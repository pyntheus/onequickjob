"""Times are stored in UTC and shown in Europe/London."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_london(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(LONDON)


def london_today(now: datetime | None = None) -> date:
    return to_london(now or utcnow()).date()


def london_datetime(day: date, at: time) -> datetime:
    """A London wall-clock time on a day, as an aware UTC datetime."""
    return datetime.combine(day, at, tzinfo=LONDON).astimezone(UTC)


def week_start(day: date) -> date:
    """Monday of the week containing day (earnings limits run Monday to Sunday)."""
    return day - timedelta(days=day.weekday())


def month_start(day: date) -> date:
    return day.replace(day=1)


def tax_year(day: date) -> str:
    """UK tax year label for a London date: 6 April 2026 to 5 April 2027 is "2026-27"."""
    start_year = day.year if (day.month, day.day) >= (4, 6) else day.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def tax_year_bounds(label: str) -> tuple[date, date]:
    """First and last London dates of a tax year label."""
    start_year = int(label[:4])
    return date(start_year, 4, 6), date(start_year + 1, 4, 5)


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def weekday_key(day: date) -> str:
    return WEEKDAYS[day.weekday()]
