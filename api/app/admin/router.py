"""L3 admin endpoints (/api/admin). Owner: L3. All require the admin role.

GET /api/admin/outbox is shared (implemented in foundations, app/shared/routes.py). The work is
in the modules beside this one: overview, providers, pricing, disputes, catalogue, export, and
app.payments for charges and refunds.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, Query, Response, status

from app.adapters.payments.base import PaymentGateway
from app.admin import catalogue, disputes, export, overview, pricing, providers
from app.admin import map as admin_map
from app.admin.schemas import (
    Calibration,
    CategoryAdminRow,
    CategoryRecord,
    ChargeState,
    CloseIn,
    DisputeMessageIn,
    DisputeView,
    DraftIn,
    MapData,
    MapLayerName,
    NudgeIn,
    OnboardingLinkOut,
    Overview,
    PricingVersionSummary,
    ProposeIn,
    ProviderDetail,
    ProviderRow,
    RaiseGuideIn,
    RefundIn,
    RefundOut,
    RejectDocIn,
    ShadeBy,
    SuspendIn,
    UnfilledRequest,
    VerifyDocIn,
    WhatsAppText,
)
from app.core.config import Settings
from app.core.db import Db, get_db
from app.core.deps import CurrentUser, gateway_dep, require_admin, settings_dep
from app.core.errors import ERROR_RESPONSES, fail
from app.models.common import Actor, DocType
from app.models.pricing_versions import PricingVersion
from app.models.system import AuditEntry
from app.payments import charging, refunds
from app.repos import AuditLog
from app.shared.schemas import OutboxItem

log = logging.getLogger("oqj.admin")
router = APIRouter(prefix="/api/admin", tags=["L3 admin"], responses=ERROR_RESPONSES)
Admin = Annotated[CurrentUser, Depends(require_admin)]
DbDep = Annotated[Db, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
Gateway = Annotated[PaymentGateway, Depends(gateway_dep)]
LANE = "L3"
CSV = {200: {"content": {"text/csv": {}}, "description": "CSV file"}}


def actor(admin: CurrentUser) -> Actor:
    return admin.actor("admin")


@asynccontextmanager
async def gateway_errors() -> AsyncIterator[None]:
    """The payment provider being unreachable (or refusing) becomes a 502 with plain words."""
    try:
        yield
    except (stripe.StripeError, LookupError, ConnectionError) as e:
        log.warning("payment gateway error: %s", e)
        fail(
            status.HTTP_502_BAD_GATEWAY,
            "gateway_unavailable",
            "We couldn't get an answer from the payment provider. Try again in a minute.",
        )


# ---------------------------------------------------------------- overview and dispatch
@router.get("/overview")
async def overview_(admin: Admin, db: DbDep) -> Overview:
    return await overview.overview(db)


@router.get("/requests/{ref}/whatsapp")
async def whatsapp_message(ref: str, admin: Admin, db: DbDep, s: SettingsDep) -> WhatsAppText:
    """The text for the providers' WhatsApp group, with the job link (/p/j/{ref})."""
    return await overview.whatsapp_text(db, s, ref)


@router.post("/requests/{ref}/raise-guide")
async def raise_guide(ref: str, body: RaiseGuideIn, admin: Admin, db: DbDep, s: SettingsDep) -> UnfilledRequest:
    """Suggest a higher guide price for an open request (rounded to whole pounds), audit-logged. It
    waits for the customer's approval (A12): the request shows "Awaiting customer" until then."""
    return await overview.raise_guide(db, s, ref, body.percent, body.note, actor(admin))


# ---------------------------------------------------------------- the map (A30 to A35)
@router.get("/map")
async def map_(
    admin: Admin,
    db: DbDep,
    layers: Annotated[
        list[MapLayerName], Query(description="The layers to send; repeat it. None at all: only the grid")
    ] = [],  # noqa: B006 (FastAPI copies defaults)
    shade: Annotated[ShadeBy, Query(description="The job layer the hexagon grid counts, or none")] = "open",
    from_: Annotated[date | None, Query(alias="from", description="Completed jobs from this London day")] = None,
    to: Annotated[date | None, Query(description="... to this one, inclusive (default: the last 30 days)")] = None,
) -> MapData:
    """What the admin map's layers need, as GeoJSON features: open requests (highlighted once
    waiting an hour), uncovered demand (A32), booked visits still to come, completed jobs in the
    date range, providers at their postcode's centroid with their travel radius (A33), and the H3
    concentration grid of one job layer (A34). Customer addresses are exact: admins only."""
    start, end = admin_map.date_range(from_, to)
    return await admin_map.map_data(db, set(layers), shade, start, end)


# ---------------------------------------------------------------- providers
@router.get("/providers")
async def providers_(
    admin: Admin, db: DbDep, filter: Annotated[str, Query(pattern="^(all|attention|signup)$")] = "all"
) -> list[ProviderRow]:
    return await providers.provider_rows(db, filter)  # type: ignore[arg-type]


@router.get("/providers/{provider_id}")
async def provider_detail(provider_id: str, admin: Admin, db: DbDep) -> ProviderDetail:
    return await providers.detail(db, provider_id)


@router.post("/providers/{provider_id}/documents/{doc_type}/verify")
async def verify_document(
    provider_id: str, doc_type: DocType, body: VerifyDocIn, admin: Admin, db: DbDep, s: SettingsDep
) -> ProviderDetail:
    """Set the expiry with services.documents.expiry_for (a basic DBS check: 12 months from its
    issue date); F's task reminds the provider 30 days before it lapses."""
    await providers.verify_document(
        db, s, provider_id, doc_type, body.issued_on, body.expires_on, actor(admin), reviewed=body.file_id
    )
    return await providers.detail(db, provider_id)


@router.post("/providers/{provider_id}/documents/{doc_type}/reject")
async def reject_document(
    provider_id: str, doc_type: DocType, body: RejectDocIn, admin: Admin, db: DbDep, s: SettingsDep
) -> ProviderDetail:
    await providers.reject_document(db, s, provider_id, doc_type, body.reason, actor(admin), reviewed=body.file_id)
    return await providers.detail(db, provider_id)


@router.post("/providers/{provider_id}/helpers/{user_id}/documents/{doc_type}/verify")
async def verify_helper_document(
    provider_id: str, user_id: str, doc_type: DocType, body: VerifyDocIn, admin: Admin, db: DbDep, s: SettingsDep
) -> ProviderDetail:
    """A helper's document, checked as a provider's is; the helper is texted (Session S)."""
    await providers.verify_helper_document(
        db, s, provider_id, user_id, doc_type, body.issued_on, body.expires_on, actor(admin), reviewed=body.file_id
    )
    return await providers.detail(db, provider_id)


@router.post("/providers/{provider_id}/helpers/{user_id}/documents/{doc_type}/reject")
async def reject_helper_document(
    provider_id: str, user_id: str, doc_type: DocType, body: RejectDocIn, admin: Admin, db: DbDep, s: SettingsDep
) -> ProviderDetail:
    await providers.reject_helper_document(
        db, s, provider_id, user_id, doc_type, body.reason, actor(admin), reviewed=body.file_id
    )
    return await providers.detail(db, provider_id)


@router.post("/providers/{provider_id}/helpers/{user_id}/ready")
async def mark_helper_ready(provider_id: str, user_id: str, admin: Admin, db: DbDep, s: SettingsDep) -> ProviderDetail:
    """The helper can be sent to visits once their ID is checked; the provider is texted (Session S)."""
    await providers.mark_helper_ready(db, s, provider_id, user_id, actor(admin))
    return await providers.detail(db, provider_id)


@router.post("/providers/{provider_id}/suspend")
async def suspend_provider(
    provider_id: str, body: SuspendIn, admin: Admin, db: DbDep, s: SettingsDep
) -> ProviderDetail:
    await providers.suspend(db, s, provider_id, body.reason, actor(admin))
    return await providers.detail(db, provider_id)


@router.post("/providers/{provider_id}/reinstate")
async def reinstate_provider(provider_id: str, admin: Admin, db: DbDep, s: SettingsDep) -> ProviderDetail:
    await providers.reinstate(db, s, provider_id, actor(admin))
    return await providers.detail(db, provider_id)


@router.post("/providers/{provider_id}/nudge")
async def nudge_provider(provider_id: str, body: NudgeIn, admin: Admin, db: DbDep, s: SettingsDep) -> OutboxItem:
    return await providers.nudge(db, s, provider_id, body, actor(admin))


@router.post("/providers/{provider_id}/payment-account")
async def provider_payment_account(
    provider_id: str, admin: Admin, db: DbDep, s: SettingsDep, gateway: Gateway
) -> OnboardingLinkOut:
    """Create the provider's payment account if needed and return the payment provider's hosted
    onboarding link (L3 addition: lets admin support a provider through Stripe onboarding)."""
    async with gateway_errors():
        return await providers.payment_account_link(db, s, gateway, provider_id, actor(admin))


@router.post("/providers/{provider_id}/payment-account/sync")
async def sync_provider_payment_account(
    provider_id: str, admin: Admin, db: DbDep, s: SettingsDep, gateway: Gateway
) -> ProviderDetail:
    """Read the account's state from the payment provider now (webhooks do it too; L3 addition)."""
    async with gateway_errors():
        await providers.sync_payment_account(db, s, gateway, provider_id, actor(admin))
    return await providers.detail(db, provider_id)


# ---------------------------------------------------------------- pricing and calibration
@router.get("/pricing/calibration")
async def calibration(admin: Admin, db: DbDep) -> Calibration:
    return await pricing.calibration(db)


@router.get("/pricing/versions")
async def pricing_versions(admin: Admin, db: DbDep) -> list[PricingVersionSummary]:
    return await pricing.versions(db, admin.id)


@router.get("/pricing/versions/{version_id}")
async def pricing_version(version_id: str, admin: Admin, db: DbDep) -> PricingVersion:
    return await pricing.version(db, version_id)


@router.post("/pricing/versions", status_code=201)
async def draft_pricing_version(body: DraftIn, admin: Admin, db: DbDep) -> PricingVersionSummary:
    return await pricing.draft(db, body.based_on, body.changes, body.notes, actor(admin))


@router.post("/pricing/versions/{version_id}/approve")
async def approve_pricing_version(version_id: str, admin: Admin, db: DbDep) -> PricingVersionSummary:
    """A different admin from the drafter makes it live; the old live version is retired."""
    return await pricing.approve(db, version_id, actor(admin))


# ---------------------------------------------------------------- disputes, refunds, charges
@router.get("/disputes")
async def disputes_(admin: Admin, db: DbDep) -> list[DisputeView]:
    return await disputes.listing(db)


@router.get("/disputes/{ref}")
async def dispute(ref: str, admin: Admin, db: DbDep) -> DisputeView:
    return await disputes.one(db, ref)


@router.post("/disputes/{ref}/message")
async def dispute_message(ref: str, body: DisputeMessageIn, admin: Admin, db: DbDep, s: SettingsDep) -> DisputeView:
    return await disputes.message(db, s, ref, body, actor(admin))


@router.post("/disputes/{ref}/propose")
async def dispute_propose(ref: str, body: ProposeIn, admin: Admin, db: DbDep, s: SettingsDep) -> DisputeView:
    return await disputes.propose(db, s, ref, body, actor(admin))


@router.post("/disputes/{ref}/close")
async def dispute_close(
    ref: str, body: CloseIn, admin: Admin, db: DbDep, s: SettingsDep, gateway: Gateway
) -> DisputeView:
    async with gateway_errors():
        return await disputes.close(db, s, gateway, ref, body, actor(admin))


@router.post("/visits/{visit_id}/refund")
async def refund_visit(
    visit_id: str, body: RefundIn, admin: Admin, db: DbDep, s: SettingsDep, gateway: Gateway
) -> RefundOut:
    """Provider-funded refund through PaymentGateway.refund, split by money.refund_split,
    recorded with services.ledger.record_refund."""
    async with gateway_errors():
        return await refunds.refund_visit(db, s, gateway, visit_id, body.amount_pence, body.reason, actor(admin))


@router.post("/visits/{visit_id}/retry-charge")
async def retry_charge(visit_id: str, admin: Admin, db: DbDep, s: SettingsDep, gateway: Gateway) -> ChargeState:
    async with gateway_errors():
        visit = await charging.retry_charge(db, s, gateway, visit_id, actor(admin))
    return ChargeState(visit_id=visit.id, status=visit.charge.status, failure_reason=visit.charge.failure_reason)


# ---------------------------------------------------------------- categories, export, audit
@router.get("/categories")
async def categories(admin: Admin, db: DbDep) -> list[CategoryAdminRow]:
    return await catalogue.rows(db)


@router.get("/categories/{category_id}")
async def category_record(category_id: str, admin: Admin, db: DbDep) -> CategoryRecord:
    return await catalogue.record(db, category_id)


@router.get("/hmrc-export.csv", response_class=Response, responses=CSV)
async def hmrc_export(
    admin: Admin, db: DbDep, s: SettingsDep, year: Annotated[int, Query(ge=2024, le=2100)]
) -> Response:
    """Per calendar year: each provider's identity fields and gross takings and fees from the
    ledger. The format must be checked against HMRC's specification before real use."""
    body, _ = await export.hmrc_csv(db, s, year, actor(admin))
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="onequickjob-hmrc-{year}.csv"',
            "Cache-Control": "no-store",
            "X-OQJ-Note": "Draft format: check against HMRC's specification before real use",
        },
    )


@router.get("/audit")
async def audit_log(admin: Admin, db: DbDep, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[AuditEntry]:
    return await AuditLog(db).find({}, sort=[("at", -1), ("_id", -1)], limit=limit)
