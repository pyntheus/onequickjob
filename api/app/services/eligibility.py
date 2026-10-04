"""Who may take a job, who gets alerted, and how far through their earnings limit they are.

Two levels (decisions.md):
- can_take (hard rules): active or payouts-paused status, the category in their skills,
  identity checked, and every document the category requires verified and in date.
  can_take_request adds the request's own hard rule (A23): the provider works at least one of
  the days the customer chose. Every accept and counter checks it. Distance is NOT a hard
  rule: admins dispatch further-away jobs by hand through the WhatsApp group.
- alert_targets (who gets the broadcast, L1): can_take, plus within their travel radius
  of the job (within_reach: the admin map's uncovered-demand rule uses it too, A32), a working
  day that suits the customer, alerts switched on, and not yet at their earnings limit. Jobs
  that would take them over the limit still alert while they have headroom; the provider's job
  list marks them (L2).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core import money
from app.core.db import Db, DbSession
from app.core.geo import miles_between
from app.core.timeutil import london_today, month_start, week_start
from app.models.categories import Category
from app.models.common import DaysPref, DocType
from app.models.job_requests import JobRequest
from app.models.providers import Provider
from app.repos.ledger_entries import LedgerEntries
from app.repos.providers import Providers

# Statuses that take new jobs: the hard rule's, and the providers who count for coverage (A32).
TAKES_JOBS = ("active", "payouts_paused")
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
    if provider.status not in TAKES_JOBS:
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


DAYS_REASON: dict[str, str] = {
    "weekdays": "This customer wants weekdays, and you don't work any weekdays.",
    "weekends": "This customer wants a weekend, and you don't work weekends.",
    "any": "You haven't chosen any days that you work.",
}


def can_take_request(
    provider: Provider, category: Category, request: JobRequest, today: date | None = None
) -> Eligibility:
    """can_take, plus A23: a provider who works none of the customer's chosen days can't take the
    request (no alert, not in their job list, accepting refused)."""
    elig = can_take(provider, category, today)
    if suits_days(provider, request.when.days):
        return elig
    days = DAYS_REASON[request.when.days] + " You can change your working days in Me."
    return Eligibility(ok=False, missing_documents=elig.missing_documents, reasons=[*elig.reasons, days])


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


def within_reach(provider: Provider, request: JobRequest) -> bool:
    """The job is inside the provider's travel radius, measured from their home as the broadcast
    measures it. The admin map's uncovered demand is an open request within no active provider's
    reach (A32)."""
    return distance_miles(provider, request) <= provider.travel_radius_miles


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


async def limit_status(
    db: Db, provider: Provider, today: date | None = None, *, session: DbSession | None = None
) -> LimitStatus:
    """Earnings so far this week (Mon-Sun) or calendar month, net of our fee, against the limit."""
    today = today or london_today()
    lim = provider.earnings_limit
    if lim.period == "month":
        start = month_start(today)
        resumes = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        start = week_start(today)
        resumes = start + timedelta(days=7)
    earned = await LedgerEntries(db).net_between(provider.id, start, today, session=session)
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
    db: Db, request: JobRequest, category: Category, today: date | None = None, *, session: DbSession | None = None
) -> list[AlertTarget]:
    """Providers to alert about an open request, nearest first."""
    today = today or london_today()
    out: list[AlertTarget] = []
    for p in await Providers(db).with_skill(category.id, session=session):
        if request.direct_provider_id and p.id != request.direct_provider_id:
            continue
        if not can_take_request(p, category, request, today).ok:
            continue
        if not within_reach(p, request) and not request.direct_provider_id:
            continue
        if not (p.alert_settings.sms or p.alert_settings.whatsapp):
            continue
        lim = await limit_status(db, p, today, session=session)
        if lim.reached:
            continue
        out.append(AlertTarget(provider=p, miles=round(distance_miles(p, request), 1), limit=lim))
    return sorted(out, key=lambda t: t.miles)
