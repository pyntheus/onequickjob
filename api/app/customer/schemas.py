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
    photos: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="File ids from POST /api/files (kind request_photo), uploaded once signed in",
    )


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
    frequency_label: str | None = Field(default=None, description='e.g. "every 2 weeks"; None for a one-off')


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


class PriceChangeView(BaseModel):
    """A raised guide waiting for the customer's approval (A12)."""

    change_id: str = Field(description="Send it back with the answer")
    guide_pence: int
    first_pence: int | None
    from_guide_pence: int
    from_first_pence: int | None
    proposed_at: datetime


class RequestDetail(RequestSummary):
    timeline: list[TimelineEvent]
    pending_offers: list[CounterOfferView]
    booked_with: ProviderCard | None
    booked_price_pence: int | None
    booked_via: Literal["guide", "counter"] | None
    demo_simulator: bool = Field(description="DEMO_MODE only: show the Simulate local responses control")
    booked_first_price_pence: int | None = Field(default=None, description="First-visit price agreed, if different")
    alerted: int = Field(default=0, description="How many providers the request was sent to")
    size_text: str | None = Field(
        default=None, description='Lawns: the size the customer chose, e.g. "Large (about 190 m²)"'
    )
    notes: str = ""
    simulating: bool = Field(default=False, description="DEMO_MODE: a simulation is running for this request")
    price_change: PriceChangeView | None = Field(default=None, description="A raised guide to approve or decline (A12)")


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
    provider_first_name: str = ""
    recurring: bool = False
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
    can_change_date: bool = Field(default=False, description="One-off visits not yet done")
    thread_id: str | None = None
    dispute_ref: str | None = None
    tip_pence: int = 0


class VisitsOut(BaseModel):
    next_visit: CustomerVisit | None
    upcoming: list[CustomerVisit]
    done: list[CustomerVisit]


class ChangeDateIn(In):
    preferred: list[date] = Field(min_length=1, max_length=3)
    note: str = Field(default="", max_length=500)


class FrequencyOption(BaseModel):
    value: str
    label: str = Field(description='e.g. "every 2 weeks"')


class PendingPlanChange(BaseModel):
    """A change of frequency waiting for the provider (A10). The plan is unchanged until then."""

    to_frequency: str
    to_frequency_label: str
    to_price_pence: int
    expires_at: datetime


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
    pending_change: PendingPlanChange | None = None
    frequency_options: list[FrequencyOption] = Field(
        default_factory=list, description="How often this plan can run (the category's options); empty if fixed"
    )


class PlanUpdate(In):
    """Change one or more plan settings. An away pause needs both dates; send both as null to clear it."""

    pause_winter: bool | None = None
    away_from: date | None = None
    away_to: date | None = None
    cover_when_away: bool | None = None
    frequency: (
        Literal[
            "weekly",
            "fortnightly",
            "threeweekly",
            "fourweekly",
            "eightweekly",
            "monthly",
            "threemonthly",
            "weekdays",
            "someweekdays",
        ]
        | None
    ) = Field(default=None, description="Asks the provider to accept the re-priced plan (A10); applied only if they do")


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
    tip_status: Literal["none", "charged", "failed", "pending"] = Field(
        description="pending: the gateway hasn't confirmed yet; the tip_reconcile task finishes it"
    )
    tip_message: str | None = Field(default=None, description="Why a tip couldn't be charged, to show as it is")


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
    address: Address | None = Field(
        default=None, description="From /api/address/{id}; needed when the customer has no saved address yet"
    )


class FeeExample(BaseModel):
    """The landing page's "Where your money goes" example, from app.core.money."""

    split: FeeSplit


class PlanPrice(BaseModel):
    """What the plan would cost at another frequency (A10), before asking the provider."""

    frequency: str
    frequency_label: str
    price_pence: int
    current_price_pence: int


class PlanChangeView(BaseModel):
    """The provider's page for a change of frequency (the link in their text)."""

    status: Literal["pending", "accepted", "declined", "lapsed", "withdrawn"]
    customer_first_name: str
    provider_first_name: str
    category_name: str
    area: str
    from_frequency_label: str
    to_frequency_label: str
    from_price_pence: int
    to_price_pence: int
    provider_pence: int = Field(description="What the provider keeps per visit at the new price (money.py)")
    expires_at: datetime


class PriceChangeAnswer(In):
    """The customer's answer to a raised guide (A12), naming the proposal they saw."""

    change_id: str = Field(min_length=1, max_length=64)
