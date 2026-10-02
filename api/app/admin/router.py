"""L3 admin endpoints (/api/admin). Owner: L3. All require the admin role.

GET /api/admin/outbox is shared (implemented in foundations, app/shared/routes.py).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.admin.schemas import (
    Calibration,
    CategoryAdminRow,
    CategoryRecord,
    ChargeState,
    CloseIn,
    DisputeMessageIn,
    DisputeView,
    DraftIn,
    NudgeIn,
    Overview,
    PricingVersionSummary,
    ProposeIn,
    ProviderDetail,
    ProviderRow,
    RaiseGuideIn,
    RefundIn,
    RefundOut,
    RejectDocIn,
    SuspendIn,
    UnfilledRequest,
    VerifyDocIn,
    WhatsAppText,
)
from app.core.deps import CurrentUser, require_admin
from app.core.errors import ERROR_RESPONSES, not_implemented
from app.models.common import DocType
from app.models.pricing_versions import PricingVersion
from app.models.system import AuditEntry
from app.shared.schemas import OutboxItem

router = APIRouter(prefix="/api/admin", tags=["L3 admin"], responses=ERROR_RESPONSES)
Admin = Annotated[CurrentUser, Depends(require_admin)]
LANE = "L3"
CSV = {200: {"content": {"text/csv": {}}, "description": "CSV file"}}


# ---------------------------------------------------------------- overview and dispatch
@router.get("/overview")
async def overview(admin: Admin) -> Overview:
    not_implemented(LANE)


@router.get("/requests/{ref}/whatsapp")
async def whatsapp_message(ref: str, admin: Admin) -> WhatsAppText:
    """The text for the providers' WhatsApp group, with the job link (/p/j/{ref})."""
    not_implemented(LANE)


@router.post("/requests/{ref}/raise-guide")
async def raise_guide(ref: str, body: RaiseGuideIn, admin: Admin) -> UnfilledRequest:
    """Raise an open request's guide price (rounded to whole pounds) and audit-log it."""
    not_implemented(LANE)


# ---------------------------------------------------------------- providers
@router.get("/providers")
async def providers(
    admin: Admin, filter: Annotated[str, Query(pattern="^(all|attention|signup)$")] = "all"
) -> list[ProviderRow]:
    not_implemented(LANE)


@router.get("/providers/{provider_id}")
async def provider_detail(provider_id: str, admin: Admin) -> ProviderDetail:
    not_implemented(LANE)


@router.post("/providers/{provider_id}/documents/{doc_type}/verify")
async def verify_document(provider_id: str, doc_type: DocType, body: VerifyDocIn, admin: Admin) -> ProviderDetail:
    not_implemented(LANE)


@router.post("/providers/{provider_id}/documents/{doc_type}/reject")
async def reject_document(provider_id: str, doc_type: DocType, body: RejectDocIn, admin: Admin) -> ProviderDetail:
    not_implemented(LANE)


@router.post("/providers/{provider_id}/suspend")
async def suspend_provider(provider_id: str, body: SuspendIn, admin: Admin) -> ProviderDetail:
    not_implemented(LANE)


@router.post("/providers/{provider_id}/reinstate")
async def reinstate_provider(provider_id: str, admin: Admin) -> ProviderDetail:
    not_implemented(LANE)


@router.post("/providers/{provider_id}/nudge")
async def nudge_provider(provider_id: str, body: NudgeIn, admin: Admin) -> OutboxItem:
    not_implemented(LANE)


# ---------------------------------------------------------------- pricing and calibration
@router.get("/pricing/calibration")
async def calibration(admin: Admin) -> Calibration:
    not_implemented(LANE)


@router.get("/pricing/versions")
async def pricing_versions(admin: Admin) -> list[PricingVersionSummary]:
    not_implemented(LANE)


@router.get("/pricing/versions/{version_id}")
async def pricing_version(version_id: str, admin: Admin) -> PricingVersion:
    not_implemented(LANE)


@router.post("/pricing/versions", status_code=201)
async def draft_pricing_version(body: DraftIn, admin: Admin) -> PricingVersionSummary:
    not_implemented(LANE)


@router.post("/pricing/versions/{version_id}/approve")
async def approve_pricing_version(version_id: str, admin: Admin) -> PricingVersionSummary:
    """A different admin from the drafter makes it live; the old live version is retired."""
    not_implemented(LANE)


# ---------------------------------------------------------------- disputes, refunds, charges
@router.get("/disputes")
async def disputes(admin: Admin) -> list[DisputeView]:
    not_implemented(LANE)


@router.get("/disputes/{ref}")
async def dispute(ref: str, admin: Admin) -> DisputeView:
    not_implemented(LANE)


@router.post("/disputes/{ref}/message")
async def dispute_message(ref: str, body: DisputeMessageIn, admin: Admin) -> DisputeView:
    not_implemented(LANE)


@router.post("/disputes/{ref}/propose")
async def dispute_propose(ref: str, body: ProposeIn, admin: Admin) -> DisputeView:
    not_implemented(LANE)


@router.post("/disputes/{ref}/close")
async def dispute_close(ref: str, body: CloseIn, admin: Admin) -> DisputeView:
    not_implemented(LANE)


@router.post("/visits/{visit_id}/refund")
async def refund_visit(visit_id: str, body: RefundIn, admin: Admin) -> RefundOut:
    """Provider-funded refund through PaymentGateway.refund, split by money.refund_split,
    recorded with services.ledger.record_refund."""
    not_implemented(LANE)


@router.post("/visits/{visit_id}/retry-charge")
async def retry_charge(visit_id: str, admin: Admin) -> ChargeState:
    not_implemented(LANE)


# ---------------------------------------------------------------- categories, export, audit
@router.get("/categories")
async def categories(admin: Admin) -> list[CategoryAdminRow]:
    not_implemented(LANE)


@router.get("/categories/{category_id}")
async def category_record(category_id: str, admin: Admin) -> CategoryRecord:
    not_implemented(LANE)


@router.get("/hmrc-export.csv", response_class=Response, responses=CSV)
async def hmrc_export(admin: Admin, year: Annotated[int, Query(ge=2024, le=2100)]) -> Response:
    """Per calendar year: each provider's identity fields and gross takings and fees from the
    ledger. The format must be checked against HMRC's specification before real use."""
    not_implemented(LANE)


@router.get("/audit")
async def audit_log(admin: Admin, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[AuditEntry]:
    not_implemented(LANE)
