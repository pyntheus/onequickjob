"""Turning an agreement into a booking, its plan (series), first visit and message thread.

Used by the marketplace (a request booked at the guide price or an accepted counter) and
by own-customer invites (L1 accepts, L2 created the invite). It always runs inside the
caller's transaction, together with whatever made the agreement (the request's claim, the
invite's acceptance) and the messages that announce it: all of it commits, or none of it.
"""

from datetime import date

from app.core.db import Db, DbSession
from app.core.ids import new_id, next_ref
from app.core.timeutil import to_london
from app.models.bookings import Booking, Series
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
    session: DbSession,
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
    """Booking + series (if recurring) + first visit + visits up to the horizon + thread, in
    the caller's transaction (session is required). Returns (booking, first visit).

    One booking per request and per invite, one first visit per booking and one thread per
    booking are unique indexes: if a second booking ever got this far, its commit would fail."""
    is_recurring = schedule.recurring(frequency)
    start = await schedule.first_slot(db, provider, days, window, first_est_mins or est_mins, from_day, session=session)
    first_day = to_london(start).date()
    booking = Booking(
        id=booking_id or new_id(),
        ref=await next_ref(db, "booking", session=session),
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
    )

    series: Series | None = None
    if is_recurring:
        series = Series(
            booking_id=booking.id,
            customer_id=customer.id,
            provider_id=provider.id,
            category_id=category_id,
            frequency=booking.frequency,
            days=schedule.series_days(booking.frequency, first_day),
            start_time=to_london(start).strftime("%H:%M"),
            anchor_date=first_day,
            price_pence=price_pence,
            est_mins=est_mins,
            window=window,
        )
        await SeriesRepo(db).insert(series, session=session)
        booking.series_id = series.id

    first = Visit(
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
        est_mins=first_est_mins or est_mins,
        pricing_version_id=pricing_version_id,
    )
    await Visits(db).insert(first, session=session)
    if series:
        await schedule.ensure_horizon(db, series, provider, source=source, session=session)

    thread = await _thread(db, booking, customer, provider, session)
    booking.thread_id = thread.id
    await Bookings(db).insert(booking, session=session)
    return booking, first


async def _thread(
    db: Db, booking: Booking, customer: Customer, provider: Provider, session: DbSession
) -> MessageThread:
    users = Users(db)
    cu = await users.get(customer.user_id, session=session)
    pu = await users.get(provider.user_id, session=session)
    thread = MessageThread(
        kind="booking",
        booking_id=booking.id,
        participants=[
            Participant(user_id=customer.user_id, role="customer", name=cu.name if cu else customer.name),
            Participant(user_id=provider.user_id, role="provider", name=pu.name if pu else provider.name),
        ],
    )
    return await MessageThreads(db).insert(thread, session=session)
