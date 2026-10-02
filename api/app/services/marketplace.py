"""The guide-price-and-bidding core, shared by L1 (customer) and L2 (provider).

- The FIRST provider to accept the guide price books the request. claim_request is a
  single findOneAndUpdate on {status: "open"}, so two simultaneous accepts can't both win.
- A counter-offer waits for the customer: accepting it claims the request the same
  atomic way (and fails if a guide acceptance got there first); "keep waiting" declines it.
- Once booked, every other pending counter lapses and those providers are told.
"""

from dataclasses import dataclass

from fastapi import status
from pymongo.errors import DuplicateKeyError

from app.core import money
from app.core.config import Settings
from app.core.db import Db
from app.core.errors import fail
from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.models.bookings import Booking
from app.models.categories import Category
from app.models.common import Related
from app.models.customers import Customer
from app.models.job_requests import Booked, JobRequest, RequestEvent
from app.models.offers import Offer
from app.models.providers import Provider
from app.models.visits import Performer, Visit
from app.repos.bookings import Bookings
from app.repos.categories import Categories
from app.repos.customers import Customers
from app.repos.job_requests import JobRequests
from app.repos.offers import Offers
from app.repos.providers import Providers
from app.repos.users import Users
from app.repos.visits import Visits
from app.services import wording
from app.services.bookings import create_booking
from app.services.eligibility import can_take
from app.services.notify import link, notify, recipient_for

COUNTER_MIN_RATIO = 0.8  # the prototype's stepper: 80% of the guide ...
COUNTER_MAX_RATIO = 3  # ... to three times it, in whole pounds


@dataclass(frozen=True)
class BookingOutcome:
    request: JobRequest
    booking: Booking
    first_visit: Visit
    via: str


async def _request(db: Db, ref: str) -> JobRequest:
    req = await JobRequests(db).by_ref(ref)
    if req is None:
        fail(status.HTTP_404_NOT_FOUND, "not_found", "That job wasn't found.")
    return req


async def _category(db: Db, category_id: str) -> Category:
    cat = await Categories(db).get(category_id)
    assert cat is not None, category_id
    return cat


def _taken(req: JobRequest) -> None:
    if req.status == "booked":
        fail(status.HTTP_409_CONFLICT, "already_taken", "Sorry, someone else took this job first.")
    fail(status.HTTP_409_CONFLICT, "not_open", "This job isn't open any more.")


def _check_can_take(provider: Provider, cat: Category, req: JobRequest) -> None:
    if req.direct_provider_id and req.direct_provider_id != provider.id:
        fail(status.HTTP_403_FORBIDDEN, "not_offered_to_you", "This job was offered to someone else.")
    elig = can_take(provider, cat)
    if not elig.ok:
        fail(
            status.HTTP_403_FORBIDDEN, "not_eligible", " ".join(elig.reasons), missing_documents=elig.missing_documents
        )


async def claim_request(
    db: Db,
    request_id: str,
    *,
    provider_id: str,
    price_pence: int,
    first_price_pence: int | None,
    via: str,
    offer_id: str | None = None,
    expect_guide_pence: int | None = None,
) -> JobRequest | None:
    """Atomically move an open request to booked, freezing the agreed prices in `booked`.
    Returns None if it wasn't open (or, with expect_guide_pence, if the guide has changed)."""
    now = utcnow()
    booked = Booked(
        booking_id=new_id(),
        provider_id=provider_id,
        price_pence=price_pence,
        first_price_pence=first_price_pence,
        via=via,  # type: ignore[arg-type]
        offer_id=offer_id,
        at=now,
    )
    event = RequestEvent(at=now, kind="accepted", provider_id=provider_id, offer_id=offer_id, price_pence=price_pence)
    flt: dict = {"_id": request_id, "status": "open"}
    if expect_guide_pence is not None:
        flt["guide_pence"] = expect_guide_pence
    return await JobRequests(db).find_one_and_update(
        flt,
        {
            "$set": {"status": "booked", "booked": booked.model_dump(mode="python"), "updated_at": now},
            "$push": {"events": event.model_dump(mode="python")},
        },
    )


def counter_first_price(req: JobRequest, offer: Offer) -> int | None:
    """A counter sets the per-visit price. Unless the provider named a first-visit price, the
    first visit is the higher of the counter and the request's first-visit guide (decisions.md Q1)."""
    if offer.first_price_pence:
        return offer.first_price_pence
    return max(req.first_pence, offer.price_pence) if req.first_pence else None


async def complete_claimed(db: Db, s: Settings, req: JobRequest) -> BookingOutcome:
    """Create the booking for a claimed request, lapse other counters, send messages.
    Idempotent: safe to re-run for a request whose booking write was interrupted."""
    assert req.status == "booked" and req.booked is not None
    if req.cover_for_visit_id:
        return await _complete_cover(db, s, req)
    b = req.booked
    customer = await Customers(db).get(req.customer_id)
    provider = await Providers(db).get(b.provider_id)
    assert customer is not None and provider is not None
    cat = await _category(db, req.category_id)

    booking, first = await create_booking(
        db,
        booking_id=b.booking_id,
        source="platform",
        via=b.via,
        customer=customer,
        provider=provider,
        category_id=cat.id,
        price_pence=b.price_pence,
        first_price_pence=b.first_price_pence if b.first_price_pence != b.price_pence else None,
        unit=req.unit,
        frequency=req.frequency,
        est_mins=req.mins,
        first_est_mins=req.first_mins,
        address=req.address,
        answers=req.answers,
        notes=req.notes,
        days=req.when.days,
        window=req.when.time,
        request_id=req.id,
        pricing_version_id=req.pricing_version_id,
    )

    lapsed = await Offers(db).lapse_pending(req.id, except_offer_id=b.offer_id)
    for o in lapsed:
        await _notify_provider(
            db,
            s,
            o.provider_id,
            "job_taken",
            {"category": wording.lower_name(cat), "area": req.address.area},
            Related(request_id=req.id, offer_id=o.id),
        )
    # Booking messages: sent, then marked, so a resumed setup re-sends any that never went
    # out (at least once). Only the claim's winner and, after a grace period, the repair task
    # ever get here, so they don't race.
    if booking.confirmations_sent_at is None:
        await _notify_booked(db, s, req, cat, customer, provider, booking, first)
        booking = await Bookings(db).update(booking.id, {"confirmations_sent_at": utcnow()}) or booking
    return BookingOutcome(request=req, booking=booking, first_visit=first, via=b.via)


async def _complete_cover(db: Db, s: Settings, req: JobRequest) -> BookingOutcome:
    """A cover request was taken: the covering provider performs and is paid for that one
    visit, at the same price; the customer stays the regular provider's. The visit keeps its
    booking's source (so its fee mode) - see decisions.md Q5."""
    assert req.booked is not None and req.cover_for_visit_id
    visits = Visits(db)
    visit = await visits.get(req.cover_for_visit_id)
    cover = await Providers(db).get(req.booked.provider_id)
    assert visit is not None and cover is not None
    if visit.cover.state != "covered":
        visit = (
            await visits.update(
                visit.id,
                {
                    "provider_id": cover.id,
                    "performer": Performer(
                        kind="cover", provider_id=cover.id, user_id=cover.user_id, name=cover.short
                    ).model_dump(),
                    "cover": {"state": "covered", "request_id": req.id, "original_provider_id": visit.provider_id},
                },
            )
            or visit
        )
        booking = await Bookings(db).get(visit.booking_id)
        regular = await Providers(db).get(visit.cover.original_provider_id or "")
        customer = await Customers(db).get(visit.customer_id)
        cat = await _category(db, visit.category_id)
        cu = await Users(db).get(customer.user_id) if customer else None
        related = Related(
            request_id=req.id,
            visit_id=visit.id,
            booking_id=visit.booking_id,
            customer_id=visit.customer_id,
            provider_id=cover.id,
        )
        if cu and cu.phone and regular:
            await notify(
                db,
                "cover_coming",
                to=recipient_for(cu),
                settings=s,
                related=related,
                data={
                    "provider": regular.short,
                    "date": wording.day_text(visit.local_date),
                    "cover": cover.short,
                    "category": wording.lower_name(cat),
                },
            )
        await Offers(db).lapse_pending(req.id, except_offer_id=req.booked.offer_id)
        assert booking is not None
        return BookingOutcome(request=req, booking=booking, first_visit=visit, via=req.booked.via)
    booking = await Bookings(db).get(visit.booking_id)
    assert booking is not None
    return BookingOutcome(request=req, booking=booking, first_visit=visit, via=req.booked.via)


async def _check_not_own_cover(db: Db, provider: Provider, req: JobRequest) -> None:
    if req.cover_for_visit_id:
        visit = await Visits(db).get(req.cover_for_visit_id)
        if visit and visit.provider_id == provider.id:
            fail(status.HTTP_403_FORBIDDEN, "own_visit", "This is cover for your own visit.")


async def accept_at_guide(db: Db, s: Settings, ref: str, provider: Provider) -> BookingOutcome:
    req = await _request(db, ref)
    cat = await _category(db, req.category_id)
    _check_can_take(provider, cat, req)
    await _check_not_own_cover(db, provider, req)
    if req.status != "open":
        _taken(req)
    claimed = await claim_request(
        db,
        req.id,
        provider_id=provider.id,
        price_pence=req.guide_pence,
        first_price_pence=req.first_pence,
        via="guide",
        expect_guide_pence=req.guide_pence,
    )
    if claimed is None:
        now = await _request(db, ref)
        if now.status == "open":
            fail(status.HTTP_409_CONFLICT, "price_changed", "The guide price has just changed. Have another look.")
        _taken(now)
    return await complete_claimed(db, s, claimed)


async def make_counter(
    db: Db,
    s: Settings,
    ref: str,
    provider: Provider,
    *,
    price_pence: int,
    reasons: list[str],
    message: str = "",
    first_price_pence: int | None = None,
) -> Offer:
    req = await _request(db, ref)
    cat = await _category(db, req.category_id)
    _check_can_take(provider, cat, req)
    await _check_not_own_cover(db, provider, req)
    if req.status != "open":
        _taken(req)
    if req.cover_for_visit_id:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "cover_is_fixed_price", "Cover is at the regular price.")
    lo = round(req.guide_pence * COUNTER_MIN_RATIO / 100) * 100
    hi = req.guide_pence * COUNTER_MAX_RATIO
    if price_pence % 100 or not lo <= price_pence <= hi:
        fail(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "price_out_of_range",
            f"Suggest a whole-pound price between {wording.money(lo)} and {wording.money(hi)}.",
        )
    if price_pence == req.guide_pence:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "same_as_guide", "That's the guide price. Accept it instead.")

    # Offers are immutable: a changed price withdraws the old offer and makes a new one, so a
    # customer accepting an offer id always gets exactly the price that offer showed.
    offers = Offers(db)
    now = utcnow()
    previous = await offers.pending_for(req.id, provider.id)
    if previous:
        await offers.update(previous.id, {"status": "withdrawn", "decided_at": now}, extra_filter={"status": "pending"})
    offer = Offer(
        request_id=req.id,
        provider_id=provider.id,
        price_pence=price_pence,
        guide_pence=req.guide_pence,
        first_price_pence=first_price_pence,
        reasons=reasons,
        message=message,
        supersedes=previous.id if previous else None,
    )
    try:
        await offers.insert(offer)
    except DuplicateKeyError:
        fail(status.HTTP_409_CONFLICT, "counter_in_progress", "You've just sent a price for this job.")
    if (await JobRequests(db).get(req.id) or req).status != "open":  # booked while we were writing
        await offers.update(offer.id, {"status": "lapsed", "decided_at": now}, extra_filter={"status": "pending"})
        _taken(await JobRequests(db).get(req.id) or req)
    await JobRequests(db).add_event(
        req.id,
        RequestEvent(at=now, kind="countered", provider_id=provider.id, offer_id=offer.id, price_pence=price_pence),
    )
    customer = await Customers(db).get(req.customer_id)
    cu = await Users(db).get(customer.user_id) if customer else None
    if cu and cu.phone:
        reason_text = (message.strip() or "; ".join(reasons)).strip()
        await notify(
            db,
            "counter_offer",
            to=recipient_for(cu),
            settings=s,
            data={
                "provider": provider.short,
                "price": wording.money(price_pence),
                "guide": wording.money(req.guide_pence),
                "category": wording.lower_name(cat),
                "reason": f'"{reason_text}" ' if reason_text else "",
                "link": link(f"/requests/{req.ref}", s),
            },
            related=Related(request_id=req.id, offer_id=offer.id, customer_id=req.customer_id, provider_id=provider.id),
        )
    return offer


async def _customer_offer(db: Db, offer_id: str, customer: Customer) -> tuple[Offer, JobRequest]:
    offer = await Offers(db).get(offer_id)
    req = await JobRequests(db).get(offer.request_id) if offer else None
    if offer is None or req is None or req.customer_id != customer.id:
        fail(status.HTTP_404_NOT_FOUND, "not_found", "That offer wasn't found.")
    return offer, req


async def accept_counter(db: Db, s: Settings, offer_id: str, customer: Customer) -> BookingOutcome:
    """Book the request at exactly this offer's (immutable) terms. The offer is taken first
    (pending -> accepted, atomically) so a withdrawal can't slip in; if the request was booked
    by someone else meanwhile, the offer lapses and the customer gets 409."""
    offer, req = await _customer_offer(db, offer_id, customer)
    if offer.status != "pending":
        fail(status.HTTP_409_CONFLICT, "offer_not_pending", "That price is no longer on offer.")
    if req.status != "open":
        _taken(req)
    provider = await Providers(db).get(offer.provider_id)
    cat = await _category(db, req.category_id)
    if provider is None or not can_take(provider, cat).ok:
        fail(status.HTTP_409_CONFLICT, "provider_unavailable", "That provider can't take this job any more.")
    offers = Offers(db)
    now = utcnow()
    taken = await offers.update(offer.id, {"status": "accepted", "decided_at": now}, extra_filter={"status": "pending"})
    if taken is None:
        fail(status.HTTP_409_CONFLICT, "offer_not_pending", "That price is no longer on offer.")
    claimed = await claim_request(
        db,
        req.id,
        provider_id=offer.provider_id,
        price_pence=offer.price_pence,
        first_price_pence=counter_first_price(req, offer),
        via="counter",
        offer_id=offer.id,
    )
    if claimed is None:
        await offers.update(offer.id, {"status": "lapsed", "decided_at": utcnow()})
        _taken(await JobRequests(db).get(req.id) or req)
    return await complete_claimed(db, s, claimed)


async def decline_counter(db: Db, s: Settings, offer_id: str, customer: Customer) -> Offer:
    """The customer's "Keep waiting": decline this counter, stay open for the guide price."""
    offer, req = await _customer_offer(db, offer_id, customer)
    now = utcnow()
    updated = await Offers(db).update(
        offer.id, {"status": "declined", "decided_at": now}, extra_filter={"status": "pending"}
    )
    if updated is None:
        fail(status.HTTP_409_CONFLICT, "offer_not_pending", "That price is no longer on offer.")
    await JobRequests(db).add_event(
        req.id, RequestEvent(at=now, kind="counter_declined", provider_id=offer.provider_id, offer_id=offer.id)
    )
    if req.status == "open":
        cat = await _category(db, req.category_id)
        await _notify_provider(
            db,
            s,
            offer.provider_id,
            "counter_declined",
            {
                "customer": customer.name.split(" ")[0] or "The customer",
                "guide": wording.money(req.guide_pence),
                "category": wording.lower_name(cat),
                "area": req.address.area,
                "link": link(f"/p/j/{req.ref}", s),
            },
            Related(request_id=req.id, offer_id=offer.id),
        )
    return updated


async def _notify_provider(
    db: Db, s: Settings, provider_id: str, template_id: str, data: dict, related: Related
) -> None:
    provider = await Providers(db).get(provider_id)
    user = await Users(db).get(provider.user_id) if provider else None
    if user and user.phone:
        await notify(
            db,
            template_id,
            to=recipient_for(user),
            data=data,
            related=related.model_copy(update={"provider_id": provider_id}),
            settings=s,
        )


async def _notify_booked(
    db: Db,
    s: Settings,
    req: JobRequest,
    cat: Category,
    customer: Customer,
    provider: Provider,
    booking: Booking,
    first: Visit,
) -> None:
    related = Related(
        request_id=req.id, booking_id=booking.id, visit_id=first.id, customer_id=customer.id, provider_id=provider.id
    )
    when = wording.when_text(first.scheduled_start, booking.recurring)
    cu = await Users(db).get(customer.user_id)
    if cu and cu.phone:
        await notify(
            db,
            "request_booked",
            to=recipient_for(cu),
            settings=s,
            related=related,
            data={
                "provider": provider.short,
                "provider_first": wording.first_name(provider.name),
                "category": wording.lower_name(cat),
                "when_text": when,
                "price": wording.money(booking.price_pence),
                "unit": booking.unit,
                "charged_after": "each visit" if booking.recurring else "the job",
                "link": link(f"/bookings/{booking.id}", s),
            },
        )
    sp = money.split(booking.price_pence, "standard", s)
    await _notify_provider(
        db,
        s,
        provider.id,
        "booking_confirmed",
        {
            "category": cat.name,
            "area": req.address.area,
            "when_text": when,
            "net": wording.money(sp.provider_pence),
            "unit": booking.unit,
            "fee_percent": sp.rate_percent,
            "link": link("/p/today", s),
        },
        related,
    )
