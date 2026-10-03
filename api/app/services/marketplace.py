"""The guide-price-and-bidding core, shared by L1 (customer) and L2 (provider).

- The FIRST provider to accept the guide price books the request. The claim is a
  findOneAndUpdate on {status: "open"}, so two simultaneous accepts can't both win.
- A counter-offer waits for the customer: accepting it claims the request the same
  atomic way (and fails if a guide acceptance got there first); "keep waiting" declines it.
- Once booked, every other pending counter lapses and those providers are told.
- A counter whose provider can no longer take the job when the customer accepts it lapses
  instead; the request stays open and the provider is told (ruling A9).

Each action is one transaction (app.core.db.transaction): the claim, the booking with its
plan, visits and thread (or a cover's reassigned visit), the lapsed counters and every
message commit together or not at all. Two concurrent claims write the same request, so one
of them hits a write conflict; the driver re-runs it, it finds the request booked and gets
409. Checks that can fail fast run before the transaction, on plain reads.
"""

from dataclasses import dataclass
from typing import NoReturn

from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.core import money
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail
from app.core.ids import new_id
from app.core.rounding import D, round_to_pound
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


async def _request(db: Db, ref: str, session: DbSession | None = None) -> JobRequest:
    req = await JobRequests(db).by_ref(ref, session=session)
    if req is None:
        fail(status.HTTP_404_NOT_FOUND, "not_found", "That job wasn't found.")
    return req


async def _category(db: Db, category_id: str, session: DbSession | None = None) -> Category:
    cat = await Categories(db).get(category_id, session=session)
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


async def _provider_now(db: Db, provider_id: str, session: DbSession) -> Provider:
    """Inside the transaction, on every attempt: the provider as they are now, for the
    eligibility check. It writes last_booked_at first, so a suspension or document change that
    commits while this transaction runs conflicts with it: the driver re-runs the attempt,
    which then sees the change and refuses."""
    provider = await Providers(db).update(provider_id, {"last_booked_at": utcnow()}, session=session)
    assert provider is not None, provider_id
    return provider


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
    session: DbSession | None = None,
) -> JobRequest | None:
    """Atomically move an open request to booked, recording the agreed prices and the new
    booking's id in `booked`. Returns None if it wasn't open (or, with expect_guide_pence, if
    the guide has changed)."""
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
        session=session,
    )


def scaled_first_price(guide_pence: int, first_guide_pence: int | None, counter_pence: int) -> int | None:
    """A counter sets the per-visit price; the first-visit price scales by the same ratio:
    first = first-visit guide x counter / guide, rounded half-up to whole pounds. None when the
    job has no separate first-visit price."""
    if not first_guide_pence:
        return None
    return round_to_pound(D(first_guide_pence) * counter_pence / guide_pence)


async def _book(db: Db, s: Settings, req: JobRequest, session: DbSession) -> BookingOutcome:
    """Inside the claim's transaction: the booking (or the cover), lapsed counters, messages."""
    assert req.status == "booked" and req.booked is not None
    if req.cover_for_visit_id:
        return await _cover(db, s, req, session)
    b = req.booked
    customer = await Customers(db).get(req.customer_id, session=session)
    provider = await Providers(db).get(b.provider_id, session=session)
    assert customer is not None and provider is not None
    cat = await _category(db, req.category_id, session)

    booking, first = await create_booking(
        db,
        session=session,
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
    await _lapse_others(db, s, req, cat, session)
    await _notify_booked(db, s, req, cat, customer, provider, booking, first, session)
    await _withdraw_raise(db, s, req, cat, provider, booking, session)
    return BookingOutcome(request=req, booking=booking, first_visit=first, via=b.via)


async def _withdraw_raise(
    db: Db, s: Settings, req: JobRequest, cat: Category, provider: Provider, booking: Booking, session: DbSession
) -> None:
    """A16 (to A12): a raised guide still waiting for the customer when the request is booked, by any
    route, no longer applies. In the booking's transaction it's withdrawn and the customer is told
    the price they're booked at: their original guide, or the counter they accepted."""
    change = req.price_change
    if change is None or change.status != "pending":
        return
    now = utcnow()
    event = RequestEvent(at=now, kind="price_change_withdrawn", price_pence=change.guide_pence)
    withdrawn = await JobRequests(db).update(
        req.id,
        {"price_change.status": "withdrawn", "price_change.decided_at": now},
        extra_filter={"price_change.id": change.id, "price_change.status": "pending"},
        push={"events": event.model_dump(mode="python")},
        session=session,
    )
    customer = await Customers(db).get(req.customer_id, session=session)
    cu = await Users(db).get(customer.user_id, session=session) if customer else None
    if withdrawn is None or not (cu and cu.phone):
        return
    price = wording.money(booking.price_pence)
    await notify(
        db,
        "guide_raise_withdrawn",
        to=recipient_for(cu),
        settings=s,
        related=Related(request_id=req.id, booking_id=booking.id, customer_id=req.customer_id),
        idempotency_key=f"request:{req.id}:guide_raise_withdrawn:{change.id}",
        data={
            "provider": provider.short,
            "category": wording.lower_name(cat),
            "booked_at": f"the {price} you accepted" if booking.via == "counter" else f"your original price, {price}",
            "proposed": wording.money(change.guide_pence),
        },
        session=session,
    )


async def _cover(db: Db, s: Settings, req: JobRequest, session: DbSession) -> BookingOutcome:
    """A cover request was taken: the covering provider performs and is paid for that one
    visit, at the same price; the customer stays the regular provider's. The visit becomes
    performer kind "cover", so money.split_for_visit charges the standard fee even on an
    own customer's visit (decisions.md A4)."""
    assert req.booked is not None and req.cover_for_visit_id
    cover = await Providers(db).get(req.booked.provider_id, session=session)
    visit = await Visits(db).get(req.cover_for_visit_id, session=session)
    assert visit is not None and cover is not None
    covered = await Visits(db).update(
        visit.id,
        {
            "provider_id": cover.id,
            "performer": Performer(
                kind="cover", provider_id=cover.id, user_id=cover.user_id, name=cover.short
            ).model_dump(),
            "cover": {"state": "covered", "request_id": req.id, "original_provider_id": visit.provider_id},
        },
        # Still scheduled (not skipped, cancelled or under way) and not covered already, as read in
        # this transaction: a visit the customer skipped meanwhile can't be "taken".
        extra_filter={"status": "scheduled", "cover.state": {"$ne": "covered"}},
        session=session,
    )
    if covered is None:  # covered through another request already, or no longer happening: undo this claim
        if visit.status != "scheduled":
            fail(status.HTTP_409_CONFLICT, "visit_not_scheduled", "The visit this covers isn't happening any more.")
        fail(status.HTTP_409_CONFLICT, "not_open", "This job isn't open any more.")
    booking = await Bookings(db).get(covered.booking_id, session=session)
    assert booking is not None
    cat = await _category(db, covered.category_id, session)
    await _lapse_others(db, s, req, cat, session)
    await _notify_cover(db, s, req, cat, covered, cover, session)
    return BookingOutcome(request=req, booking=booking, first_visit=covered, via=req.booked.via)


async def _notify_cover(
    db: Db, s: Settings, req: JobRequest, cat: Category, visit: Visit, cover: Provider, session: DbSession
) -> None:
    regular = await Providers(db).get(visit.cover.original_provider_id or "", session=session)
    customer = await Customers(db).get(visit.customer_id, session=session)
    cu = await Users(db).get(customer.user_id, session=session) if customer else None
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
            idempotency_key=f"cover:{req.id}:cover_coming",
            data={
                "provider": regular.short,
                "date": wording.day_text(visit.local_date),
                "cover": cover.short,
                "category": wording.lower_name(cat),
            },
            session=session,
        )
    sp = money.split_for_visit(visit.price_pence, visit.source, visit.performer.kind, s)
    await _notify_provider(
        db,
        s,
        cover.id,
        "booking_confirmed",
        {
            "category": cat.name,
            "area": req.address.area,
            "when_text": wording.when_text(visit.scheduled_start, False),
            "net": wording.money(sp.provider_pence),
            "unit": "one-off",
            "fee_percent": sp.rate_percent,
            "link": link("/p/today", s),
        },
        related,
        session,
        idempotency_key=f"cover:{req.id}:booking_confirmed",
    )


async def _lapse_others(db: Db, s: Settings, req: JobRequest, cat: Category, session: DbSession) -> None:
    """Every other pending counter on the request lapses, and its provider is told."""
    assert req.booked is not None
    for o in await Offers(db).lapse_pending(req.id, except_offer_id=req.booked.offer_id, session=session):
        await _notify_provider(
            db,
            s,
            o.provider_id,
            "job_taken",
            {"category": wording.lower_name(cat), "area": req.address.area},
            Related(request_id=req.id, offer_id=o.id),
            session,
            idempotency_key=f"offer:{o.id}:job_taken",
        )


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

    async def accept(session: DbSession) -> BookingOutcome:
        _check_can_take(await _provider_now(db, provider.id, session), cat, req)
        claimed = await claim_request(
            db,
            req.id,
            provider_id=provider.id,
            price_pence=req.guide_pence,
            first_price_pence=req.first_pence,
            via="guide",
            expect_guide_pence=req.guide_pence,
            session=session,
        )
        if claimed is None:
            now = await _request(db, ref, session)
            if now.status == "open":
                fail(status.HTTP_409_CONFLICT, "price_changed", "The guide price has just changed. Have another look.")
            _taken(now)
        return await _book(db, s, claimed, session)

    return await transaction(db, accept)


async def make_counter(
    db: Db,
    s: Settings,
    ref: str,
    provider: Provider,
    *,
    price_pence: int,
    reasons: list[str],
    message: str = "",
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
    first_price = scaled_first_price(req.guide_pence, req.first_pence, price_pence)
    customer = await Customers(db).get(req.customer_id)
    cu = await Users(db).get(customer.user_id) if customer else None

    async def counter(session: DbSession) -> Offer:
        # Offers are immutable: a changed price withdraws the old offer and makes a new one, so
        # a customer accepting an offer id always gets exactly the price that offer showed.
        offers = Offers(db)
        now = utcnow()
        previous = await offers.pending_for(req.id, provider.id, session=session)
        if previous:
            await offers.update(
                previous.id,
                {"status": "withdrawn", "decided_at": now},
                extra_filter={"status": "pending"},
                session=session,
            )
        offer = Offer(
            request_id=req.id,
            provider_id=provider.id,
            price_pence=price_pence,
            guide_pence=req.guide_pence,
            first_price_pence=first_price,
            first_guide_pence=req.first_pence,
            reasons=reasons,
            message=message,
            supersedes=previous.id if previous else None,
        )
        await offers.insert(offer, session=session)
        # Writing the event on the still-open request is what keeps a concurrent booking honest:
        # the two transactions conflict, so either this counter lands before the booking (and
        # lapses with the others) or it sees the request booked and isn't made.
        event = RequestEvent(
            at=now, kind="countered", provider_id=provider.id, offer_id=offer.id, price_pence=price_pence
        )
        if await JobRequests(db).add_event(req.id, event, extra_filter={"status": "open"}, session=session) is None:
            _taken(await _request(db, ref, session))
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
                    "first_text": f" (first visit {wording.money(first_price)})" if first_price else "",
                    "guide": wording.money(req.guide_pence),
                    "category": wording.lower_name(cat),
                    "reason": f'"{reason_text}" ' if reason_text else "",
                    "link": link(f"/requests/{req.ref}", s),
                },
                related=Related(
                    request_id=req.id, offer_id=offer.id, customer_id=req.customer_id, provider_id=provider.id
                ),
                session=session,
            )
        return offer

    try:
        return await transaction(db, counter)
    except DuplicateKeyError:
        fail(status.HTTP_409_CONFLICT, "counter_in_progress", "You've just sent a price for this job.")


async def _customer_offer(db: Db, offer_id: str, customer: Customer) -> tuple[Offer, JobRequest]:
    offer = await Offers(db).get(offer_id)
    req = await JobRequests(db).get(offer.request_id) if offer else None
    if offer is None or req is None or req.customer_id != customer.id:
        fail(status.HTTP_404_NOT_FOUND, "not_found", "That offer wasn't found.")
    return offer, req


def _not_on_offer() -> None:
    fail(status.HTTP_409_CONFLICT, "offer_not_pending", "That price is no longer on offer.")


async def accept_counter(db: Db, s: Settings, offer_id: str, customer: Customer) -> BookingOutcome:
    """Book the request at exactly this offer's (immutable) terms: the offer is accepted and the
    request claimed in one transaction, so a withdrawal or a guide acceptance racing it either
    lands first (409 here) or loses."""
    offer, req = await _customer_offer(db, offer_id, customer)
    if offer.status != "pending":
        _not_on_offer()
    if req.status != "open":
        _taken(req)
    provider = await Providers(db).get(offer.provider_id)
    cat = await _category(db, req.category_id)
    if provider is None or not can_take(provider, cat).ok:
        await _lapse_unavailable(db, s, offer, req, cat, customer)

    async def accept(session: DbSession) -> BookingOutcome:
        if not can_take(await _provider_now(db, offer.provider_id, session), cat).ok:
            fail(status.HTTP_409_CONFLICT, "provider_unavailable", "That provider can't take this job any more.")
        accepted = await Offers(db).update(
            offer.id,
            {"status": "accepted", "decided_at": utcnow()},
            extra_filter={"status": "pending"},
            session=session,
        )
        if accepted is None:
            _not_on_offer()
        claimed = await claim_request(
            db,
            req.id,
            provider_id=offer.provider_id,
            price_pence=offer.price_pence,
            first_price_pence=offer.first_price_pence,
            via="counter",
            offer_id=offer.id,
            session=session,
        )
        if claimed is None:
            _taken(await _request(db, req.ref, session))
        return await _book(db, s, claimed, session)

    try:
        return await transaction(db, accept)
    except HTTPException as e:
        if isinstance(e.detail, dict) and e.detail.get("code") == "provider_unavailable":
            await _lapse_unavailable(db, s, offer, req, cat, customer)
        raise


async def _lapse_unavailable(
    db: Db, s: Settings, offer: Offer, req: JobRequest, cat: Category, customer: Customer
) -> NoReturn:
    """Ruling A9: the provider behind a counter the customer is accepting can no longer take the
    job. In a transaction of its own (the refused acceptance has already rolled back): the counter
    lapses, the still-open request records it and the provider is told why. The request stays
    open for everyone else; the customer gets a 409 they can show as it is."""
    provider = await Providers(db).get(offer.provider_id)
    who = wording.first_name(provider.name) if provider else "That provider"

    async def lapse(session: DbSession) -> None:
        now = utcnow()
        lapsed = await Offers(db).update(
            offer.id, {"status": "lapsed", "decided_at": now}, extra_filter={"status": "pending"}, session=session
        )
        if lapsed is None:
            _not_on_offer()
        event = RequestEvent(at=now, kind="counter_lapsed", provider_id=offer.provider_id, offer_id=offer.id)
        if await JobRequests(db).add_event(req.id, event, extra_filter={"status": "open"}, session=session) is None:
            _taken(await _request(db, req.ref, session))
        if provider is not None:
            reasons = can_take(provider, cat).reasons
            await _notify_provider(
                db,
                s,
                provider.id,
                "counter_lapsed",
                {
                    "customer": wording.first_name(customer.name) or "The customer",
                    "price": wording.money(offer.price_pence),
                    "category": wording.lower_name(cat),
                    "area": req.address.area,
                    "reason": " ".join(reasons) or "Your account can't take new jobs right now.",
                    "link": link("/p/me", s),
                },
                Related(request_id=req.id, offer_id=offer.id),
                session,
                idempotency_key=f"offer:{offer.id}:counter_lapsed",
            )

    await transaction(db, lapse)
    fail(
        status.HTTP_409_CONFLICT,
        "provider_unavailable",
        f"{who} can no longer take this job. We're still finding someone local.",
    )


async def decline_counter(db: Db, s: Settings, offer_id: str, customer: Customer) -> Offer:
    """The customer's "Keep waiting": decline this counter, stay open for the guide price."""
    offer, req = await _customer_offer(db, offer_id, customer)
    cat = await _category(db, req.category_id)

    async def decline(session: DbSession) -> Offer:
        now = utcnow()
        updated = await Offers(db).update(
            offer.id, {"status": "declined", "decided_at": now}, extra_filter={"status": "pending"}, session=session
        )
        if updated is None:
            _not_on_offer()
        event = RequestEvent(at=now, kind="counter_declined", provider_id=offer.provider_id, offer_id=offer.id)
        current = await JobRequests(db).add_event(req.id, event, session=session)
        if current is not None and current.status == "open":
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
                session,
            )
        return updated

    return await transaction(db, decline)


async def _notify_provider(
    db: Db,
    s: Settings,
    provider_id: str,
    template_id: str,
    data: dict,
    related: Related,
    session: DbSession,
    idempotency_key: str | None = None,
) -> None:
    provider = await Providers(db).get(provider_id, session=session)
    user = await Users(db).get(provider.user_id, session=session) if provider else None
    if user and user.phone:
        await notify(
            db,
            template_id,
            to=recipient_for(user),
            data=data,
            related=related.model_copy(update={"provider_id": provider_id}),
            settings=s,
            idempotency_key=idempotency_key,
            session=session,
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
    session: DbSession,
) -> None:
    related = Related(
        request_id=req.id, booking_id=booking.id, visit_id=first.id, customer_id=customer.id, provider_id=provider.id
    )
    when = wording.when_text(first.scheduled_start, booking.recurring)
    cu = await Users(db).get(customer.user_id, session=session)
    if cu and cu.phone:
        await notify(
            db,
            "request_booked",
            to=recipient_for(cu),
            settings=s,
            related=related,
            idempotency_key=f"booking:{booking.id}:request_booked",
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
            session=session,
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
        session,
        idempotency_key=f"booking:{booking.id}:booking_confirmed",
    )
