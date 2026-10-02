"""L2 provider endpoints (/api/p). Owner: L2.

Accepting at the guide price and suggesting a price are shared endpoints
(app/shared/marketplace_routes.py: POST /api/p/requests/{ref}/accept|counter).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.deps import CurrentUser, current_provider, current_user
from app.core.errors import ERROR_RESPONSES, not_implemented
from app.models.providers import Provider
from app.provider.schemas import (
    AffectedVisit,
    CallbackIn,
    DocumentIn,
    DocumentOut,
    EarningsOut,
    ExpenseIn,
    ExpenseOut,
    FinishIn,
    FinishOut,
    HelperNew,
    HelperOut,
    InviteIn,
    InviteOut,
    JobCard,
    JobOffer,
    LimitIn,
    LimitView,
    MileageDay,
    OnboardingLink,
    OwnCustomersView,
    PhotoIn,
    ProfilePatch,
    ProviderHome,
    ProviderProfile,
    ProviderVisit,
    SendHelperIn,
    SignupChecklist,
    SignupStart,
    TaxDetailsIn,
    TaxDetailsOut,
    TaxSummary,
    TimeOffIn,
    TimeOffOut,
    TimeOffRange,
    TodayRound,
)
from app.shared.schemas import Ack, MessageOut, NewMessage, ThreadSummary

router = APIRouter(prefix="/api/p", tags=["L2 provider"], responses=ERROR_RESPONSES)
Prov = Annotated[Provider, Depends(current_provider)]
User = Annotated[CurrentUser, Depends(current_user)]
TaxYear = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$", description='e.g. "2026-27"; default current')]
LANE = "L2"
CSV = {200: {"content": {"text/csv": {}}, "description": "CSV file"}}
HTML = {200: {"content": {"text/html": {}}, "description": "Printable HTML page"}}


# ---------------------------------------------------------------- jobs
@router.get("/home")
async def home(provider: Prov) -> ProviderHome:
    not_implemented(LANE)


@router.get("/jobs")
async def jobs(provider: Prov) -> list[JobCard]:
    """Open requests this provider can take (eligibility.can_take), nearest first, over-limit marked."""
    not_implemented(LANE)


@router.get("/requests/{ref}")
async def job_offer(ref: str, provider: Prov) -> JobOffer:
    """The offer screen. Records a view (JobRequests.record_view) the first time."""
    not_implemented(LANE)


# ---------------------------------------------------------------- the round
@router.get("/today")
async def today(
    provider: Prov, date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None
) -> TodayRound:
    not_implemented(LANE)


@router.get("/visits/{visit_id}")
async def get_visit(visit_id: str, provider: Prov) -> ProviderVisit:
    not_implemented(LANE)


@router.post("/visits/{visit_id}/start")
async def start_visit(visit_id: str, provider: Prov) -> ProviderVisit:
    not_implemented(LANE)


@router.post("/visits/{visit_id}/photos")
async def add_photo(visit_id: str, body: PhotoIn, provider: Prov) -> ProviderVisit:
    not_implemented(LANE)


@router.post("/visits/{visit_id}/finish")
async def finish_visit(visit_id: str, body: FinishIn, provider: Prov) -> FinishOut:
    """Record minutes and flags (calibration data), charge through PaymentGateway.charge_visit
    with the fee from money.split_for_visit(price, source, performer kind) (a cover provider
    pays 15% even on an own customer), write the ledger entry (services.ledger), send messages."""
    not_implemented(LANE)


@router.post("/visits/{visit_id}/send-helper")
async def send_helper(visit_id: str, body: SendHelperIn, provider: Prov) -> ProviderVisit:
    not_implemented(LANE)


@router.post("/visits/{visit_id}/cover")
async def ask_for_cover(visit_id: str, provider: Prov) -> ProviderVisit:
    not_implemented(LANE)


# ---------------------------------------------------------------- earnings, tax, records
@router.get("/earnings")
async def earnings(provider: Prov) -> EarningsOut:
    not_implemented(LANE)


@router.get("/tax")
async def tax(provider: Prov, tax_year: TaxYear = None) -> TaxSummary:
    not_implemented(LANE)


@router.get("/tax/pack.csv", response_class=Response, responses=CSV)
async def tax_pack_csv(provider: Prov, tax_year: TaxYear = None) -> Response:
    not_implemented(LANE)


@router.get("/tax/pack.html", response_class=Response, responses=HTML)
async def tax_pack_html(provider: Prov, tax_year: TaxYear = None) -> Response:
    not_implemented(LANE)


@router.get("/mileage")
async def mileage(provider: Prov, tax_year: TaxYear = None) -> list[MileageDay]:
    not_implemented(LANE)


@router.get("/expenses")
async def list_expenses(provider: Prov, tax_year: TaxYear = None) -> list[ExpenseOut]:
    not_implemented(LANE)


@router.post("/expenses", status_code=status.HTTP_201_CREATED)
async def add_expense(body: ExpenseIn, provider: Prov) -> ExpenseOut:
    not_implemented(LANE)


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(expense_id: str, provider: Prov) -> None:
    not_implemented(LANE)


@router.get("/limit")
async def get_limit(provider: Prov) -> LimitView:
    not_implemented(LANE)


@router.put("/limit")
async def set_limit(body: LimitIn, provider: Prov) -> LimitView:
    not_implemented(LANE)


# ---------------------------------------------------------------- profile and documents
@router.get("/profile")
async def get_profile(provider: Prov) -> ProviderProfile:
    not_implemented(LANE)


@router.patch("/profile")
async def update_profile(body: ProfilePatch, provider: Prov) -> ProviderProfile:
    not_implemented(LANE)


@router.get("/documents")
async def list_documents(provider: Prov) -> list[DocumentOut]:
    not_implemented(LANE)


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(body: DocumentIn, provider: Prov) -> DocumentOut:
    """Attach an uploaded file (POST /api/files) as a document, status pending, for admin checks.
    Work out its expiry with services.documents.expiry_for (a basic DBS check: 12 months from issue)."""
    not_implemented(LANE)


# ---------------------------------------------------------------- time off and helpers
@router.post("/time-off/preview")
async def time_off_preview(body: TimeOffRange, provider: Prov) -> list[AffectedVisit]:
    not_implemented(LANE)


@router.get("/time-off")
async def list_time_off(provider: Prov) -> list[TimeOffOut]:
    not_implemented(LANE)


@router.post("/time-off", status_code=status.HTTP_201_CREATED)
async def book_time_off(body: TimeOffIn, provider: Prov) -> TimeOffOut:
    not_implemented(LANE)


@router.delete("/time-off/{time_off_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_time_off(time_off_id: str, provider: Prov) -> None:
    not_implemented(LANE)


@router.get("/helpers")
async def list_helpers(provider: Prov) -> list[HelperOut]:
    not_implemented(LANE)


@router.post("/helpers", status_code=status.HTTP_201_CREATED)
async def add_helper(body: HelperNew, provider: Prov) -> HelperOut:
    not_implemented(LANE)


# ---------------------------------------------------------------- own customers
@router.get("/own-customers")
async def own_customers(provider: Prov) -> OwnCustomersView:
    not_implemented(LANE)


@router.post("/own-customers/invites", status_code=status.HTTP_201_CREATED)
async def invite_own_customer(body: InviteIn, provider: Prov) -> InviteOut:
    """409 platform_customer if the number already belongs to a platform customer (recorded as blocked)."""
    not_implemented(LANE)


# ---------------------------------------------------------------- messages
@router.get("/threads")
async def list_threads(provider: Prov) -> list[ThreadSummary]:
    not_implemented(LANE)


@router.get("/threads/{thread_id}/messages")
async def list_messages(thread_id: str, provider: Prov) -> list[MessageOut]:
    not_implemented(LANE)


@router.post("/threads/{thread_id}/messages", status_code=status.HTTP_201_CREATED)
async def post_message(thread_id: str, body: NewMessage, provider: Prov) -> MessageOut:
    not_implemented(LANE)


# ---------------------------------------------------------------- sign-up (signed in, not yet a provider)
@router.get("/signup")
async def signup_checklist(user: User) -> SignupChecklist:
    not_implemented(LANE)


@router.post("/signup/start", status_code=status.HTTP_201_CREATED)
async def signup_start(body: SignupStart, user: User) -> SignupChecklist:
    """Adds the provider role (Users.add_role) and creates the providers record (status signing_up)."""
    not_implemented(LANE)


@router.put("/signup/tax")
async def signup_tax(body: TaxDetailsIn, user: User) -> TaxDetailsOut:
    """Seal the full values in tax_identities (core.crypto.seal); keep only masked copies on providers."""
    not_implemented(LANE)


@router.post("/signup/payment-account")
async def signup_payment_account(user: User) -> OnboardingLink:
    """PaymentGateway.create_provider_account then onboarding_link."""
    not_implemented(LANE)


@router.post("/signup/callback", status_code=status.HTTP_202_ACCEPTED)
async def signup_callback(body: CallbackIn, user: User) -> Ack:
    not_implemented(LANE)
