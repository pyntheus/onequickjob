"""Small, shared bits of copy for message bodies (dates, times, prices, frequencies)."""

from datetime import date, datetime

from app.core.money import format_pounds
from app.core.rounding import D, round_half_up, round_half_up_to
from app.core.timeutil import to_london
from app.models.categories import Category

FREQUENCY_WORDS = {
    "weekly": "every week",
    "fortnightly": "every 2 weeks",
    "threeweekly": "every 3 weeks",
    "fourweekly": "every 4 weeks",
    "eightweekly": "every 8 weeks",
    "monthly": "every month",
    "threemonthly": "every 3 months",
    "weekdays": "every weekday",
    "someweekdays": "a few days a week",
    "oneoff": "one-off",
}


def day_text(d: date | datetime) -> str:
    """Tuesday 13 October."""
    if isinstance(d, datetime):
        d = to_london(d).date()
    return f"{d:%A} {d.day} {d:%B}"


def time_text(dt: datetime) -> str:
    """10:30 (24-hour, as the prototype's round shows)."""
    local = to_london(dt)
    return f"{local.hour}:{local.minute:02d}"


def when_text(dt: datetime, recurring: bool) -> str:
    prefix = "First visit " if recurring else ""
    return f"{prefix}{day_text(dt)} at {time_text(dt)}"


def money(pence: int) -> str:
    return format_pounds(pence)


def lower_name(cat: Category) -> str:
    return cat.name[0].lower() + cat.name[1:]


def first_name(name: str) -> str:
    return (name or "").strip().split(" ")[0]


def duration_text(mins: int) -> str:
    """The prototype's fmtDuration: "38 minutes", "1½ hours", "8½ hours"."""
    if mins < 90:
        return f"{round_half_up(mins)} minutes"
    h = round_half_up_to(D(mins) / 60, "0.5")
    return f"{int(h)}{'½' if h % 1 else ''} hours"
