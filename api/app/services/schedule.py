"""When visits happen. Rulings (decisions.md), since the prototype doesn't define them:

- Windows (London time): morning 09:00-12:00, afternoon 13:00-17:00, either 09:00-17:00.
  Customers see "morning, 8am to 12pm" etc.; slots start at 9 so a provider can travel.
- First visit: the earliest day from tomorrow that the provider works, suits the
  customer (any / weekdays / weekends) and isn't in the provider's time off, at the first
  free half-hour in the window: after the provider's previous visit that day ends plus a
  30-minute travel buffer ("10:30, straight after Widmer End" in the prototype). A visit
  ends by its window's end, except one longer than its window (a first regular clean is
  four hours; the morning is three), which starts at the window's start on a day with room
  for all of it and runs over (decisions.md A14). If nothing fits within six months, the
  first working day with room, whatever the customer's days: the provider rearranges by
  message. Never a day the provider doesn't work or is away; with no working day that has room
  in six months, nothing is booked (409 no_free_day).
- Recurring visits keep the first visit's weekday and time; materialised 6 weeks ahead
  (at least the next two), idempotently (unique series_id + local_date).
- Frequencies: weekly 7 days, fortnightly 14, threeweekly 21, fourweekly 28,
  eightweekly 56, monthly and threemonthly by calendar month, weekdays Mon-Fri,
  someweekdays on the series' chosen days (default Mon, Wed, Fri).
- Winter pause (outside jobs): no visits from 1 November to the end of February.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from app.core.db import Db, DbSession, transaction
from app.core.errors import Conflict
from app.core.timeutil import add_months, london_datetime, london_today, to_london, weekday_key
from app.models.bookings import Frequency, Series
from app.models.common import DaysPref, TimePref, Weekday
from app.models.providers import Provider
from app.models.visits import Performer, Visit
from app.repos.bookings import Bookings
from app.repos.providers import Providers
from app.repos.series import SeriesRepo
from app.repos.time_off import TimeOffRepo
from app.repos.visits import Visits

WINDOWS: dict[str, tuple[time, time]] = {
    "morning": (time(9, 0), time(12, 0)),
    "afternoon": (time(13, 0), time(17, 0)),
    "either": (time(9, 0), time(17, 0)),
}
WINDOW_COPY = {
    "morning": "morning, 8am to 12pm",
    "afternoon": "afternoon, 12pm to 5pm",
    "either": "time confirmed the day before",
}
TRAVEL_BUFFER = timedelta(minutes=30)
SEARCH_DAYS = 182  # how far ahead a first visit is looked for
HORIZON_DAYS = 42
MIN_UPCOMING = 2
INTERVAL_DAYS: dict[str, int] = {"weekly": 7, "fortnightly": 14, "threeweekly": 21, "fourweekly": 28, "eightweekly": 56}
MONTHS: dict[str, int] = {"monthly": 1, "threemonthly": 3}
DEFAULT_SOME_DAYS: list[Weekday] = ["mon", "wed", "fri"]
WINTER_MONTHS = {11, 12, 1, 2}


def recurring(frequency: str | None) -> bool:
    return bool(frequency) and frequency != "oneoff"


def suits(day: date, days: DaysPref) -> bool:
    if days == "weekdays":
        return day.weekday() < 5
    if days == "weekends":
        return day.weekday() >= 5
    return True


def _round_up_half_hour(dt: datetime) -> datetime:
    local = to_london(dt)
    if local.second or local.microsecond:
        local = local.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return local + timedelta(minutes=(-local.minute) % 30)


def slot_on(day: date, window: TimePref, mins: int, busy: list[Visit]) -> datetime | None:
    """First start time on day in window that fits mins around the provider's other visits that
    day (busy, by start time), with the travel buffer either side. A visit ends by the window's
    end; one longer than the window may only start at the window's start, and runs over."""
    start_t, end_t = WINDOWS[window]
    window_start = to_london(london_datetime(day, start_t))
    length = timedelta(minutes=mins)
    latest = max(window_start, to_london(london_datetime(day, end_t)) - length)
    candidate = window_start
    for v in busy:
        v_start = v.scheduled_start
        v_end = v_start + timedelta(minutes=v.est_mins)
        if candidate < v_end + TRAVEL_BUFFER and candidate + length + TRAVEL_BUFFER > v_start:
            candidate = _round_up_half_hour(v_end + TRAVEL_BUFFER)
    if candidate > latest:
        return None
    return candidate.astimezone(UTC)


async def first_slot(
    db: Db,
    provider: Provider,
    days: DaysPref,
    window: TimePref,
    mins: int,
    from_day: date | None = None,
    *,
    session: DbSession | None = None,
) -> datetime:
    """The first visit's start: the earliest day from from_day (tomorrow by default) that the
    provider works, isn't away, suits the customer and has room in the window (slot_on). If no
    such day comes within SEARCH_DAYS, the provider's first working day with room, whatever the
    customer's days (they can rearrange by message); never a day they don't work or are away. If
    there's none at all, it raises Conflict no_free_day, which undoes the booking (409)."""
    first = from_day or (london_today() + timedelta(days=1))
    last = first + timedelta(days=SEARCH_DAYS - 1)
    span = {"$gte": first.isoformat(), "$lte": last.isoformat()}
    away = [
        (t.from_date, t.to_date)
        for t in await TimeOffRepo(db).find(
            {
                "provider_id": provider.id,
                "status": {"$in": ["planned", "active"]},
                "from_date": {"$lte": last.isoformat()},
                "to_date": {"$gte": first.isoformat()},
            },
            session=session,
        )
    ]
    busy: dict[date, list[Visit]] = {}
    for v in await Visits(db).find(
        {"provider_id": provider.id, "local_date": span, "status": {"$nin": ["cancelled", "skipped"]}},
        sort=[("scheduled_start", 1)],
        session=session,
    ):
        busy.setdefault(v.local_date, []).append(v)
    working = [
        d
        for d in (first + timedelta(days=k) for k in range(SEARCH_DAYS))
        if weekday_key(d) in provider.working_days and not any(a <= d <= b for a, b in away)
    ]
    for candidates in ([d for d in working if suits(d, days)], working):
        for d in candidates:
            if (slot := slot_on(d, window, mins, busy.get(d, []))) is not None:
                return slot
    # No working day with room in six months (none at all, away throughout, or every one full):
    # nothing can be booked, so the booking's transaction is undone (409).
    raise Conflict(
        "no_free_day", f"{provider.short} has no free day for this in the next six months, so it can't be booked."
    )


def occurrences(series: Series, after: date, until: date) -> list[date]:
    """Visit dates strictly after `after` and up to `until`, honouring pauses."""
    out: list[date] = []
    f: Frequency = series.frequency
    if f in INTERVAL_DAYS:
        step = INTERVAL_DAYS[f]
        k = max(0, (after - series.anchor_date).days // step)
        d = series.anchor_date + timedelta(days=step * k)
        while d <= until:
            if d > after:
                out.append(d)
            d += timedelta(days=step)
    elif f in MONTHS:
        k, d = 0, series.anchor_date
        while d <= until:
            if d > after:
                out.append(d)
            k += 1
            d = add_months(series.anchor_date, MONTHS[f] * k)
    elif f in ("weekdays", "someweekdays"):
        days = set(series.days or (["mon", "tue", "wed", "thu", "fri"] if f == "weekdays" else DEFAULT_SOME_DAYS))
        d = max(after + timedelta(days=1), series.anchor_date)
        while d <= until:
            if weekday_key(d) in days:
                out.append(d)
            d += timedelta(days=1)
    return [d for d in out if not paused_on(series, d)]


def paused_on(series: Series, d: date) -> bool:
    p = series.pause
    if p.winter and d.month in WINTER_MONTHS:
        return True
    return bool(p.away_from and p.away_to and p.away_from <= d <= p.away_to)


def series_days(frequency: str, first_day: date) -> list[Weekday]:
    if frequency == "weekdays":
        return ["mon", "tue", "wed", "thu", "fri"]
    if frequency == "someweekdays":
        return list(DEFAULT_SOME_DAYS)
    return [weekday_key(first_day)]  # type: ignore[list-item]


async def ensure_horizon(
    db: Db,
    series: Series,
    provider: Provider,
    *,
    today: date | None = None,
    from_day: date | None = None,
    source: Literal["platform", "own_customer"] = "platform",
    session: DbSession | None = None,
) -> list[Visit]:
    """Create the series' visits up to the horizon. Safe to call repeatedly and concurrently
    (one visit per plan and day is a unique index; existing days are left as they are).

    Normally it adds the plan's dates after its latest visit. With from_day (after a change of
    frequency) it makes every plan date after from_day instead: a date's existing visit stays as
    it is, except one an earlier change of frequency cancelled, which comes back at the plan's
    price. Returns the visits it added or brought back. When it adds any, it writes the plan
    (horizon_until), so inside a transaction a concurrent change to the plan conflicts with it."""
    if series.status != "active":
        return []
    today = today or london_today()
    visits = Visits(db)
    until = today + timedelta(days=HORIZON_DAYS)
    if from_day is None:
        last = await visits.find_one({"series_id": series.id}, sort=[("local_date", -1)], session=session)
        after = max(last.local_date if last else series.anchor_date - timedelta(days=1), today)
        upcoming = await visits.count(
            {"series_id": series.id, "local_date": {"$gt": today.isoformat()}}, session=session
        )
    else:
        after, upcoming = from_day, 0
    dates = occurrences(series, after, until)
    if upcoming + len(dates) < MIN_UPCOMING:
        dates = occurrences(series, after, until + timedelta(days=400))[: MIN_UPCOMING - upcoming] or dates
    hh, mm = (int(x) for x in series.start_time.split(":"))
    made: list[Visit] = []
    for d in dates:
        v = Visit(
            booking_id=series.booking_id,
            series_id=series.id,
            customer_id=series.customer_id,
            provider_id=series.provider_id,
            performer=Performer(
                kind="provider", provider_id=provider.id, user_id=provider.user_id, name=provider.short
            ),
            category_id=series.category_id,
            source=source,
            local_date=d,
            scheduled_start=london_datetime(d, time(hh, mm)),
            window=series.window,
            is_first=False,
            price_pence=series.price_pence,
            est_mins=series.est_mins,
        )
        stored = await visits.insert_once(v, {"series_id": series.id, "local_date": d.isoformat()}, session=session)
        if stored.id == v.id:
            made.append(v)
        elif from_day is not None and stored.status == "cancelled" and stored.skipped_reason == "plan_change":
            back = await visits.update(
                stored.id,
                {"status": "scheduled", "skipped_reason": None, "price_pence": series.price_pence},
                extra_filter={"status": "cancelled"},
                session=session,
            )
            if back is not None:
                made.append(back)
    if dates:
        horizon = max(dates) if series.horizon_until is None else max(max(dates), series.horizon_until)
        await SeriesRepo(db).update(series.id, {"horizon_until": horizon.isoformat()}, session=session)
    return made


async def top_up(db: Db, series_id: str, *, today: date | None = None) -> list[Visit]:
    """ensure_horizon for one plan, in a transaction of its own that reads the plan (and its
    provider and booking) as they are now, so it never adds a visit at a frequency or price that
    a committed change has replaced. ensure_horizon writes the plan whenever it adds a visit, so
    a change of frequency, a pause or a cancellation committing meanwhile conflicts with it and
    the driver re-runs it on the plan as changed (decisions.md A13)."""

    async def fill(session: DbSession) -> list[Visit]:
        series = await SeriesRepo(db).get(series_id, session=session)
        if series is None or series.status != "active":
            return []
        provider = await Providers(db).get(series.provider_id, session=session)
        booking = await Bookings(db).get(series.booking_id, session=session)
        if provider is None or booking is None:
            return []
        return await ensure_horizon(db, series, provider, today=today, source=booking.source, session=session)

    return await transaction(db, fill)
