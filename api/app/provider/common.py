"""Small shared pieces for the provider app: names, distances, the facts a provider sees about
a job, files they attach, and quiet hours for alerts."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi import status

from app.adapters.area.describe import fact_text
from app.core.db import Db, DbSession
from app.core.errors import fail
from app.core.geo import miles_between
from app.core.rounding import D, round_half_up_to
from app.core.timeutil import LONDON, to_london
from app.models.categories import Category, IntakeField
from app.models.common import Address
from app.models.job_requests import When
from app.models.providers import AlertSettings
from app.models.quotes import Measure
from app.models.system import StoredFile
from app.repos.categories import Categories
from app.repos.files import Files
from app.services import wording

ONE_MILE = Decimal(1)


def short_name(name: str) -> str:
    """Sarah Whitfield -> Sarah W. (how customers appear to providers, and providers to customers)."""
    parts = (name or "").split()
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


def one_dp(x: float | Decimal) -> float:
    """A distance to one decimal place, halves up (never round(): decisions.md rule 17)."""
    return float(round_half_up_to(D(x), "0.1"))


def miles(a: Address, lat: float, lng: float) -> float:
    return miles_between(a.lat, a.lng, lat, lng)


def frequency_label(frequency: str | None) -> str:
    """Every 2 weeks, One-off (the job card's second badge)."""
    words = wording.FREQUENCY_WORDS.get(frequency or "oneoff", "one-off")
    return words[0].upper() + words[1:]


DAYS_WORD = {"any": "Any day", "weekdays": "Weekday", "weekends": "Weekend"}
TIME_WORD = {"morning": "mornings", "afternoon": "afternoons", "either": "any time"}


def when_text(when: When) -> str:
    """Weekday mornings, Weekend afternoons, Any morning, Weekdays, any time, Any day."""
    if when.days == "any":
        return {"morning": "Any morning", "afternoon": "Any afternoon", "either": "Any day"}[when.time]
    if when.time == "either":
        return f"{DAYS_WORD[when.days]}s, any time"
    return f"{DAYS_WORD[when.days]} {TIME_WORD[when.time]}"


# Short labels for the facts grid (the intake asks questions; the provider reads facts).
FACT_LABELS: dict[str, str] = {
    "grassState": "Grass",
    "waste": "Waste",
    "access": "Access",
    "length": "Length",
    "height": "Height",
    "sides": "Sides",
    "photos": "Photos",
    "volume": "Amount",
    "surface": "Surface",
    "area": "Size",
    "resand": "Re-sanding",
    "house": "House",
    "conservatory": "Conservatory",
    "downpipes": "Downpipes",
    "size": "Size",
    "bedrooms": "Bedrooms",
    "bathrooms": "Bathrooms",
    "extras": "Extras",
    "supplies": "Products",
    "type": "Clean",
    "furnished": "Furnished",
    "ovenType": "Oven",
    "rooms": "Rooms",
    "parts": "Painting",
    "condition": "Walls",
    "paint": "Paint",
    "items": "Items",
    "anchor": "Fix to wall",
    "packaging": "Packaging",
    "wall": "Walls",
    "description": "The job",
    "topics": "Help with",
    "forWhom": "For",
    "dogs": "Dogs",
    "keys": "Getting in",
}
FACT_LABELS_BY_CATEGORY: dict[tuple[str, str], str] = {
    ("mowing", "waste"): "Clippings",
    ("hedges", "length"): "Hedge",
    ("hedges", "waste"): "Cuttings",
    ("windows", "size"): "House",
    ("decorating", "size"): "Room size",
    ("repairs", "size"): "Time needed",
    ("techhelp", "length"): "Session",
    ("dogwalking", "length"): "Walk",
    ("mounting", "items"): "To put up",
}
NOT_FACTS = {"frequency"}  # already on the card


def _option_label(field: IntakeField, value: Any) -> str:
    for o in field.options or []:
        if o.value == value:
            return o.label
    return str(value)


def answer_text(field: IntakeField, value: Any) -> str | None:
    """How one answer reads to a provider, or None if there's nothing to say."""
    match field.type:
        case "choice" | "chips":
            return _option_label(field, value) if value not in (None, "") else None
        case "multi":
            labels = [_option_label(field, v) for v in value or []]
            return ", ".join(labels) if labels else "None"
        case "number":
            if value is None:
                return None
            unit = field.unit1 if value == 1 and field.unit1 else field.unit
            if unit in ("m", "m²"):
                return f"About {value} {unit}"
            return f"{value} {unit}" if unit else str(value)
        case "counts":
            names = {i.key: i.label for i in field.items or []}
            parts = [f"{n} {names.get(k, k).lower()}" for k, n in (value or {}).items() if n]
            return ", ".join(parts) if parts else None
        case "text":
            text = str(value or "").strip()
            return text or None
        case "photos":
            n = len(value or [])
            return f"{n} {'photo' if n == 1 else 'photos'}" if n else None
    return None  # pragma: no cover - guarded by the IntakeField type


def facts_for(
    cat: Category, answers: dict[str, Any], measure: Measure | None, when: When | None, mins: int
) -> list[tuple[str, str]]:
    """The facts grid: lawn size first, then the customer's answers, when, and the estimate."""
    out: list[tuple[str, str]] = []
    if measure is not None:
        out.append(("Lawn", fact_text(measure)))
    for field in cat.intake:
        if field.key in NOT_FACTS:
            continue
        text = answer_text(field, answers.get(field.key, field.default))
        if text:
            label = FACT_LABELS_BY_CATEGORY.get((cat.id, field.key)) or FACT_LABELS.get(field.key) or field.label
            out.append((label, text))
    if when is not None:
        out.append(("When", when_text(when)))
    out.append(("Estimate", f"About {wording.duration_text(mins)}"))
    return out


def summary_for(cat: Category, answers: dict[str, Any]) -> str:
    """One line for the round: "Recently cut, take them away, side gate"."""
    bits: list[str] = []
    for field in cat.intake:
        if field.key in NOT_FACTS or field.type in ("text", "photos"):
            continue
        text = answer_text(field, answers.get(field.key, field.default))
        if text:
            bits.append(text if not bits else text[0].lower() + text[1:])
        if len(bits) == 3:
            break
    return ", ".join(bits)


async def categories(db: Db, *, session: DbSession | None = None) -> dict[str, Category]:
    return {c.id: c for c in await Categories(db).all(session=session)}


async def file_urls(db: Db, ids: list[str]) -> list[str]:
    if not ids:
        return []
    found = {f.id: f.url for f in await Files(db).find({"_id": {"$in": ids}})}
    return [found[i] for i in ids if i in found]


async def own_file(db: Db, file_id: str, user_id: str, kinds: tuple[str, ...]) -> StoredFile:
    """A file this user uploaded, of one of these kinds. Anyone else's file is a 404, so ids
    can't be borrowed from other people's uploads."""
    f = await Files(db).get(file_id)
    if f is None or f.owner_user_id != user_id:
        fail(status.HTTP_404_NOT_FOUND, "file_not_found", "We couldn't find that upload. Please try again.")
    if f.kind not in kinds:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "wrong_file_kind", "That upload is for something else.")
    return f


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def quiet_until(alerts: AlertSettings, now: datetime) -> datetime | None:
    """When an alert would be sent if it's quiet hours now (held with not_before), else None."""
    if not alerts.quiet_hours:
        return None
    local = to_london(now)
    start, end = _hhmm(alerts.quiet_from), _hhmm(alerts.quiet_to)
    t = local.time()
    quiet = (start <= t or t < end) if start > end else (start <= t < end)
    if not quiet:
        return None
    day: date = local.date() if t < end else local.date() + timedelta(days=1)
    return datetime.combine(day, end, tzinfo=LONDON)
