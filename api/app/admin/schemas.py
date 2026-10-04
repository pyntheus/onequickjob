"""L3 admin API models. Owner: L3."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

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
    action: Literal["Send reminder", "Chase", "Ring them", "Check it"]


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
    status: Literal["ok", "warn", "missing", "renewal"] = Field(
        description="From the copy that counts. renewal: no checked copy in date, but an upload is waiting for a check"
    )
    expires_on: date | None
    renewal_waiting: bool = Field(default=False, description="A renewal is waiting for a check beside the checked copy")


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
    status: DocStatus = Field(description="Of the copy to check next (a waiting renewal comes first)")
    issued_on: date | None
    expires_on: date | None
    file_url: str | None
    file_id: str | None = Field(default=None, description="The upload: send it back with a verdict (VerifyDocIn)")
    verified_by: str | None
    verified_at: datetime | None
    note: str | None
    current_expires_on: date | None = Field(
        default=None, description="When this is a renewal: when the checked copy it renews runs out"
    )


class AdminHelper(BaseModel):
    """A provider's helper and their checks (Session S): admins verify their documents and mark
    them ready to be sent to visits."""

    user_id: str
    name: str
    relationship: str
    status: Literal["invited", "checking", "ready"]
    phone: str | None
    documents: list[AdminDocument]
    can_mark_ready: bool = Field(description="Not ready yet, and their ID has been checked")


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
    helper_checks: list[AdminHelper] = Field(default_factory=list, description="Each helper's documents and status")
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


REVIEWED = (
    "The upload the admin reviewed (AdminDocument.file_id; null for a copy with no file). If it has been "
    "replaced since, nothing changes: 409 document_changed"
)


class VerifyDocIn(In):
    file_id: str | None = Field(description=REVIEWED)
    issued_on: date | None = Field(default=None, description="For a basic DBS check: the issue date (valid 12 months)")
    expires_on: date | None = Field(default=None, description="For documents with a stated expiry, e.g. insurance")


class RejectDocIn(In):
    file_id: str | None = Field(description=REVIEWED)
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


# ------------------------------------------------------------------ the map (A30 to A35)
# GeoJSON-shaped, so the web hands each layer straight to the map. Coordinates are
# [longitude, latitude], GeoJSON's order. Customer addresses are exact here: admins only.

MapLayerName = Literal["open", "uncovered", "booked", "completed", "providers"]
ShadeBy = Literal["open", "booked", "completed", "none"]
# A list rather than a tuple: the typed web client reads tuples as plain arrays anyway.
LngLat = Annotated[list[float], Field(min_length=2, max_length=2)]


class PointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: LngLat = Field(description="[longitude, latitude]")


class PolygonGeometry(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[LngLat]] = Field(description="One closed ring of [longitude, latitude]")


class RequestPin(BaseModel):
    request_id: str
    ref: str
    category_id: str
    category_name: str
    area: str
    district: str
    created_at: datetime
    age_text: str = Field(description='How long it has been open: "5 hours"')
    guide_pence: int
    waiting: bool = Field(description="Open for more than an hour without a taker, so on the dispatch list")
    uncovered: bool = Field(description="Outside every active provider's travel radius (A32)")
    in_reach: int = Field(description="Active providers whose travel radius covers it")
    in_reach_doing_it: int = Field(description="Of those, how many do this kind of job")
    cover: bool = Field(description="Cover for one visit of a provider's time off")
    awaiting_customer: bool = Field(description="A raised guide is waiting for the customer (A12)")


class RequestFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: PointGeometry
    properties: RequestPin


class RequestLayer(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[RequestFeature]


class JobPin(BaseModel):
    """A booking's visits in a layer, at its address: one pin per booking, so a weekly regular
    isn't six pins on one house (A30)."""

    booking_id: str
    booking_ref: str
    category_id: str
    category_name: str
    area: str
    district: str
    provider_id: str
    provider_short: str
    own_customer: bool = Field(description="A customer the provider brought (5% fee)")
    visits: int = Field(description="Visits still to come (booked), or finished in the date range (completed)")
    visit_date: date = Field(description="The next visit (booked), or the latest finished in the range (completed)")
    price_pence: int = Field(description="That visit's price")


class JobFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: PointGeometry
    properties: JobPin


class JobLayer(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[JobFeature]
    visits: int = Field(description="Visits in the layer, all pins together")


class ProviderPin(BaseModel):
    provider_id: str
    short: str
    initials: str
    status: ProviderStatus
    area: str
    district: str
    travel_radius_miles: int
    placed_at: Literal["postcode", "approximate"] = Field(
        description="postcode: their home postcode's centroid; approximate: home rounded to about 1 km (A33)"
    )
    covers: bool = Field(description="Counts for coverage: active, or active with payouts paused (A32)")
    jobs: list[str] = Field(description="The kinds of job they do, by name")


class ProviderFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: PointGeometry
    properties: ProviderPin


class ProviderLayer(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[ProviderFeature]


class ReachArea(BaseModel):
    provider_id: str
    status: ProviderStatus
    travel_radius_miles: int
    covers: bool


class ReachFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: PolygonGeometry
    properties: ReachArea


class ReachLayer(BaseModel):
    """Each provider's travel radius as a circle around where they're shown."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[ReachFeature]


class HexCount(BaseModel):
    cell: str = Field(description="H3 cell index")
    count: int
    level: int = Field(description="Its legend band, 0 the lightest")


class HexFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: PolygonGeometry
    properties: HexCount


class HexLayer(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[HexFeature]


class HexBand(BaseModel):
    level: int
    min: int
    max: int
    label: str = Field(description='"1", "3 to 4"')


class HexGrid(BaseModel):
    """Concentration: an H3 grid (resolution 8, cells about 1 km across) counting the chosen
    layer's requests or visits (A34)."""

    shade_by: Literal["open", "booked", "completed"]
    resolution: int
    total: int
    max: int
    legend: list[HexBand]
    cells: HexLayer


class MapData(BaseModel):
    generated_at: datetime
    from_date: date = Field(description="Completed jobs: the first London day of the range")
    to_date: date = Field(description="Completed jobs: the last London day of the range (inclusive)")
    waiting_after_minutes: int = Field(description="Open this long without a taker, a request is highlighted")
    open: RequestLayer | None = None
    uncovered: RequestLayer | None = None
    booked: JobLayer | None = None
    completed: JobLayer | None = None
    providers: ProviderLayer | None = None
    reach: ReachLayer | None = None
    hexes: HexGrid | None = None
