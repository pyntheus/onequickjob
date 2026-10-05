"""Request and response models for the shared endpoints implemented in foundations (F)."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.adapters.area.base import AreaInput
from app.models.categories import Category, CategoryGroup, DocumentType, ExcludedJob
from app.models.common import Address, Channel, Related, Role
from app.models.quotes import FeeSplit, Measure, QuoteResult
from app.models.system import Recipient


class In(BaseModel):
    """Base for request bodies: unknown fields are an error, not silently dropped."""

    model_config = ConfigDict(extra="forbid")


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "down"]
    version: str
    instance: str


class FeeConfig(BaseModel):
    standard_percent: int
    own_customer_percent: int
    own_customer_min_pence: int


class PaymentsConfig(BaseModel):
    gateway: Literal["fake", "stripe"]
    publishable_key: str | None = None


class PublicConfig(BaseModel):
    brand: str
    demo_mode: bool
    public_base_url: str
    timezone: Literal["Europe/London"] = "Europe/London"
    fees: FeeConfig
    payments: PaymentsConfig
    address_lookup: Literal["fake", "ideal_postcodes"]
    area_estimator: str


# ---------------------------------------------------------------- auth
class Me(BaseModel):
    user_id: str
    name: str
    phone: str | None = Field(description="National format, e.g. 07700 900123")
    email: str | None
    roles: list[Role]
    customer_id: str | None
    provider_id: str | None
    helper_of: str | None = Field(description="Provider id, if this user is a helper")
    home_path: str = Field(description="Where this user lands: /account, /p or /admin")


class CodeRequest(In):
    identifier: str = Field(min_length=3, max_length=254, description="UK mobile number or email address")


class CodeSent(BaseModel):
    channel: Channel
    sent_to: str = Field(description="Masked, e.g. 07700 9•••23")
    expires_in_seconds: int


class VerifyRequest(In):
    identifier: str = Field(min_length=3, max_length=254)
    code: str = Field(pattern=r"^\s*\d{6}\s*$")
    name: str | None = Field(default=None, max_length=80, description="Used if this creates a new account")


class MagicRequest(In):
    token: str = Field(min_length=10, max_length=200)


class MagicResult(BaseModel):
    me: Me
    next: str = Field(description="Path to open after signing in")


# ---------------------------------------------------------------- demo
class DemoUser(BaseModel):
    user_id: str
    demo_key: str
    name: str
    roles: list[Role]
    group: Literal["Customers", "Providers", "Helpers", "Admins"]
    description: str
    home_path: str


class SwitchRequest(In):
    user_id: str


# ---------------------------------------------------------------- outbox
class OutboxItem(BaseModel):
    id: str
    channel: Channel
    recipient: Recipient
    template_id: str
    subject: str | None
    body: str
    related: Related
    created_at: datetime
    not_before: datetime | None


class OutboxPage(BaseModel):
    items: list[OutboxItem]
    next_before: str | None = Field(description="Pass as ?before= for the next page")


# ---------------------------------------------------------------- catalogue
class Catalogue(BaseModel):
    groups: list[CategoryGroup]
    categories: list[Category]
    document_types: list[DocumentType]
    excluded: list[ExcludedJob]


# ---------------------------------------------------------------- quotes
class QuoteRequest(In):
    category_id: str
    answers: dict[str, Any] = Field(
        default_factory=dict, description="Keyed by intake field key; missing keys take defaults"
    )
    lawn: AreaInput | None = Field(default=None, description="Required for categories with measure == lawn")
    address: Address | None = Field(default=None, description="From /api/address/{id}, if chosen already")


class AreaEstimateOut(BaseModel):
    measure: Measure = Field(description="The area, how it was sized and each lawn")
    text: str = Field(description='"That\'s about 12 × 8 metres (96 m²)", or "... in total across 2 lawns"')
    lawn_texts: list[str] = Field(description='Each lawn: "about 12 × 8 metres (96 m²)"')


class ConfidenceCopy(BaseModel):
    level: Literal["high", "medium", "low"]
    bars: int = Field(ge=1, le=3)
    label: str = Field(description='e.g. "Usually close"')
    note: str


class QuoteOut(BaseModel):
    id: str
    category_id: str
    answers: dict[str, Any]
    measure: Measure | None
    pricing_version: int
    pricing_version_id: str
    result: QuoteResult
    fee: FeeSplit
    first_fee: FeeSplit | None
    confidence: ConfidenceCopy
    size_text: str | None = Field(
        default=None, description='Lawns: what the price is for, e.g. "a large lawn (about 190 m²)"'
    )
    duration_text: str = Field(description='How long it usually takes: "38 minutes", "1½ hours"')
    first_duration_text: str | None
    created_at: datetime


# ---------------------------------------------------------------- files
class FileOut(BaseModel):
    id: str
    kind: str
    url: str
    content_type: str
    size: int


# ---------------------------------------------------------------- marketplace
class CounterRequest(In):
    price_pence: int = Field(
        gt=0,
        description="Per-visit price, whole pounds, 80% to 300% of the guide. A job with a dearer first visit "
        "gets its first-visit price scaled by the same ratio (returned on the offer)",
    )
    reasons: list[str] = Field(default_factory=list, max_length=6)
    message: str = Field(default="", max_length=300)


class VisitBrief(BaseModel):
    id: str
    local_date: date
    scheduled_start: datetime
    when_text: str = Field(description='e.g. "Tuesday 13 October at 10:30"')
    price_pence: int


class BookingConfirmed(BaseModel):
    request_ref: str
    booking_id: str
    booking_ref: str
    via: Literal["guide", "counter", "direct"]
    provider_id: str
    provider_short: str
    price_pence: int
    unit: str
    recurring: bool
    provider_pence: int = Field(description="What the provider receives per visit, after our fee")
    fee_pence: int
    first_visit: VisitBrief


# ---------------------------------------------------------------- message threads (every lane)
class ThreadSummary(BaseModel):
    id: str
    kind: Literal["booking", "dispute", "support"]
    title: str = Field(description='e.g. "Lawn mowing with Dave H."')
    other_party: str
    last_message_at: datetime | None
    preview: str
    unread: int


class MessageOut(BaseModel):
    id: str
    sender_user_id: str | None
    sender_role: str
    sender_name: str
    body: str
    created_at: datetime
    mine: bool


class NewMessage(In):
    body: str = Field(min_length=1, max_length=1000)


class Ack(BaseModel):
    ok: Literal[True] = True
    message: str = ""
