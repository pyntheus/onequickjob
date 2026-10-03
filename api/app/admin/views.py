"""Small pieces of admin copy and shape shared by the admin endpoints."""

from datetime import date, datetime, timedelta

from app.core.timeutil import london_today, to_london, utcnow
from app.models.categories import Category
from app.models.job_requests import JobRequest
from app.models.providers import Provider, ProviderDocument
from app.models.quotes import Measure
from app.services import wording

# The prototype's districts (AdminOverview), for tiles whose addresses don't name the area.
DISTRICT_NAMES = {
    "HP15": "Hazlemere",
    "HP10": "Tylers Green, Loudwater",
    "HP13": "Downley",
    "SL7": "Marlow",
    "HP12": "Booker, Sands",
    "HP11": "Town centre",
    "HP9": "Beaconsfield",
    "HP27": "Princes Risborough",
    "HP14": "Stokenchurch",
    "HP16": "Great Missenden",
    "HP7": "Amersham",
}
EXPIRY_WARNING_DAYS = 30


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def age_text(since: datetime, now: datetime | None = None) -> str:
    """ "5 hours", "26 hours", "3 days": the prototype's waiting times."""
    mins = max(int(((now or utcnow()) - since).total_seconds() // 60), 0)
    if mins < 60:
        return plural(mins, "minute")
    if mins < 48 * 60:
        return plural(mins // 60, "hour")
    return plural(mins // (24 * 60), "day")


def ago_text(when: datetime, now: datetime | None = None) -> str:
    """ "today", "yesterday", "2 days ago"."""
    today = to_london(now).date() if now else london_today()
    days = (today - to_london(when).date()).days
    if days <= 0:
        return "today"
    return "yesterday" if days == 1 else f"{days} days ago"


def long_date(d: date) -> str:
    """19 November 2026."""
    return f"{d.day} {d:%B %Y}"


def short_name(name: str) -> str:
    """Helen Mitchell -> Helen M."""
    parts = (name or "").split()
    return parts[0] if len(parts) < 2 else f"{parts[0]} {parts[-1][0]}."


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def brief_for(cat: Category, answers: dict, measure: Measure | None) -> str:
    """A one-line description of a job from its answers, rendered from the intake schema."""
    parts: list[str] = []
    if measure is not None:
        parts.append(f"About {measure.area_m2} m² lawn")
    for f in cat.intake:
        value = answers.get(f.key)
        if value in (None, "", [], {}) or f.type in ("photos", "text"):
            continue
        labels = {o.value: o.label for o in f.options or []}
        if f.type in ("choice", "chips"):
            label = labels.get(str(value), str(value))
            if not label.lower().startswith(("yes", "no")):  # "No thanks" means nothing without its question
                parts.append(label)
        elif f.type == "multi":
            parts.append(", ".join(labels.get(v, v) for v in value))
        elif f.type == "number":
            unit = (f.unit1 if value == 1 else f.unit) or ""
            parts.append(f"{value} {unit}".strip())
        elif f.type == "counts" and isinstance(value, dict):
            names = {i.key: i.label for i in f.items or []}
            counted = [f"{n} {lower_first(names.get(k, k))}" for k, n in value.items() if n]
            if counted:
                parts.append(", ".join(counted))
        if len(parts) >= 3:
            break
    if not parts:
        return cat.name
    return parts[0] + "".join(", " + lower_first(p) for p in parts[1:])


def request_where(req: JobRequest) -> str:
    return f"{req.address.area}, {req.address.district}"


def doc_state(doc: ProviderDocument | None, today: date | None = None) -> str:
    """ok, warn (runs out within 30 days), expired or missing (not verified)."""
    today = today or london_today()
    if doc is None or doc.status != "verified":
        return "missing"
    if doc.expires_on is None:
        return "ok"
    if doc.expires_on < today:
        return "expired"
    return "warn" if doc.expires_on < today + timedelta(days=EXPIRY_WARNING_DAYS) else "ok"


def doc_of(provider: Provider, doc_type: str) -> ProviderDocument | None:
    return next((d for d in provider.documents if d.type == doc_type), None)


def money(pence: int) -> str:
    return wording.money(pence)
