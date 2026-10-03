"""L3 admin API models. Owner: L3."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.categories import Category
from app.models.common import DocType
from app.models.disputes import DisputeEvent, Resolution
from app.models.pricing_versions import ParamChange
from app.models.providers import DocStatus, ProviderStatus
from app.models.records import LedgerEntry
from app.shared.schemas import In

# ------------------------------------------------------------------ overview


class Kpi(BaseModel):
    label: str
    value: str
    sub: str


class UnfilledRequest(BaseModel):
    request_id: str
    request_ref: str
    category_id: str
    category_name: str
    area: str
    district: str
    waiting_since: datetime
    age_text: str = Field(description='"5 hours"')
    guide_pence: int
    brief: str
    why: str = Field(description="Why it's stuck, from views and counters (or the admin note)")
    views: int
    pending_counters: int
    awaiting_customer: bool = Field(default=False, description="A raised guide is waiting for the customer (A12)")
    proposed_guide_pence: int | None = Field(default=None, description="The raise they've been asked to approve")


class DistrictTile(BaseModel):
    code: str
    name: str
    jobs: int
    providers: int


class OwnCustomersCard(BaseModel):
    active: int
    providers: int
    job_value_pence: int
    revenue_pence: int
    invites_blocked: int


class AttentionItem(BaseModel):
    provider_id: str
    short: str
    issue: str
    tone: Literal["warn", "danger"]
    action: Literal["Send reminder", "Chase", "Ring them"]


class PaymentIssue(BaseModel):
    """A visit whose charge failed, waits for the customer, hasn't been confirmed, or never started
    (status not_started: finished, but no charge was recorded), or a refund that's stuck."""

    visit_id: str
    customer_name: str
    provider_short: str
    category_name: str
    local_date: date
    amount_pence: int
    status: str
    failure_reason: str | None
    since: datetime
    kind: Literal["charge", "refund"] = "charge"


class Overview(BaseModel):
    week_label: str
    season_note: str | None
    kpis: list[Kpi]
    waiting: list[UnfilledRequest]
    districts: list[DistrictTile]
    own_customers: OwnCustomersCard
    attention: list[AttentionItem]
    payments: list[PaymentIssue] = Field(default_factory=list, description="Charges needing a look (L3 addition)")


class RaiseGuideIn(In):
    percent: int = Field(default=10, ge=1, le=50)
    note: str = Field(default="", max_length=300)


class WhatsAppText(BaseModel):
    text: str


# ------------------------------------------------------------------ providers


class InsuranceState(BaseModel):
    status: Literal["ok", "warn", "missing"]
    expires_on: date | None


class ProviderRow(BaseModel):
    id: str
    name: str
    short: str
    initials: str
    area: str
    district: str
    skills: list[str]
    rating_avg: float | None
    rating_count: int
    jobs_30d: int
    accept_rate: float | None
    insurance: InsuranceState
    hmrc_complete: bool
    status: ProviderStatus


class AdminDocument(BaseModel):
    type: DocType
    label: str
    status: DocStatus
    issued_on: date | None
    expires_on: date | None
    file_url: str | None
    verified_by: str | None
    verified_at: datetime | None
    note: str | None


class RecentRating(BaseModel):
    visit_id: str
    stars: int
    tags: list[str]
    customer_name: str
    created_at: datetime


class ProviderDetail(ProviderRow):
    phone: str | None
    email: str | None
    travel_radius_miles: int
    working_days: list[str]
    documents: list[AdminDocument]
    ledger: list[LedgerEntry] = Field(description="Most recent entries")
    ratings: list[RecentRating]
    helpers: list[str]
    payout_account_status: Literal["none", "pending", "enabled", "restricted"]
    payout_account_id: str | None = Field(default=None, description="L3 addition")
    payout_account_gateway: Literal["fake", "stripe"] | None = Field(default=None, description="L3 addition")
    status_reason: str | None = Field(default=None, description="Why they're suspended, if they are (L3 addition)")
    issues: list[str] = Field(default_factory=list, description="What needs attention, in words (L3 addition)")


class OnboardingLinkOut(BaseModel):
    """The payment provider's hosted onboarding for a provider's account (L3 addition)."""

    account_id: str
    url: str
    status: Literal["pending", "enabled", "restricted"]


class VerifyDocIn(In):
    issued_on: date | None = Field(default=None, description="For a basic DBS check: the issue date (valid 12 months)")
    expires_on: date | None = Field(default=None, description="For documents with a stated expiry, e.g. insurance")


class RejectDocIn(In):
    reason: str = Field(min_length=3, max_length=300)


class SuspendIn(In):
    reason: str = Field(min_length=3, max_length=300)


class NudgeIn(In):
    kind: Literal["insurance_reminder", "tax_details", "signup_help"]
    note: str = Field(default="", max_length=300)


# ------------------------------------------------------------------ pricing and calibration


class CalibrationPoint(BaseModel):
    visit_id: str
    segment: str
    est_mins: int
    actual_mins: int


class Segment(BaseModel):
    id: str
    label: str
    color_token: str = Field(description="CSS variable, e.g. --c1")


class SegmentRow(BaseModel):
    segment: str
    label: str
    jobs: int
    taken_at_guide: float
    countered: float
    median_counter_uplift_pence: int
    median_overrun: float
    over_25: float


class Suggestion(BaseModel):
    id: str
    title: str
    body: str
    change_text: str
    change: ParamChange


class Calibration(BaseModel):
    kpis: list[Kpi]
    points: list[CalibrationPoint]
    segments: list[Segment]
    table: list[SegmentRow]
    suggestions: list[Suggestion]
    live_version: int


class PricingVersionSummary(BaseModel):
    id: str
    version: int
    status: Literal["draft", "live", "retired"]
    notes: str
    changes: list[ParamChange]
    created_by: str
    created_by_name: str
    created_at: datetime
    approved_by: str | None
    approved_by_name: str | None
    approved_at: datetime | None
    can_approve: bool = Field(description="False for the admin who drafted it")


class ChangeIn(In):
    category_id: str
    path: str = Field(description="Dotted path in that category's params, e.g. growth.overgrown")
    after: Any


class DraftIn(In):
    based_on: str = Field(description="Version id to copy (normally the live one)")
    changes: list[ChangeIn] = Field(min_length=1)
    notes: str = Field(default="", max_length=1000)


# ------------------------------------------------------------------ disputes


class DisputeView(BaseModel):
    id: str
    ref: str
    title: str
    category_id: str
    area: str
    customer_name: str
    provider_short: str
    opened_at: datetime
    opened_text: str = Field(description='"2 days ago"')
    stage: int = Field(ge=0, le=3)
    stages: list[str]
    status_text: str
    amount_pence: int
    proposed: Resolution | None
    resolution: Resolution | None
    events: list[DisputeEvent]
    thread_id: str | None
    visit_id: str = ""
    provider_first: str = ""
    charge_status: str = Field(default="none", description="The disputed visit's charge (L3 addition)")
    charged_pence: int = 0
    refunded_pence: int = 0
    refundable_pence: int = Field(default=0, description="What's left to refund, less refunds in flight")
    closing_outcome: Literal["return_visit", "partial_refund", "full_refund", "none"] | None = Field(
        default=None, description="A close in progress, waiting for its refund to be confirmed (L3 addition)"
    )
    closing_amount_pence: int | None = None


class DisputeMessageIn(In):
    to: Literal["both", "customer", "provider"] = "both"
    body: str = Field(min_length=1, max_length=1000)


class ProposeIn(In):
    kind: Literal["return_visit", "partial_refund"]
    amount_pence: int | None = Field(default=None, gt=0, description="For a partial refund (provider-funded)")
    note: str = Field(default="", max_length=500)


class CloseIn(In):
    outcome: Literal["return_visit", "partial_refund", "full_refund", "none"]
    amount_pence: int | None = Field(default=None, gt=0)
    note: str = Field(default="", max_length=500)


class RefundIn(In):
    amount_pence: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=300)


class RefundOut(BaseModel):
    visit_id: str
    status: Literal["succeeded", "pending", "failed"]
    refund_id: str | None
    amount_pence: int
    fee_refunded_pence: int
    provider_refunded_pence: int


class ChargeState(BaseModel):
    visit_id: str
    status: str
    failure_reason: str | None


# ------------------------------------------------------------------ categories


class CategoryAdminRow(BaseModel):
    category: Category
    provider_count: int
    extra_documents: list[str] = Field(description="Required documents other than insurance, as labels")


class CategoryRecord(BaseModel):
    category: Category
    pricing_version: int
    pricing_params: dict[str, Any]


class WebhookAck(BaseModel):
    received: bool = True
    duplicate: bool = False
