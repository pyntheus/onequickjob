"""L2 provider endpoints (/api/p). Owner: L2.

Accepting at the guide price and suggesting a price are shared endpoints
(app/shared/marketplace_routes.py: POST /api/p/requests/{ref}/accept|counter).

Most endpoints are the provider's own business and refuse helpers (`Owner`); the round
(today, visits, start, photos, finish) and documents also serve helpers (`Act`).
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.adapters.address.base import AddressLookup
from app.adapters.payments.base import PaymentGateway
from app.core.config import Settings
from app.core.db import Db, get_db
from app.core.deps import CurrentUser, address_dep, current_user, gateway_dep, settings_dep
from app.core.errors import ERROR_RESPONSES, fail
from app.models.quotes import FeeSplit
from app.provider import (
    cover,
    finish,
    helpers,
    records,
)
from app.provider import (
    home as home_mod,
)
from app.provider import (
    jobs as jobs_mod,
)
from app.provider import (
    limit as limit_mod,
)
from app.provider import (
    own_customers as own,
)
from app.provider import (
    profile as profile_mod,
)
from app.provider import (
    round as round_mod,
)
from app.provider import (
    signup as signup_mod,
)
from app.provider import (
    threads as threads_mod,
)
from app.provider import (
    time_off as time_off_mod,
)
from app.provider.acting import Act, Owner, require_owner
from app.provider.schemas import (
    AffectedVisit,
    ArrangeMoreIn,
    CallbackIn,
    CounterPreview,
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
from app.services.quotes import fee_split
from app.shared.schemas import Ack, MessageOut, NewMessage, ThreadSummary

router = APIRouter(prefix="/api/p", tags=["L2 provider"], responses=ERROR_RESPONSES)
User = Annotated[CurrentUser, Depends(current_user)]
DbDep = Annotated[Db, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
Gateway = Annotated[PaymentGateway, Depends(gateway_dep)]
Lookup = Annotated[AddressLookup, Depends(address_dep)]
TaxYear = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$", description='e.g. "2026-27"; default current')]
Pence = Annotated[int, Query(gt=0, le=1_000_000, description="Integer pence")]
LANE = "L2"
CSV = {200: {"content": {"text/csv": {}}, "description": "CSV file"}}
HTML = {200: {"content": {"text/html": {}}, "description": "Printable HTML page"}}


def _year(label: str | None) -> str | None:
    """2026-27 is a tax year; 2026-99 isn't."""
    if label is not None and int(label[5:]) != (int(label[:4]) + 1) % 100:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_tax_year", "Tax years look like 2026-27.")
    return label


# ---------------------------------------------------------------- jobs
@router.get("/home")
async def home(a: Act, db: DbDep, s: SettingsDep) -> ProviderHome:
    return await home_mod.home(db, s, a)


@router.get("/jobs")
async def jobs(provider: Owner, db: DbDep, s: SettingsDep) -> list[JobCard]:
    """Open requests this provider can take (eligibility.can_take), nearest first, over-limit marked."""
    return await jobs_mod.list_jobs(db, s, provider)


@router.get("/requests/{ref}")
async def job_offer(ref: str, provider: Owner, db: DbDep, s: SettingsDep) -> JobOffer:
    """The offer screen. Records a view (JobRequests.record_view) the first time."""
    return await jobs_mod.job_offer(db, s, provider, ref)


@router.get("/requests/{ref}/counter-preview")
async def counter_preview(ref: str, price_pence: Pence, provider: Owner, db: DbDep, s: SettingsDep) -> CounterPreview:
    """What a suggested price means before it's sent (decisions.md A1): the per-visit price, the
    first-visit price it scales to and what the provider would get for each."""
    return await jobs_mod.counter_preview(db, s, provider, ref, price_pence)


# ---------------------------------------------------------------- the round
@router.get("/today")
async def today(
    a: Act,
    db: DbDep,
    day: Annotated[date | None, Query(alias="date", description="A London date; default today")] = None,
) -> TodayRound:
    return await round_mod.today_round(db, a, day)


@router.get("/visits/{visit_id}")
async def get_visit(visit_id: str, a: Act, db: DbDep, s: SettingsDep) -> ProviderVisit:
    return await round_mod.visit_detail(db, s, a, visit_id)


@router.post("/visits/{visit_id}/start")
async def start_visit(visit_id: str, a: Act, db: DbDep, s: SettingsDep) -> ProviderVisit:
    v = await round_mod.start_visit(db, s, a, visit_id)
    return await round_mod.provider_visit(db, s, a, v)


@router.post("/visits/{visit_id}/photos")
async def add_photo(visit_id: str, body: PhotoIn, a: Act, db: DbDep, s: SettingsDep) -> ProviderVisit:
    v = await round_mod.add_photo(db, a, visit_id, body)
    return await round_mod.provider_visit(db, s, a, v)


@router.post("/visits/{visit_id}/finish")
async def finish_visit(visit_id: str, body: FinishIn, a: Act, db: DbDep, s: SettingsDep, gateway: Gateway) -> FinishOut:
    """Record minutes and flags (calibration data), charge through PaymentGateway.charge_visit
    with the fee from money.split_for_visit(price, source, performer kind) (a cover provider
    pays 15% even on an own customer), write the ledger entry (services.ledger), send messages.
    The charge is never inside a transaction: save the finished visit first, charge with the
    visit's idempotency key, then record the result, ledger entry and messages in one."""
    return await finish.finish_visit(db, s, gateway, a, visit_id, body)


@router.post("/visits/{visit_id}/send-helper")
async def send_helper(visit_id: str, body: SendHelperIn, a: Act, db: DbDep, s: SettingsDep) -> ProviderVisit:
    require_owner(a)
    v = await round_mod.send_helper(db, s, a, visit_id, body.helper_user_id)
    return await round_mod.provider_visit(db, s, a, v)


@router.post("/visits/{visit_id}/cover")
async def ask_for_cover(visit_id: str, a: Act, db: DbDep, s: SettingsDep) -> ProviderVisit:
    v = await cover.ask_for_cover(db, s, require_owner(a), visit_id)
    return await round_mod.provider_visit(db, s, a, v)


# ---------------------------------------------------------------- earnings, tax, records
@router.get("/earnings")
async def earnings(provider: Owner, db: DbDep, gateway: Gateway) -> EarningsOut:
    return await records.earnings(db, gateway, provider)


@router.get("/tax")
async def tax(provider: Owner, db: DbDep, tax_year: TaxYear = None) -> TaxSummary:
    return await records.tax_summary(db, provider, _year(tax_year))


@router.get("/tax/pack.csv", response_class=Response, responses=CSV)
async def tax_pack_csv(provider: Owner, db: DbDep, tax_year: TaxYear = None) -> Response:
    name, body = await records.tax_pack_csv(db, provider, _year(tax_year))
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


@router.get("/tax/pack.html", response_class=Response, responses=HTML)
async def tax_pack_html(provider: Owner, db: DbDep, tax_year: TaxYear = None) -> Response:
    page = await records.tax_pack_html(db, provider, _year(tax_year))
    return Response(
        content=page,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "Cache-Control": "no-store",
        },
    )


@router.get("/mileage")
async def mileage(provider: Owner, db: DbDep, tax_year: TaxYear = None) -> list[MileageDay]:
    return await records.mileage(db, provider, _year(tax_year))


@router.get("/expenses")
async def list_expenses(provider: Owner, db: DbDep, tax_year: TaxYear = None) -> list[ExpenseOut]:
    return await records.list_expenses(db, provider, _year(tax_year))


@router.post("/expenses", status_code=status.HTTP_201_CREATED)
async def add_expense(body: ExpenseIn, provider: Owner, db: DbDep) -> ExpenseOut:
    return await records.add_expense(db, provider, body)


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(expense_id: str, provider: Owner, db: DbDep) -> None:
    await records.delete_expense(db, provider, expense_id)


@router.get("/limit")
async def get_limit(provider: Owner, db: DbDep) -> LimitView:
    return await limit_mod.get_limit(db, provider)


@router.get("/limit/preview")
async def preview_limit(
    provider: Owner,
    db: DbDep,
    period: Annotated[str, Query(pattern="^(week|month)$")],
    amount_pence: Annotated[int, Query(ge=500, le=500_000)],
) -> LimitView:
    """The limit screen's figures for a limit that hasn't been saved yet."""
    return await limit_mod.preview_limit(db, provider, LimitIn(on=True, period=period, amount_pence=amount_pence))  # type: ignore[arg-type]


@router.put("/limit")
async def set_limit(body: LimitIn, provider: Owner, db: DbDep) -> LimitView:
    return await limit_mod.set_limit(db, provider, body)


# ---------------------------------------------------------------- profile and documents
@router.get("/profile")
async def get_profile(provider: Owner, db: DbDep) -> ProviderProfile:
    return await profile_mod.profile(db, provider)


@router.patch("/profile")
async def update_profile(body: ProfilePatch, provider: Owner, user: User, db: DbDep, s: SettingsDep) -> ProviderProfile:
    return await profile_mod.update_profile(db, s, provider, body, user)


@router.get("/documents")
async def list_documents(a: Act, db: DbDep) -> list[DocumentOut]:
    return await profile_mod.list_documents(db, a)


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(body: DocumentIn, a: Act, db: DbDep) -> DocumentOut:
    """Attach an uploaded file (POST /api/files) as a document, status pending, for admin checks.
    Work out its expiry with services.documents.expiry_for (a basic DBS check: 12 months from issue)."""
    return await profile_mod.upload_document(db, a, body)


# ---------------------------------------------------------------- time off and helpers
@router.post("/time-off/preview")
async def time_off_preview(body: TimeOffRange, provider: Owner, db: DbDep) -> list[AffectedVisit]:
    return await time_off_mod.preview(db, provider, body)


@router.get("/time-off")
async def list_time_off(provider: Owner, db: DbDep) -> list[TimeOffOut]:
    return await time_off_mod.list_time_off(db, provider)


@router.post("/time-off", status_code=status.HTTP_201_CREATED)
async def book_time_off(body: TimeOffIn, provider: Owner, db: DbDep, s: SettingsDep) -> TimeOffOut:
    return await time_off_mod.book(db, s, provider, body)


@router.post("/time-off/{time_off_id}/arrange")
async def arrange_more(time_off_id: str, body: ArrangeMoreIn, provider: Owner, db: DbDep, s: SettingsDep) -> TimeOffOut:
    """Arrange visits booked into time off after it was arranged (cover, helper or skip)."""
    return await time_off_mod.arrange_more(db, s, provider, time_off_id, body.arrangements)


@router.delete("/time-off/{time_off_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_time_off(time_off_id: str, provider: Owner, db: DbDep, s: SettingsDep) -> None:
    await time_off_mod.cancel(db, s, provider, time_off_id)


@router.get("/helpers")
async def list_helpers(provider: Owner, db: DbDep) -> list[HelperOut]:
    return await helpers.list_helpers(db, provider)


@router.post("/helpers", status_code=status.HTTP_201_CREATED)
async def add_helper(body: HelperNew, provider: Owner, db: DbDep, s: SettingsDep) -> HelperOut:
    return await helpers.add_helper(db, s, provider, body)


# ---------------------------------------------------------------- own customers
@router.get("/own-customers")
async def own_customers(provider: Owner, db: DbDep, s: SettingsDep) -> OwnCustomersView:
    return await own.view(db, s, provider)


@router.get("/own-customers/preview")
async def own_customer_preview(price_pence: Pence, provider: Owner, s: SettingsDep) -> FeeSplit:
    """What the provider keeps from their own price for an own customer (money.py, 5% with a
    100p minimum), so the invite form never works out a fee itself."""
    del provider
    return fee_split(price_pence, "own_customer", s)


@router.post("/own-customers/invites", status_code=status.HTTP_201_CREATED)
async def invite_own_customer(body: InviteIn, provider: Owner, db: DbDep, s: SettingsDep) -> InviteOut:
    """409 platform_customer if the number already belongs to a platform customer (recorded as blocked)."""
    return await own.invite(db, s, provider, body)


# ---------------------------------------------------------------- messages
@router.get("/threads")
async def list_threads(provider: Owner, db: DbDep) -> list[ThreadSummary]:
    return await threads_mod.list_threads(db, provider.user_id)


@router.get("/threads/{thread_id}/messages")
async def list_messages(thread_id: str, provider: Owner, db: DbDep) -> list[MessageOut]:
    return await threads_mod.messages(db, provider.user_id, thread_id)


@router.post("/threads/{thread_id}/messages", status_code=status.HTTP_201_CREATED)
async def post_message(thread_id: str, body: NewMessage, provider: Owner, db: DbDep, s: SettingsDep) -> MessageOut:
    return await threads_mod.post(db, s, provider.user_id, thread_id, body.body)


# ---------------------------------------------------------------- sign-up (signed in, not yet a provider)
@router.get("/signup")
async def signup_checklist(user: User, db: DbDep, s: SettingsDep, gateway: Gateway) -> SignupChecklist:
    return await signup_mod.get_checklist(db, s, gateway, user)


@router.post("/signup/start", status_code=status.HTTP_201_CREATED)
async def signup_start(body: SignupStart, user: User, db: DbDep, lookup: Lookup) -> SignupChecklist:
    """Adds the provider role (Users.add_role) and creates the providers record (status signing_up)."""
    return await signup_mod.start(db, lookup, user, body)


@router.put("/signup/tax")
async def signup_tax(body: TaxDetailsIn, user: User, db: DbDep, s: SettingsDep) -> TaxDetailsOut:
    """Seal the full values in tax_identities (core.crypto.seal); keep only masked copies on providers."""
    return await signup_mod.save_tax(db, s, user, body)


@router.post("/signup/payment-account")
async def signup_payment_account(user: User, db: DbDep, s: SettingsDep, gateway: Gateway) -> OnboardingLink:
    """PaymentGateway.create_provider_account then onboarding_link."""
    return await signup_mod.payment_account(db, s, gateway, user)


@router.post("/signup/callback", status_code=status.HTTP_202_ACCEPTED)
async def signup_callback(body: CallbackIn, user: User, db: DbDep, s: SettingsDep) -> Ack:
    return Ack(message=await signup_mod.callback(db, s, user, body.step))


__all__ = ["LANE", "router"]
