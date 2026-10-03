"""The earnings limit: only the limit is stored, never the benefits answer that suggests one.

What counts is what the provider receives after our fee, this week (Monday to Sunday) or
this calendar month (services.eligibility.limit_status). Reaching it pauses job alerts
(eligibility.alert_targets); jobs that would take them over are marked on their list.
"""

from datetime import date

from app.core.db import Db, DbSession
from app.core.rounding import D, round_half_up
from app.core.timeutil import london_today
from app.models.providers import EarningsLimit, Provider
from app.provider.schemas import LimitIn, LimitView
from app.repos.providers import Providers
from app.services.eligibility import LimitStatus, limit_status


def limit_view(st: LimitStatus) -> LimitView:
    used = 0
    if st.amount_pence > 0:
        used = min(100, round_half_up(D(st.earned_pence) * 100 / st.amount_pence))
    return LimitView(
        on=st.on,
        period=st.period,  # type: ignore[arg-type]
        amount_pence=st.amount_pence,
        earned_pence=st.earned_pence,
        remaining_pence=st.remaining_pence,
        reached=st.reached,
        resumes_on=st.resumes_on,
        used_percent=max(0, used),
    )


async def get_limit(db: Db, provider: Provider, today: date | None = None) -> LimitView:
    return limit_view(await limit_status(db, provider, today or london_today()))


async def preview_limit(db: Db, provider: Provider, draft: LimitIn) -> LimitView:
    """The limit screen while it's being changed: the same figures for a draft, unsaved."""
    trial = provider.model_copy(update={"earnings_limit": EarningsLimit(**draft.model_dump())})
    return limit_view(await limit_status(db, trial, london_today()))


async def set_limit(db: Db, provider: Provider, body: LimitIn, *, session: DbSession | None = None) -> LimitView:
    """Store the limit (on, period, amount) and nothing else: LimitIn rejects unknown fields,
    so a benefits answer can't even be sent."""
    limit = EarningsLimit(on=body.on, period=body.period, amount_pence=body.amount_pence)
    updated = await Providers(db).patch(provider.id, {"earnings_limit": limit.model_dump()}, session=session)
    assert updated is not None
    return await get_limit(db, updated)
