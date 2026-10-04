"""Changing how often a plan's visits happen (ruling A10).

The new frequency is re-priced from the pricing engine (services.quotes.create_quote, so the
quote records the pricing version), keeping any counter the provider negotiated in proportion:
new price = new guide x agreed price / original guide, half-up to whole pounds. A dearer first
visit doesn't apply to an existing plan. The provider gets the new price to accept or decline
through a single-use link in a text; until they accept, the plan carries on unchanged, and
unanswered for 48 hours the change lapses and the customer is told. Each step sends an outbox
message. The web never works out a price: it shows what these functions return.
"""

from dataclasses import dataclass
from datetime import timedelta

from fastapi import status

from app.adapters.area.base import AreaInput
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.core.ids import new_token, token_hash
from app.core.rounding import D, round_to_pound
from app.core.timeutil import utcnow
from app.customer import account
from app.customer.views import plan_frequencies
from app.models.bookings import Booking, Series
from app.models.categories import Category
from app.models.common import Related
from app.models.customers import Customer
from app.models.job_requests import JobRequest
from app.models.plan_changes import PlanChange
from app.models.users import User
from app.repos.bookings import Bookings
from app.repos.categories import Categories
from app.repos.customers import Customers
from app.repos.job_requests import JobRequests
from app.repos.offers import Offers
from app.repos.plan_changes import PlanChanges
from app.repos.providers import Providers
from app.repos.series import SeriesRepo
from app.repos.users import Users
from app.services import wording
from app.services.notify import link, notify, recipient_for
from app.services.quotes import create_quote

ANSWER_WITHIN = timedelta(hours=48)
DEFAULT_BAND = "medium"  # a lawn plan with no size on record (an own customer's)


@dataclass(frozen=True)
class Reprice:
    frequency: str
    price_pence: int
    new_guide_pence: int
    original_guide_pence: int
    quote_id: str
    reference_quote_id: str | None


def words(frequency: str) -> str:
    return wording.FREQUENCY_WORDS.get(frequency, frequency)


def scaled_price(new_guide_pence: int, agreed_pence: int, original_guide_pence: int) -> int:
    """A10: keep what the provider negotiated in proportion, half-up to whole pounds."""
    return round_to_pound(D(new_guide_pence) * agreed_pence / original_guide_pence)


def offered_frequencies(cat: Category) -> list[str]:
    return plan_frequencies(cat)


async def _category(db: Db, category_id: str) -> Category:
    cat = await Categories(db).get(category_id)
    assert cat is not None, category_id
    return cat


async def _booked_guide(db: Db, req: JobRequest) -> int | None:
    """The guide the booked price was agreed against: an accepted counter's own guide (offers keep
    it, so a guide raised and approved later doesn't change it, A12), else the guide it was booked
    at."""
    b = req.booked
    if b and b.via == "counter" and b.offer_id:
        offer = await Offers(db).get(b.offer_id)
        if offer is not None:
            return offer.guide_pence
    if b and b.via in ("guide", "direct"):
        return b.price_pence
    return req.guide_pence or None


async def reprice(db: Db, s: Settings, series: Series, booking: Booking, frequency: str, user_id: str) -> Reprice:
    """The plan's price at another frequency."""
    if series.status == "cancelled":
        fail(status.HTTP_409_CONFLICT, "plan_cancelled", "This plan is cancelled.")
    cat = await _category(db, series.category_id)
    offered = offered_frequencies(cat)
    if frequency not in offered or series.frequency not in offered:
        fail(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "frequency_not_offered",
            f"{cat.name} isn't offered {words(frequency)}."
            if series.frequency in offered
            else "Message your provider to change how often this plan runs.",
        )
    req = await JobRequests(db).get(booking.request_id) if booking.request_id else None
    lawn = None
    if cat.measure == "lawn":
        m = req.measure if req else None
        lawn = AreaInput(band=m.band or DEFAULT_BAND, adjust=m.adjust or "right") if m else AreaInput(band=DEFAULT_BAND)

    async def guide_at(freq: str) -> tuple[int, str]:
        q = await create_quote(
            db,
            s,
            category_id=cat.id,
            answers={**booking.answers, "frequency": freq},
            lawn=lawn,
            address=booking.address,
            user_id=user_id,
        )
        return q.result.price_pence, q.id

    new_guide, quote_id = await guide_at(frequency)
    # The guide the agreed price was set against: the last accepted change's, else the request's
    # (what the customer was quoted), else for an own customer's plan the engine's price now.
    last = await PlanChanges(db).find_one({"series_id": series.id, "status": "accepted"}, sort=[("decided_at", -1)])
    reference_quote_id = None
    if last is not None:
        original = last.new_guide_pence
    elif req is not None and (booked_guide := await _booked_guide(db, req)):
        original = booked_guide
    else:
        original, reference_quote_id = await guide_at(series.frequency)
    if original <= 0:
        fail(status.HTTP_409_CONFLICT, "cannot_reprice", "We can't price that change. Message your provider instead.")
    return Reprice(
        frequency=frequency,
        price_pence=scaled_price(new_guide, series.price_pence, original),
        new_guide_pence=new_guide,
        original_guide_pence=original,
        quote_id=quote_id,
        reference_quote_id=reference_quote_id,
    )


async def request_change(
    db: Db,
    s: Settings,
    series: Series,
    booking: Booking,
    customer: Customer,
    user: User,
    frequency: str,
    expected_price_pence: int | None,
) -> PlanChange:
    """The customer asks: the provider is texted the re-priced plan; the plan doesn't change yet.
    Asking again replaces a change still waiting. The customer names the price they were shown;
    if pricing has moved since, nothing is sent and they see the new price first."""
    if frequency == series.frequency:
        fail(status.HTTP_409_CONFLICT, "same_frequency", f"Your plan is already {words(frequency)}.")
    if expected_price_pence is None:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "price_needed", "See the new price first, then ask.")
    priced = await reprice(db, s, series, booking, frequency, user.id)
    if priced.price_pence != expected_price_pence:
        fail(
            status.HTTP_409_CONFLICT,
            "price_changed",
            f"The price for that has just changed to {wording.money(priced.price_pence)} a visit. Have another look.",
            price_pence=priced.price_pence,
        )
    cat = await _category(db, series.category_id)
    provider = await Providers(db).get(series.provider_id)
    pu = await Users(db).get(provider.user_id) if provider else None
    assert provider is not None
    token = new_token(24)
    now = utcnow()
    change = PlanChange(
        series_id=series.id,
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=provider.id,
        category_id=cat.id,
        from_frequency=series.frequency,
        to_frequency=frequency,  # type: ignore[arg-type]
        from_price_pence=series.price_pence,
        to_price_pence=priced.price_pence,
        new_guide_pence=priced.new_guide_pence,
        original_guide_pence=priced.original_guide_pence,
        quote_id=priced.quote_id,
        reference_quote_id=priced.reference_quote_id,
        token_hash=token_hash(token, s.pepper),
        requested_by=user.id,
        expires_at=now + ANSWER_WITHIN,
    )
    related = Related(series_id=series.id, booking_id=booking.id, customer_id=customer.id, provider_id=provider.id)
    deadline = f"{wording.day_text(change.expires_at)} at {wording.time_text(change.expires_at)}"

    async def ask(session: DbSession) -> PlanChange:
        # The price was worked out from the plan as it was read (its frequency, price and the last
        # accepted change). A guarded write on the plan binds the proposal to that state: if a change
        # was accepted (or the plan cancelled) since, it doesn't match and nothing is sent; a
        # concurrent acceptance conflicts with this write and the re-run sees it.
        if await SeriesRepo(db).update(series.id, {}, extra_filter=_as_priced(change), session=session) is None:
            _plan_moved()
        changes = PlanChanges(db)
        if (previous := await changes.pending_for(series.id, session=session)) is not None:
            await changes.update(
                previous.id,
                {"status": "withdrawn", "decided_at": now},
                extra_filter={"status": "pending"},
                session=session,
            )
        await changes.insert(change, session=session)
        if pu and pu.phone:
            await notify(
                db,
                "plan_change_proposed",
                to=recipient_for(pu),
                settings=s,
                related=related,
                idempotency_key=f"plan_change:{change.id}:proposed",
                data={
                    "customer": wording.first_name(customer.name) or "Your customer",
                    "category": wording.lower_name(cat),
                    "new_frequency": words(frequency),
                    "old_frequency": words(series.frequency),
                    "price": wording.money(priced.price_pence),
                    "current": wording.money(series.price_pence),
                    "deadline": deadline,
                    "link": link(f"/p/plan-change/{token}", s),
                },
                session=session,
            )
        if user.phone:
            await notify(
                db,
                "plan_change_requested",
                to=recipient_for(user),
                settings=s,
                related=related,
                idempotency_key=f"plan_change:{change.id}:requested",
                data={
                    "provider": provider.short,
                    "category": wording.lower_name(cat),
                    "new_frequency": words(frequency),
                    "price": wording.money(priced.price_pence),
                },
                session=session,
            )
        await account.system_note(
            db,
            booking.thread_id,
            f"{customer.name} asked to change the plan to {words(frequency)} at {wording.money(priced.price_pence)} a "
            "visit. The plan carries on as it is unless it's accepted.",
            session,
        )
        return change

    return await transaction(db, ask)


def _as_priced(change: PlanChange) -> dict:
    """The plan as the change was priced from: not cancelled, same frequency and price."""
    return {"status": {"$ne": "cancelled"}, "frequency": change.from_frequency, "price_pence": change.from_price_pence}


def _plan_moved() -> None:
    fail(status.HTTP_409_CONFLICT, "plan_changed", "This plan has just changed. Have another look.")


# ------------------------------------------------------------------------------- the provider's answer


@dataclass(frozen=True)
class Found:
    change: PlanChange
    series: Series
    booking: Booking
    customer: Customer


async def find(db: Db, s: Settings, token: str) -> Found:
    change = await PlanChanges(db).by_token_hash(token_hash(token, s.pepper))
    if change is None:
        not_found("That plan change")
    series = await SeriesRepo(db).get(change.series_id)
    booking = await Bookings(db).get(change.booking_id)
    customer = await Customers(db).get(change.customer_id)
    assert series is not None and booking is not None and customer is not None
    if change.status == "pending" and change.expires_at <= utcnow():
        await lapse(db, s, change)
        change = await PlanChanges(db).get(change.id) or change
    return Found(change, series, booking, customer)


def _closed(change: PlanChange) -> None:
    messages = {
        "accepted": "You've already accepted this change.",
        "declined": "You've already declined this change.",
        "lapsed": "This change lapsed after 48 hours without an answer.",
        "withdrawn": "The customer has withdrawn or replaced this change.",
    }
    fail(status.HTTP_409_CONFLICT, f"change_{change.status}", messages.get(change.status, "This change is closed."))


async def _customer_user(db: Db, customer: Customer, session: DbSession) -> User | None:
    return await Users(db).get(customer.user_id, session=session)


async def accept(db: Db, s: Settings, found: Found) -> PlanChange:
    change, series, booking, customer = found.change, found.series, found.booking, found.customer
    if change.status != "pending":
        _closed(change)
    provider = await Providers(db).get(change.provider_id)
    cat = await _category(db, change.category_id)
    assert provider is not None

    async def apply(session: DbSession) -> PlanChange:
        now = utcnow()
        accepted = await PlanChanges(db).update(
            change.id,
            {"status": "accepted", "decided_at": now},
            extra_filter={"status": "pending", "expires_at": {"$gt": now}},
            session=session,
        )
        if accepted is None:
            current = await PlanChanges(db).get(change.id, session=session)
            _closed(current or change)
        current_series = await SeriesRepo(db).find_one({"_id": series.id, **_as_priced(change)}, session=session)
        if current_series is None:  # cancelled, or changed since this was priced: it no longer applies
            fail(
                status.HTTP_409_CONFLICT,
                "plan_changed",
                "The customer's plan has changed since, so this no longer applies.",
            )
        _, nxt = await account.apply_frequency_change(
            db, current_series, booking, provider, change.to_frequency, change.to_price_pence, session=session
        )
        cu = await _customer_user(db, customer, session)
        if cu and cu.phone:
            await notify(
                db,
                "plan_change_accepted",
                to=recipient_for(cu),
                settings=s,
                related=Related(series_id=series.id, booking_id=booking.id, customer_id=customer.id),
                idempotency_key=f"plan_change:{change.id}:accepted",
                data={
                    "provider": provider.short,
                    "category": wording.lower_name(cat),
                    "new_frequency": words(change.to_frequency),
                    "price": wording.money(change.to_price_pence),
                    "next_text": f"Your next visit is {wording.day_text(nxt.local_date)}." if nxt else "",
                },
                session=session,
            )
        await account.system_note(
            db,
            booking.thread_id,
            f"{provider.short} accepted: the plan is now {words(change.to_frequency)} at "
            f"{wording.money(change.to_price_pence)} a visit.",
            session,
        )
        return accepted

    return await transaction(db, apply)


async def decline(db: Db, s: Settings, found: Found) -> PlanChange:
    change, booking, customer = found.change, found.booking, found.customer
    if change.status != "pending":
        _closed(change)
    provider = await Providers(db).get(change.provider_id)
    cat = await _category(db, change.category_id)
    assert provider is not None

    async def apply(session: DbSession) -> PlanChange:
        declined = await PlanChanges(db).update(
            change.id,
            {"status": "declined", "decided_at": utcnow()},
            extra_filter={"status": "pending"},
            session=session,
        )
        if declined is None:
            current = await PlanChanges(db).get(change.id, session=session)
            _closed(current or change)
        cu = await _customer_user(db, customer, session)
        if cu and cu.phone:
            await notify(
                db,
                "plan_change_declined",
                to=recipient_for(cu),
                settings=s,
                related=Related(series_id=change.series_id, booking_id=booking.id, customer_id=customer.id),
                idempotency_key=f"plan_change:{change.id}:declined",
                data={
                    "provider": provider.short,
                    "category": wording.lower_name(cat),
                    "old_frequency": words(change.from_frequency),
                    "current": wording.money(change.from_price_pence),
                },
                session=session,
            )
        await account.system_note(
            db, booking.thread_id, f"{provider.short} would rather keep the plan as it is.", session
        )
        return declined

    return await transaction(db, apply)


async def lapse(db: Db, s: Settings, change: PlanChange) -> bool:
    """Unanswered for 48 hours: the change lapses and the customer is told. True if it did."""
    provider = await Providers(db).get(change.provider_id)
    cat = await _category(db, change.category_id)
    customer = await Customers(db).get(change.customer_id)

    async def apply(session: DbSession) -> bool:
        now = utcnow()
        lapsed = await PlanChanges(db).update(
            change.id,
            {"status": "lapsed", "decided_at": now},
            extra_filter={"status": "pending", "expires_at": {"$lte": now}},
            session=session,
        )
        if lapsed is None:
            return False
        cu = await _customer_user(db, customer, session) if customer else None
        if cu and cu.phone:
            await notify(
                db,
                "plan_change_lapsed",
                to=recipient_for(cu),
                settings=s,
                related=Related(
                    series_id=change.series_id, booking_id=change.booking_id, customer_id=change.customer_id
                ),
                idempotency_key=f"plan_change:{change.id}:lapsed",
                data={
                    "provider": provider.short if provider else "Your provider",
                    "category": wording.lower_name(cat),
                    "old_frequency": words(change.from_frequency),
                    "current": wording.money(change.from_price_pence),
                },
                session=session,
            )
        return True

    return await transaction(db, apply)


async def lapse_stale(db: Db, s: Settings) -> int:
    n = 0
    for change in await PlanChanges(db).find({"status": "pending", "expires_at": {"$lte": utcnow()}}, limit=200):
        if await lapse(db, s, change):
            n += 1
    return n
