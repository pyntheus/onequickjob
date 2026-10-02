"""Turning an agreement into a booking, its plan (series), first visit and message thread.

Used by the marketplace (a request booked at the guide price or an accepted counter) and
by own-customer invites (L1 accepts, L2 created the invite).

Resumable by design (there are no multi-document transactions on a standalone Mongo):

1. ensure_booking inserts the booking with everything later steps need, including the
   first visit's slot, or returns the existing one (unique request_id / invite_id).
2. finish_setup idempotently ensures the series, the first visit, the visit horizon and the
   message thread, then marks the booking setup_complete.

A crash between any two writes is repaired by calling create_booking again (the
marketplace's repair task does this for requests whose booking isn't setup_complete).
"""

from datetime import date

from pymongo.errors import DuplicateKeyError

from app.core.db import Db
from app.core.ids import new_id, next_ref
from app.core.timeutil import to_london
from app.models.bookings import Booking, Frequency, Series
from app.models.common import Address, BookingSource, DaysPref, TimePref
from app.models.customers import Customer
from app.models.messages import MessageThread, Participant
from app.models.providers import Provider
from app.models.quotes import Unit
from app.models.visits import Performer, Visit
from app.repos.bookings import Bookings
from app.repos.messages import MessageThreads
from app.repos.series import SeriesRepo
from app.repos.users import Users
from app.repos.visits import Visits
from app.services import schedule


async def create_booking(
    db: Db,
    *,
    booking_id: str | None = None,
    source: BookingSource,
    via: str,
    customer: Customer,
    provider: Provider,
    category_id: str,
    price_pence: int,
    first_price_pence: int | None,
    unit: Unit,
    frequency: str | None,
    est_mins: int,
    first_est_mins: int | None,
    address: Address,
    answers: dict,
    notes: str,
    days: DaysPref,
    window: TimePref,
    request_id: str | None = None,
    invite_id: str | None = None,
    pricing_version_id: str | None = None,
    from_day: date | None = None,
) -> tuple[Booking, Visit]:
    """Create (or resume) booking + series (if recurring) + first visit + thread.
    Returns (booking, first visit). Safe to call again with the same request_id / invite_id."""
    booking = await ensure_booking(
        db,
        booking_id=booking_id,
        source=source,
        via=via,
        customer=customer,
        provider=provider,
        category_id=category_id,
        price_pence=price_pence,
        first_price_pence=first_price_pence,
        unit=unit,
        frequency=frequency,
        est_mins=est_mins,
        first_est_mins=first_est_mins,
        address=address,
        answers=answers,
        notes=notes,
        days=days,
        window=window,
        request_id=request_id,
        invite_id=invite_id,
        pricing_version_id=pricing_version_id,
        from_day=from_day,
    )
    return await finish_setup(db, booking, customer, provider)


async def _existing(db: Db, request_id: str | None, invite_id: str | None) -> Booking | None:
    bookings = Bookings(db)
    if request_id:
        return await bookings.by_request(request_id)
    if invite_id:
        return await bookings.find_one({"invite_id": invite_id})
    return None


async def ensure_booking(
    db: Db,
    *,
    booking_id: str | None,
    source: BookingSource,
    via: str,
    customer: Customer,
    provider: Provider,
    category_id: str,
    price_pence: int,
    first_price_pence: int | None,
    unit: Unit,
    frequency: str | None,
    est_mins: int,
    first_est_mins: int | None,
    address: Address,
    answers: dict,
    notes: str,
    days: DaysPref,
    window: TimePref,
    request_id: str | None,
    invite_id: str | None,
    pricing_version_id: str | None,
    from_day: date | None,
) -> Booking:
    """Step 1: the booking document, with the first visit's slot fixed at creation."""
    if existing := await _existing(db, request_id, invite_id):
        return existing
    is_recurring = schedule.recurring(frequency)
    first_mins = first_est_mins or est_mins
    start = await schedule.first_slot(db, provider, days, window, first_mins, from_day)
    booking = Booking(
        id=booking_id or new_id(),
        ref=await next_ref(db, "booking"),
        source=source,
        customer_id=customer.id,
        provider_id=provider.id,
        category_id=category_id,
        request_id=request_id,
        invite_id=invite_id,
        via=via,  # type: ignore[arg-type]
        price_pence=price_pence,
        first_price_pence=first_price_pence,
        unit=unit,
        recurring=is_recurring,
        frequency=frequency if is_recurring else "oneoff",  # type: ignore[arg-type]
        address=address,
        answers=answers,
        notes=notes,
        when=window,
        days=days,
        est_mins=est_mins,
        first_est_mins=first_est_mins,
        pricing_version_id=pricing_version_id,
        first_visit_start=start,
    )
    try:
        await Bookings(db).insert(booking)
    except DuplicateKeyError:
        existing = await _existing(db, request_id, invite_id)
        if existing is None:
            raise
        return existing
    return booking


async def finish_setup(db: Db, booking: Booking, customer: Customer, provider: Provider) -> tuple[Booking, Visit]:
    """Step 2: series, first visit, horizon and thread. Each part checks before it writes."""
    bookings, visits = Bookings(db), Visits(db)
    assert booking.first_visit_start is not None
    start = booking.first_visit_start
    first_day = to_london(start).date()

    series: Series | None = None
    if booking.recurring:
        series = await SeriesRepo(db).find_one({"booking_id": booking.id})
        if series is None:
            freq: Frequency = booking.frequency
            series = Series(
                booking_id=booking.id,
                customer_id=customer.id,
                provider_id=provider.id,
                category_id=booking.category_id,
                frequency=freq,
                days=schedule.series_days(freq, first_day),
                start_time=to_london(start).strftime("%H:%M"),
                anchor_date=first_day,
                price_pence=booking.price_pence,
                est_mins=booking.est_mins,
                window=booking.when,
            )
            try:
                await SeriesRepo(db).insert(series)
            except DuplicateKeyError:
                series = await SeriesRepo(db).find_one({"booking_id": booking.id})
                assert series is not None
        if booking.series_id != series.id:
            booking = await bookings.update(booking.id, {"series_id": series.id}) or booking

    first = await visits.find_one({"booking_id": booking.id, "is_first": True})
    if first is None:
        first = Visit(
            booking_id=booking.id,
            series_id=series.id if series else None,
            customer_id=customer.id,
            provider_id=provider.id,
            performer=Performer(
                kind="provider", provider_id=provider.id, user_id=provider.user_id, name=provider.short
            ),
            category_id=booking.category_id,
            source=booking.source,
            local_date=first_day,
            scheduled_start=start,
            window=booking.when,
            is_first=True,
            price_pence=booking.first_price_pence or booking.price_pence,
            est_mins=booking.first_est_mins or booking.est_mins,
            pricing_version_id=booking.pricing_version_id,
        )
        try:
            await visits.insert(first)
        except DuplicateKeyError:  # same series and day, written by a concurrent resume
            first = await visits.find_one({"booking_id": booking.id, "is_first": True})
            assert first is not None
    if series:
        await schedule.ensure_horizon(db, series, provider, source=booking.source)

    thread = await ensure_booking_thread(db, booking, customer, provider)
    booking = await bookings.update(booking.id, {"thread_id": thread.id, "setup_complete": True}) or booking
    return booking, first


async def ensure_booking_thread(db: Db, booking: Booking, customer: Customer, provider: Provider) -> MessageThread:
    threads = MessageThreads(db)
    existing = await threads.find_one({"kind": "booking", "booking_id": booking.id})
    if existing:
        return existing
    users = Users(db)
    cu, pu = await users.get(customer.user_id), await users.get(provider.user_id)
    thread = MessageThread(
        kind="booking",
        booking_id=booking.id,
        participants=[
            Participant(user_id=customer.user_id, role="customer", name=cu.name if cu else customer.name),
            Participant(user_id=provider.user_id, role="provider", name=pu.name if pu else provider.name),
        ],
    )
    try:
        await threads.insert(thread)
    except DuplicateKeyError:
        found = await threads.find_one({"kind": "booking", "booking_id": booking.id})
        assert found is not None
        return found
    return thread
