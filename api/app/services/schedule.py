"""When visits happen. Rulings (decisions.md), since the prototype doesn't define them:

- Windows (London time): morning 09:00-12:00, afternoon 13:00-17:00, either 09:00-17:00.
  Customers see "morning, 8am to 12pm" etc.; slots start at 9 so a provider can travel.
- First visit: the earliest day from tomorrow that the provider works, suits the
  customer (any / weekdays / weekends) and isn't in the provider's time off, at the first
  free half-hour in the window: after the provider's previous visit that day ends plus a
  30-minute travel buffer ("10:30, straight after Widmer End" in the prototype).
- Recurring visits keep the first visit's weekday and time; materialised 6 weeks ahead
  (at least the next two), idempotently (unique series_id + local_date).
- Frequencies: weekly 7 days, fortnightly 14, threeweekly 21, fourweekly 28,
  eightweekly 56, monthly and threemonthly by calendar month, weekdays Mon-Fri,
  someweekdays on the series' chosen days (default Mon, Wed, Fri).
- Winter pause (outside jobs): no visits from 1 November to the end of February.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pymongo.errors import DuplicateKeyError

from app.core.db import Db
from app.core.timeutil import london_datetime, london_today, to_london, weekday_key
from app.models.bookings import Frequency, Series
from app.models.common import DaysPref, TimePref, Weekday
from app.models.providers import Provider
from app.models.visits import Performer, Visit
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
SEARCH_DAYS = 28
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


async def _away(db: Db, provider_id: str, day: date) -> bool:
    iso = day.isoformat()
    return (
        await TimeOffRepo(db).count(
            {
                "provider_id": provider_id,
                "status": {"$in": ["planned", "active"]},
                "from_date": {"$lte": iso},
                "to_date": {"$gte": iso},
            }
        )
        > 0
    )


async def free_slot_on(db: Db, provider: Provider, day: date, window: TimePref, mins: int) -> datetime | None:
    """First start time on day in window that fits mins, after the provider's other visits."""
    start_t, end_t = WINDOWS[window]
    window_end = london_datetime(day, end_t)
    candidate = to_london(london_datetime(day, start_t))
    for v in await Visits(db).for_provider_day(provider.id, day):
        v_start = v.scheduled_start
        v_end = v_start + timedelta(minutes=v.est_mins)
        if candidate < v_end + TRAVEL_BUFFER and candidate + timedelta(minutes=mins) + TRAVEL_BUFFER > v_start:
            candidate = _round_up_half_hour(v_end + TRAVEL_BUFFER)
    if candidate + timedelta(minutes=mins) > window_end:
        return None
    return candidate.astimezone(UTC)


async def first_slot(
    db: Db, provider: Provider, days: DaysPref, window: TimePref, mins: int, from_day: date | None = None
) -> datetime:
    day = from_day or (london_today() + timedelta(days=1))
    for _ in range(SEARCH_DAYS):
        if weekday_key(day) in provider.working_days and suits(day, days) and not await _away(db, provider.id, day):
            slot = await free_slot_on(db, provider, day, window, mins)
            if slot is not None:
                return slot
        day += timedelta(days=1)
    # Nothing free in four weeks: first suitable day at the start of the window; the
    # provider can rearrange by message.
    fallback = from_day or (london_today() + timedelta(days=1))
    return london_datetime(fallback, WINDOWS[window][0])


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError(d)  # pragma: no cover


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
            d = _add_months(series.anchor_date, MONTHS[f] * k)
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
    source: Literal["platform", "own_customer"] = "platform",
) -> list[Visit]:
    """Create the series' visits up to the horizon. Safe to call repeatedly."""
    if series.status != "active":
        return []
    today = today or london_today()
    visits = Visits(db)
    last = await visits.find_one({"series_id": series.id}, sort=[("local_date", -1)])
    after = max(last.local_date if last else series.anchor_date - timedelta(days=1), today)
    until = today + timedelta(days=HORIZON_DAYS)
    upcoming = await visits.count({"series_id": series.id, "local_date": {"$gt": today.isoformat()}})
    dates = occurrences(series, after, until)
    if upcoming + len(dates) < MIN_UPCOMING:
        dates = occurrences(series, after, until + timedelta(days=400))[: MIN_UPCOMING - upcoming] or dates
    hh, mm = (int(x) for x in series.start_time.split(":"))
    created: list[Visit] = []
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
        try:
            await visits.insert(v)
            created.append(v)
        except DuplicateKeyError:
            continue
    if dates:
        await SeriesRepo(db).update(series.id, {"horizon_until": max(dates).isoformat()})
    return created
