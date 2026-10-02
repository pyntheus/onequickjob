"""The offer endpoints, implemented in foundations (F) because both L1 and L2 depend on
them from day one: L2's job screen accepts and counters; L1's request screen accepts or
declines counters, and its DEMO_MODE simulator drives the provider side through them.
All of them go through app.services.marketplace (atomic first acceptance).
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core import money
from app.core.config import Settings
from app.core.db import Db, get_db
from app.core.deps import current_customer, current_provider, settings_dep
from app.core.errors import ERROR_RESPONSES
from app.models.customers import Customer
from app.models.offers import Offer
from app.models.providers import Provider
from app.repos.providers import Providers
from app.services import marketplace, wording
from app.services.marketplace import BookingOutcome
from app.shared.schemas import BookingConfirmed, CounterRequest, VisitBrief

router = APIRouter(prefix="/api", responses=ERROR_RESPONSES, tags=["shared: marketplace"])
DbDep = Annotated[Db, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]


async def _confirmed(db: Db, s: Settings, out: BookingOutcome) -> BookingConfirmed:
    b, v = out.booking, out.first_visit
    provider = await Providers(db).get(b.provider_id)
    sp = money.split_for_source(b.price_pence, b.source, s)
    return BookingConfirmed(
        request_ref=out.request.ref,
        booking_id=b.id,
        booking_ref=b.ref,
        via=out.via,  # type: ignore[arg-type]
        provider_id=b.provider_id,
        provider_short=provider.short if provider else "",
        price_pence=b.price_pence,
        unit=b.unit,
        recurring=b.recurring,
        provider_pence=sp.provider_pence,
        fee_pence=sp.fee_pence,
        first_visit=VisitBrief(
            id=v.id,
            local_date=v.local_date,
            scheduled_start=v.scheduled_start,
            when_text=wording.when_text(v.scheduled_start, False),
            price_pence=v.price_pence,
        ),
    )


@router.post("/p/requests/{ref}/accept")
async def provider_accept(
    ref: str, db: DbDep, s: SettingsDep, provider: Annotated[Provider, Depends(current_provider)]
) -> BookingConfirmed:
    """Accept the guide price. The first provider to accept books the job; anyone later gets
    409 already_taken ("Sorry, someone else took this job first.")."""
    return await _confirmed(db, s, await marketplace.accept_at_guide(db, s, ref, provider))


@router.post("/p/requests/{ref}/counter")
async def provider_counter(
    ref: str, body: CounterRequest, db: DbDep, s: SettingsDep, provider: Annotated[Provider, Depends(current_provider)]
) -> Offer:
    """Suggest a different price. The customer accepts it or keeps waiting; if someone accepts the
    guide price first, the job goes to them. Re-sending replaces your pending suggestion."""
    return await marketplace.make_counter(
        db,
        s,
        ref,
        provider,
        price_pence=body.price_pence,
        reasons=body.reasons,
        message=body.message,
    )


@router.post("/c/offers/{offer_id}/accept")
async def customer_accept_counter(
    offer_id: str, db: DbDep, s: SettingsDep, customer: Annotated[Customer, Depends(current_customer)]
) -> BookingConfirmed:
    """Accept a provider's suggested price. 409 if the job was booked in the meantime."""
    return await _confirmed(db, s, await marketplace.accept_counter(db, s, offer_id, customer))


@router.post("/c/offers/{offer_id}/decline")
async def customer_keep_waiting(
    offer_id: str, db: DbDep, s: SettingsDep, customer: Annotated[Customer, Depends(current_customer)]
) -> Offer:
    """Keep waiting for someone at the guide price; the provider is told."""
    return await marketplace.decline_counter(db, s, offer_id, customer)
