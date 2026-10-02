"""Who may take a job, who gets alerted, and how far through their earnings limit they are.

Two levels (decisions.md):
- can_take (hard rules, checked on every accept and counter): active or payouts-paused
  status, the category in their skills, identity checked, and every document the
  category requires verified and in date. Distance is NOT a hard rule: admins dispatch
  further-away jobs by hand through the WhatsApp group.
- alert_targets (who gets the broadcast, L1): can_take, plus within their travel radius
  of the job, a working day that suits the customer, alerts switched on, and not yet at
  their earnings limit. Jobs that would take them over the limit still alert while they
  have headroom; the provider's job list marks them (L2).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core import money
from app.core.db import Db
from app.core.geo import miles_between
from app.core.timeutil import london_today, month_start, week_start
from app.models.categories import Category
from app.models.common import DaysPref, DocType
from app.models.job_requests import JobRequest
from app.models.providers import Provider
from app.repos.ledger_entries import LedgerEntries
from app.repos.providers import Providers

WEEKDAYS = {"mon", "tue", "wed", "thu", "fri"}
WEEKEND = {"sat", "sun"}


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    missing_documents: list[DocType] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def can_take(provider: Provider, category: Category, today: date | None = None) -> Eligibility:
    today = today or london_today()
    reasons: list[str] = []
    if provider.status not in ("active", "payouts_paused"):
        reasons.append("Your account isn't active for new jobs.")
    if category.status != "live":
        reasons.append(f"{category.name} isn't bookable.")
    if category.id not in provider.skills:
        reasons.append(f"{category.name} isn't one of the jobs you do.")
    held = {
        d.type for d in provider.documents if d.status == "verified" and (d.expires_on is None or d.expires_on >= today)
    }
    missing = [t for t in ["identity", *category.requires] if t not in held]
    if missing:
        reasons.append("Some documents this job needs aren't checked or have run out.")
    return Eligibility(ok=not reasons, missing_documents=missing, reasons=reasons)


def suits_days(provider: Provider, days: DaysPref) -> bool:
    worked = set(provider.working_days)
    if days == "weekdays":
        return bool(worked & WEEKDAYS)
    if days == "weekends":
        return bool(worked & WEEKEND)
    return bool(worked)


def distance_miles(provider: Provider, request: JobRequest) -> float:
    home = provider.home.location
    return miles_between(home.lat, home.lng, request.address.lat, request.address.lng)


@dataclass(frozen=True)
class LimitStatus:
    on: bool
    period: str
    amount_pence: int
    earned_pence: int
    remaining_pence: int | None
    reached: bool
    period_start: date
    resumes_on: date


async def limit_status(db: Db, provider: Provider, today: date | None = None) -> LimitStatus:
    """Earnings so far this week (Mon-Sun) or calendar month, net of our fee, against the limit."""
    today = today or london_today()
    lim = provider.earnings_limit
    if lim.period == "month":
        start = month_start(today)
        resumes = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        start = week_start(today)
        resumes = start + timedelta(days=7)
    earned = await LedgerEntries(db).net_between(provider.id, start, today)
    remaining = max(0, lim.amount_pence - earned) if lim.on else None
    return LimitStatus(
        on=lim.on,
        period=lim.period,
        amount_pence=lim.amount_pence,
        earned_pence=earned,
        remaining_pence=remaining,
        reached=lim.on and earned >= lim.amount_pence,
        period_start=start,
        resumes_on=resumes,
    )


def over_limit(status: LimitStatus, price_pence: int, source: money.BookingSource = "platform") -> bool:
    """Would taking a job at this price (provider's share) go over the limit?"""
    if status.remaining_pence is None:
        return False
    return money.split_for_source(price_pence, source).provider_pence > status.remaining_pence


@dataclass(frozen=True)
class AlertTarget:
    provider: Provider
    miles: float
    limit: LimitStatus


async def alert_targets(
    db: Db, request: JobRequest, category: Category, today: date | None = None
) -> list[AlertTarget]:
    """Providers to alert about an open request, nearest first."""
    today = today or london_today()
    out: list[AlertTarget] = []
    for p in await Providers(db).with_skill(category.id):
        if request.direct_provider_id and p.id != request.direct_provider_id:
            continue
        if not can_take(p, category, today).ok:
            continue
        miles = distance_miles(p, request)
        if miles > p.travel_radius_miles and not request.direct_provider_id:
            continue
        if not suits_days(p, request.when.days):
            continue
        if not (p.alert_settings.sms or p.alert_settings.whatsapp):
            continue
        lim = await limit_status(db, p, today)
        if lim.reached:
            continue
        out.append(AlertTarget(provider=p, miles=round(miles, 1), limit=lim))
    return sorted(out, key=lambda t: t.miles)
