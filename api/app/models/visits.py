"""visits: one occurrence of a booking. Owner: L2 (start, photos, finish). L3 writes
charge state from webhooks; L1 skips and reschedules.

The recorded times (minutes_actual against est_mins) and the "what was different"
flags are the calibration data for pricing. Never skip them.
"""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.common import BookingSource, IsoDate, Model, Pence, TimePref, Timestamped

VisitStatus = Literal["scheduled", "in_progress", "finished", "skipped", "cancelled"]
ChargeStatus = Literal["none", "pending", "succeeded", "requires_action", "failed", "refunded", "partially_refunded"]


class Performer(Model):
    """Who actually does the visit. Payment always goes to the booked provider."""

    kind: Literal["provider", "helper", "cover"] = "provider"
    provider_id: str
    user_id: str
    name: str


class Charge(Model):
    status: ChargeStatus = "none"
    amount_pence: Pence = 0
    fee_pence: Pence = 0
    provider_pence: Pence = 0
    gateway: Literal["fake", "stripe"] | None = None
    charge_id: str | None = None
    payment_intent_id: str | None = None
    idempotency_key: str | None = None
    charged_at: datetime | None = None
    failure_reason: str | None = None
    refunded_pence: Pence = 0
    refund_ids: list[str] = Field(default_factory=list)
    attempted_at: datetime | None = Field(
        default=None,
        description="When a request last claimed this charge to send it to the gateway (L2), so a pending "
        "charge is only ever sent by one request at a time",
    )


class Photos(Model):
    before: list[str] = Field(default_factory=list, description="File ids")
    after: list[str] = Field(default_factory=list)


class CoverState(Model):
    state: Literal["none", "offered", "covered"] = "none"
    request_id: str | None = Field(default=None, description="The cover request offered to other providers")
    original_provider_id: str | None = None


class Visit(Timestamped):
    COLLECTION: ClassVar[str] = "visits"

    booking_id: str
    series_id: str | None = None
    customer_id: str
    provider_id: str = Field(description="The booked provider, who is paid")
    performer: Performer
    category_id: str
    source: BookingSource
    local_date: IsoDate = Field(description="London date, for day and week queries")
    scheduled_start: datetime = Field(description="UTC")
    window: TimePref = "either"
    is_first: bool = False
    price_pence: Pence
    est_mins: int = Field(description="Estimate when booked: the calibration baseline")
    pricing_version_id: str | None = None
    status: VisitStatus = "scheduled"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    minutes_actual: int | None = None
    minutes_from_timer: bool = False
    flags: list[str] = Field(default_factory=list, description='"What was different", e.g. "Access was harder"')
    flags_none: bool = Field(default=False, description='Provider chose "Nothing, it was as described"')
    overrun: bool | None = Field(default=None, description="minutes_actual > est_mins x 1.1")
    over_25: bool | None = Field(default=None, description="minutes_actual > est_mins x 1.25")
    finish_note: str = ""
    photos: Photos = Field(default_factory=Photos)
    charge: Charge = Field(default_factory=Charge)
    tip_pence: Pence = 0
    tip_charge: Charge | None = None
    cover: CoverState = Field(default_factory=CoverState)
    rating_id: str | None = None
    dispute_id: str | None = None
    skipped_reason: str | None = None
