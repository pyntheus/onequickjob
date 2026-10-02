"""Turning an agreement into a booking, its plan (series), first visit and message thread.

Used by the marketplace (a request booked at the guide price or an accepted counter)
and by own-customer invites (L1 accepts, L2 created the invite). Booking creation is
idempotent per request and per invite (unique indexes), so a retry after a crash
between claiming a request and writing the booking can't double-book.
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
    """Create booking + series (if recurring) + first visit + thread. Returns (booking, first visit)."""
    bookings = Bookings(db)
    if request_id and (existing := await bookings.by_request(request_id)):
        first = await Visits(db).find_one({"booking_id": existing.id}, sort=[("scheduled_start", 1)])
        assert first is not None
        return existing, first

    is_recurring = schedule.recurring(frequency)
    freq: Frequency = frequency if is_recurring else "oneoff"  # type: ignore[assignment]
    first_mins = first_est_mins or est_mins
    start = await schedule.first_slot(db, provider, days, window, first_mins, from_day)
    first_day = to_london(start).date()

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
        frequency=freq,
        address=address,
        answers=answers,
        notes=notes,
        when=window,
    )
    try:
        await bookings.insert(booking)
    except DuplicateKeyError:
        if request_id and (existing := await bookings.by_request(request_id)):
            first = await Visits(db).find_one({"booking_id": existing.id}, sort=[("scheduled_start", 1)])
            assert first is not None
            return existing, first
        raise

    series: Series | None = None
    if is_recurring:
        series = Series(
            booking_id=booking.id,
            customer_id=customer.id,
            provider_id=provider.id,
            category_id=category_id,
            frequency=freq,
            days=schedule.series_days(freq, first_day),
            start_time=to_london(start).strftime("%H:%M"),
            anchor_date=first_day,
            price_pence=price_pence,
            est_mins=est_mins,
            window=window,
        )
        await SeriesRepo(db).insert(series)
        booking = await bookings.update(booking.id, {"series_id": series.id}) or booking

    first_visit = Visit(
        booking_id=booking.id,
        series_id=series.id if series else None,
        customer_id=customer.id,
        provider_id=provider.id,
        performer=Performer(kind="provider", provider_id=provider.id, user_id=provider.user_id, name=provider.short),
        category_id=category_id,
        source=source,
        local_date=first_day,
        scheduled_start=start,
        window=window,
        is_first=True,
        price_pence=first_price_pence or price_pence,
        est_mins=first_mins,
        pricing_version_id=pricing_version_id,
    )
    await Visits(db).insert(first_visit)
    if series:
        await schedule.ensure_horizon(db, series, provider, source=source)

    thread = await ensure_booking_thread(db, booking, customer, provider)
    booking = await bookings.update(booking.id, {"thread_id": thread.id}) or booking
    return booking, first_visit


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
