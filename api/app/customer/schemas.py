"""L1 customer API models. Owner: L1. Change them freely while they stay backward
compatible for the web; regenerate web types with `make types`."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.adapters.payments.base import SavedCardInfo
from app.models.common import Address, TimePref
from app.models.customers import SavedCard
from app.models.job_requests import When
from app.models.quotes import FeeSplit, Unit
from app.shared.schemas import In

# ------------------------------------------------------------------ shared views


class Badge(BaseModel):
    kind: Literal["identity", "dbs", "insured", "distance", "rating"]
    label: str = Field(
        description='e.g. "ID checked", "Basic DBS checked", "Insured until Mar 2027", "Lives 1.2 miles away"'
    )
    tone: Literal["ok", "plain"] = "ok"


class ProviderCard(BaseModel):
    provider_id: str
    short: str
    first_name: str
    initials: str
    rating_avg: float | None
    rating_count: int
    miles: float | None = Field(description="From the job's address, one decimal place")
    badges: list[Badge]


# ------------------------------------------------------------------ requests


class ContactDetails(In):
    name: str = Field(min_length=1, max_length=80)
    email: str | None = Field(default=None, max_length=254, description="For receipts")


class NewRequest(In):
    quote_id: str
    address: Address = Field(description="Resolved through /api/address/{id}: has UPRN and coordinates")
    notes: str = Field(default="", max_length=1000)
    when: When
    contact: ContactDetails
    agree_terms: Literal[True] = Field(description="The agency checkbox on the contact screen")


class RequestSummary(BaseModel):
    id: str
    ref: str
    category_id: str
    category_name: str
    status: Literal["open", "booked", "cancelled", "expired"]
    guide_pence: int
    first_pence: int | None
    unit: Unit
    area: str
    district: str
    created_at: datetime
    booking_id: str | None


class CounterOfferView(BaseModel):
    offer_id: str
    provider: ProviderCard
    price_pence: int
    first_price_pence: int | None
    guide_pence: int
    reason_text: str
    status: Literal["pending", "accepted", "declined", "lapsed", "withdrawn"]
    created_at: datetime


class TimelineEvent(BaseModel):
    """One line of "What's happened so far"."""

    at: datetime
    kind: Literal["sent", "viewing", "counter", "accepted", "declined", "cancelled", "note"]
    text: str
    provider: ProviderCard | None = None
    offer: CounterOfferView | None = None


class RequestDetail(RequestSummary):
    timeline: list[TimelineEvent]
    pending_offers: list[CounterOfferView]
    booked_with: ProviderCard | None
    booked_price_pence: int | None
    booked_via: Literal["guide", "counter"] | None
    demo_simulator: bool = Field(description="DEMO_MODE only: show the Simulate local responses control")


class SimulationStarted(BaseModel):
    provider_short: str
    counter_in_seconds: int
    accept_in_seconds: int


# ------------------------------------------------------------------ bookings, visits, plans


class BookingCard(BaseModel):
    id: str
    ref: str
    source: Literal["platform", "own_customer"]
    category_id: str
    category_name: str
    provider: ProviderCard
    recurring: bool
    frequency_label: str | None = Field(description='e.g. "every 2 weeks"')
    price_pence: int
    first_price_pence: int | None
    unit: Unit
    split: FeeSplit = Field(description="Shown to the customer: what goes to the provider and our fee")
    charged_after: Literal["each visit", "the job"]
    first_visit_text: str = Field(description='e.g. "Tuesday 29 September, morning, 8am to 12pm"')
    status: Literal["active", "completed", "cancelled"]
    thread_id: str | None
    series_id: str | None


class BookingDetail(BookingCard):
    address: Address
    agreement_text: str = Field(description="Who you're dealing with: the agency wording")
    sms_sent_to: str | None


class CustomerVisit(BaseModel):
    id: str
    booking_id: str
    category_id: str
    category_name: str
    provider_short: str
    local_date: date
    scheduled_start: datetime
    window: TimePref
    status: Literal["scheduled", "in_progress", "finished", "skipped", "cancelled"]
    label: Literal["booked", "planned", "done", "skipped"]
    price_pence: int
    minutes_actual: int | None
    after_photo_url: str | None
    rating_stars: int | None
    can_rate: bool
    can_skip: bool
    can_report: bool = Field(description="Within 48 hours of the visit")


class VisitsOut(BaseModel):
    next_visit: CustomerVisit | None
    upcoming: list[CustomerVisit]
    done: list[CustomerVisit]


class ChangeDateIn(In):
    preferred: list[date] = Field(min_length=1, max_length=3)
    note: str = Field(default="", max_length=500)


class PlanOut(BaseModel):
    series_id: str
    booking_id: str
    category_id: str
    category_name: str
    outside: bool = Field(description="Outside jobs offer the winter pause; inside jobs the away pause")
    provider: ProviderCard
    frequency: str
    frequency_label: str
    price_pence: int
    unit: Unit
    status: Literal["active", "paused", "cancelled"]
    pause_winter: bool
    away_from: date | None
    away_to: date | None
    cover_when_away: bool
    next_visit_date: date | None


class PlanUpdate(In):
    pause_winter: bool | None = None
    away_from: date | None = None
    away_to: date | None = None
    cover_when_away: bool | None = None
    frequency: Literal["weekly", "fortnightly", "threeweekly", "fourweekly", "eightweekly", "monthly"] | None = None


class RebookIn(In):
    note: str = Field(default="", max_length=500)
    when: When | None = None


# ------------------------------------------------------------------ rating and problems


class RatingIn(In):
    stars: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=8)
    tip_pence: int = Field(default=0, ge=0, le=10000, description="All of it goes to the provider (no fee)")
    comment: str = Field(default="", max_length=1000)


class RatingOut(BaseModel):
    id: str
    visit_id: str
    stars: int
    tags: list[str]
    tip_pence: int
    tip_status: Literal["none", "charged", "failed"]


class ProblemIn(In):
    description: str = Field(min_length=3, max_length=2000)
    photos: list[str] = Field(default_factory=list, max_length=4, description="File ids")


class ProblemOut(BaseModel):
    dispute_id: str
    ref: str
    status_text: str


# ------------------------------------------------------------------ profile and card


class CustomerProfile(BaseModel):
    customer_id: str
    name: str
    phone: str | None
    email: str | None
    addresses: list[Address]
    card: SavedCard | None


class ProfileUpdate(In):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    email: str | None = Field(default=None, max_length=254)


class CardConfirmed(BaseModel):
    card: SavedCardInfo


# ------------------------------------------------------------------ own-customer invites


class InvitePreview(BaseModel):
    invite_id: str
    status: Literal["invited", "accepted", "declined", "blocked", "expired"]
    customer_first_name: str
    provider: ProviderCard
    category_id: str
    category_name: str
    frequency_label: str
    price_pence: int = Field(description="Set by the provider")
    provider_fee_pence: int = Field(description="Paid by the provider; not added to the customer's price")
    next_visit_text: str | None
    phone_hint: str = Field(description="Masked number the invite was sent to; sign in with it")


class InviteAccept(In):
    agree_terms: Literal[True]
