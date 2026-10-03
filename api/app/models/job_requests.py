"""job_requests: a customer's priced job, broadcast to eligible providers. Owner: L1.

State machine in docs/spec/state-machines.md. The open -> booked transition is atomic
(app.services.marketplace.claim_request: findOneAndUpdate on status == open), so the
first provider to accept the guide price, or the customer accepting a counter, wins.
"""

from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import Field

from app.models.common import Address, DaysPref, GeoPoint, Model, Pence, TimePref, Timestamped
from app.models.quotes import Measure, Unit

RequestStatus = Literal["open", "booked", "cancelled", "expired"]
EventKind = Literal[
    "created",
    "broadcast",
    "viewed",
    "countered",
    "counter_declined",
    "counter_lapsed",
    "accepted",
    "guide_raised",
    "price_change_proposed",
    "price_change_declined",
    "cancelled",
    "expired",
    "note",
]


class When(Model):
    days: DaysPref = "any"
    time: TimePref = "either"


class RequestEvent(Model):
    """The customer's "What's happened so far" timeline, and admin history."""

    at: datetime
    kind: EventKind
    provider_id: str | None = None
    offer_id: str | None = None
    price_pence: Pence | None = None
    count: int | None = Field(default=None, description="broadcast: how many providers were alerted")
    by_user_id: str | None = None
    text: str | None = None


class Broadcast(Model):
    at: datetime
    provider_ids: list[str]
    rule: str = Field(default="eligible_v1", description="Eligibility rule that chose them")


class Booked(Model):
    """The terms agreed at the atomic claim, and the booking made in the same transaction."""

    booking_id: str
    provider_id: str
    price_pence: Pence
    first_price_pence: Pence | None = Field(default=None, description="First-visit price, if different")
    via: Literal["guide", "counter"]
    offer_id: str | None = None
    at: datetime


class PriceChange(Model):
    """A raised guide price waiting for the customer's approval (ruling A12). Only on approval
    does the request's guide change and its job alerts go out again."""

    status: Literal["pending", "approved", "declined"] = "pending"
    guide_pence: Pence
    first_pence: Pence | None = Field(default=None, description="Scaled by the same ratio (scaled_first_price)")
    from_guide_pence: Pence
    from_first_pence: Pence | None = None
    percent: int | None = None
    proposed_by: str | None = Field(default=None, description="Admin user id")
    proposed_at: datetime
    decided_at: datetime | None = None
    note: str = ""


class JobRequest(Timestamped):
    COLLECTION: ClassVar[str] = "job_requests"

    ref: str = Field(description="Human reference, e.g. R-2291. Used in job links /p/j/{ref}")
    customer_id: str
    category_id: str
    quote_id: str
    pricing_version_id: str
    answers: dict[str, Any]
    measure: Measure | None = None
    address: Address = Field(description="Exact address: shown to the provider only once booked")
    approx: GeoPoint = Field(description="About 1 km resolution, for the provider's approximate map")
    notes: str = ""
    when: When = Field(default_factory=When)
    recurring: bool = False
    frequency: str | None = None
    guide_pence: Pence
    first_pence: Pence | None = None
    mins: int
    first_mins: int | None = None
    unit: Unit
    photos: list[str] = Field(default_factory=list, description="File ids")
    status: RequestStatus = "open"
    broadcast: Broadcast | None = None
    viewed_by: list[str] = Field(default_factory=list, description="Provider ids who opened it")
    events: list[RequestEvent] = Field(default_factory=list)
    booked: Booked | None = None
    direct_provider_id: str | None = Field(default=None, description="Book again: offered to this provider only")
    cover_for_visit_id: str | None = Field(
        default=None,
        description="Time-off cover (L2 creates): accepting reassigns this one visit instead of creating a booking",
    )
    admin_note: str | None = None
    price_change: PriceChange | None = Field(default=None, description="A raised guide awaiting the customer (A12)")
