"""L2 provider API models. Owner: L2."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.adapters.payments.base import Payout
from app.models.common import E164, DocType, GeoPoint, Weekday
from app.models.offers import Offer
from app.models.providers import AlertSettings, DocStatus
from app.models.quotes import FeeSplit, Unit
from app.shared.schemas import In

# ------------------------------------------------------------------ jobs


class LimitView(BaseModel):
    on: bool
    period: Literal["week", "month"]
    amount_pence: int
    earned_pence: int = Field(description="Received this period, after our fee")
    remaining_pence: int | None
    reached: bool
    resumes_on: date = Field(description="When alerts restart if the limit is reached")


class JobCard(BaseModel):
    request_ref: str
    category_id: str
    category_name: str
    area: str
    district: str
    miles: float
    mins: int
    frequency_label: str = Field(description='"Every 2 weeks" or "One-off"')
    guide_pence: int
    provider_pence: int = Field(description="What you'd get, after the fee")
    unit: Unit
    posted_at: datetime
    route_hint: str | None = Field(description="Another of your visits within a mile on the same day")
    state: Literal["yours", "countered", "taken"] | None
    over_limit: bool


class UpcomingVisit(BaseModel):
    visit_id: str
    local_date: date
    dow: str
    day: int
    start_time: str
    category_name: str
    area: str
    price_pence: int


class ProviderHome(BaseModel):
    greeting: str = Field(description='"Morning, Dave"')
    today_text: str
    week_earned_pence: int
    week_jobs: int
    rating_avg: float | None
    rating_count: int
    limit: LimitView
    new_jobs: list[JobCard]
    coming_up: list[UpcomingVisit]


class Fact(BaseModel):
    label: str
    value: str


class CustomerMeta(BaseModel):
    initials: str
    name: str = Field(description='"Sarah W."')
    meta: str = Field(description='"3 past bookings, pays by card"')


class JobOffer(BaseModel):
    card: JobCard
    approx: GeoPoint = Field(description="About 1 km resolution: exact address only once booked")
    facts: list[Fact]
    note: str | None
    customer: CustomerMeta
    fee_percent: int
    my_counter: Offer | None
    can_take: bool
    missing_documents: list[DocType]
    over_limit_by_pence: int | None
    booked_by_me: bool
    first_visit_text: str | None = Field(description="Once yours: when it's been added to your round")


# ------------------------------------------------------------------ the round


class RoundItem(BaseModel):
    visit_id: str
    start_time: str
    status: Literal["scheduled", "in_progress", "finished", "skipped", "cancelled"]
    is_now: bool
    category_name: str
    address_line: str
    area: str
    customer_name: str
    est_mins: int
    minutes_actual: int | None
    summary: str = Field(description='e.g. "Side gate, clippings taken away"')
    note: str
    miles_from_previous: float | None
    performer: Literal["provider", "helper", "cover"]


class TodayRound(BaseModel):
    local_date: date
    day_text: str
    items: list[RoundItem]
    helpers: list[HelperOut]


class ProviderVisit(BaseModel):
    id: str
    booking_id: str
    category_id: str
    category_name: str
    customer_name: str
    address_line: str
    directions_url: str
    local_date: date
    scheduled_start: datetime
    status: Literal["scheduled", "in_progress", "finished", "skipped", "cancelled"]
    est_mins: int
    started_at: datetime | None
    finished_at: datetime | None
    minutes_actual: int | None
    before_photos: list[str] = Field(description="URLs")
    after_photos: list[str]
    note: str
    thread_id: str | None
    price_pence: int
    provider_pence: int
    charge_status: str
    performer_name: str


class PhotoIn(In):
    kind: Literal["before", "after"]
    file_id: str


class FinishIn(In):
    minutes: int = Field(ge=1, le=720, description="Pre-filled from the timer")
    from_timer: bool
    flags: list[str] = Field(default_factory=list, max_length=8, description="What was different")
    nothing_different: bool = Field(description='"Nothing, it was as described" (exclusive with flags)')
    note: str = Field(default="", max_length=1000)


class FinishOut(BaseModel):
    visit_id: str
    minutes_actual: int
    est_mins: int
    overrun: bool
    charge_status: Literal["succeeded", "pending", "requires_action", "failed"]
    price_pence: int
    fee_pence: int
    provider_pence: int
    payout_date: date | None


class SendHelperIn(In):
    helper_user_id: str


# ------------------------------------------------------------------ earnings and tax


class WeekBar(BaseModel):
    week_start: date
    label: str
    net_pence: int


class EarningsOut(BaseModel):
    week_net_pence: int
    week_jobs: int
    weekly: list[WeekBar] = Field(description="The last 8 weeks, oldest first")
    payouts: list[Payout]
    next_payout_date: date | None
    limit: LimitView
    own_customers_active: int


class MileageDay(BaseModel):
    local_date: date
    route_text: str = Field(description='"Home, Widmer End, Hazlemere, home"')
    miles: float
    amount_pence: int


class ExpenseIn(In):
    local_date: date
    description: str = Field(min_length=1, max_length=120)
    amount_pence: int = Field(gt=0, le=1_000_000)
    category: Literal["kit", "supplies", "fuel", "other"] = "kit"
    receipt_file_id: str | None = None


class ExpenseOut(BaseModel):
    id: str
    local_date: date
    description: str
    category: str
    amount_pence: int
    receipt_url: str | None


class KeyDate(BaseModel):
    on: date
    text: str


class TaxSummary(BaseModel):
    tax_year: str
    starts_on: date
    turnover_pence: int = Field(description="What customers paid (gross), the figure for tax")
    fees_pence: int
    received_pence: int
    mileage_miles: float
    mileage_pence: int
    expenses_pence: int
    costs_pence: int = Field(description="Fees + mileage + expenses")
    allowance_pence: int = Field(description="Trading allowance, £1,000")
    allowance_profit_pence: int
    costs_profit_pence: int
    better: Literal["allowance", "costs"]
    difference_pence: int
    trips: list[MileageDay]
    expenses: list[ExpenseOut]
    key_dates: list[KeyDate]


class LimitIn(In):
    """Only the limit is accepted. The benefits question that suggests one is never sent or stored."""

    on: bool
    period: Literal["week", "month"]
    amount_pence: int = Field(ge=500, le=500_000)


# ------------------------------------------------------------------ profile, documents


class DocumentOut(BaseModel):
    type: DocType
    label: str
    status: DocStatus
    expires_on: date | None
    note: str | None
    file_url: str | None


class DocumentIn(In):
    type: DocType
    file_id: str
    expires_on: date | None = None


class HelperOut(BaseModel):
    user_id: str
    name: str
    initials: str
    relationship: str
    status: Literal["invited", "checking", "ready", "removed"]
    badges: list[str]


class HelperNew(In):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=10, max_length=20)
    relationship: str = Field(default="", max_length=40)


class ProviderProfile(BaseModel):
    provider_id: str
    name: str
    short: str
    initials: str
    area: str
    district: str
    joined_on: date | None
    rating_avg: float | None
    rating_count: int
    status: str
    skills: list[str]
    documents: list[DocumentOut]
    missing_for_skills: list[DocType]
    travel_radius_miles: int
    working_days: list[Weekday]
    alert_settings: AlertSettings
    helpers: list[HelperOut]
    payment_account_status: Literal["none", "pending", "enabled", "restricted"]
    tax_complete: bool


class ProfilePatch(In):
    skills: list[str] | None = None
    travel_radius_miles: int | None = Field(default=None, ge=1, le=15)
    working_days: list[Weekday] | None = None
    alert_settings: AlertSettings | None = None


# ------------------------------------------------------------------ time off


class TimeOffRange(In):
    from_date: date
    to_date: date


class AffectedVisit(BaseModel):
    visit_id: str
    customer_name: str
    category_name: str
    local_date: date
    area: str
    cover_allowed: bool = Field(description="The customer's plan allows cover")


class ArrangementIn(In):
    visit_id: str
    action: Literal["cover", "helper", "skip"]
    helper_user_id: str | None = None


class TimeOffIn(In):
    from_date: date
    to_date: date
    arrangements: list[ArrangementIn]


class ArrangementOut(BaseModel):
    visit_id: str
    action: Literal["cover", "helper", "skip"]
    state: Literal["planned", "arranged", "done", "failed"]
    detail: str


class TimeOffOut(BaseModel):
    id: str
    from_date: date
    to_date: date
    status: Literal["planned", "active", "done", "cancelled"]
    arrangements: list[ArrangementOut]


# ------------------------------------------------------------------ own customers


class OwnCustomerRow(BaseModel):
    id: str
    name: str
    area: str
    category_name: str
    frequency_label: str
    price_pence: int
    status: Literal["active", "invited"]


class FeeComparison(BaseModel):
    example_price_pence: int
    own_customer: FeeSplit
    standard: FeeSplit


class OwnCustomersView(BaseModel):
    comparison: FeeComparison
    customers: list[OwnCustomerRow]
    skills: list[str]


class InviteIn(In):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=10, max_length=20)
    category_id: str
    price_pence: int = Field(ge=500, le=50_000, description="The provider's own price; whole pounds")
    frequency: Literal["weekly", "fortnightly", "monthly", "threemonthly", "oneoff"]


class InviteOut(BaseModel):
    invite_id: str
    status: Literal["invited", "blocked"]
    name: str
    phone: E164
    category_id: str
    price_pence: int
    provider_pence: int
    fee_pence: int


# ------------------------------------------------------------------ sign-up


class SignupStep(BaseModel):
    key: Literal["details", "identity", "tax", "insurance", "work", "payouts"]
    title: str
    detail: str
    state: Literal["done", "now", "todo"]


class SignupChecklist(BaseModel):
    steps: list[SignupStep]
    done_count: int
    provider_id: str | None


class SignupStart(In):
    name: str = Field(min_length=1, max_length=80)
    postcode: str = Field(min_length=5, max_length=8)
    email: str | None = Field(default=None, max_length=254)


class TaxDetailsIn(In):
    ni_number: str = Field(pattern=r"^\s*[A-Za-z]{2}\s*\d{2}\s*\d{2}\s*\d{2}\s*[A-Da-d]\s*$")
    date_of_birth: date


class TaxDetailsOut(BaseModel):
    complete: bool
    ni_masked: str
    dob_masked: str


class OnboardingLink(BaseModel):
    url: str


class CallbackIn(In):
    step: str = Field(max_length=60)


TodayRound.model_rebuild()
