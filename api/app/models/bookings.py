"""bookings and series. Owner: F creates them (marketplace core); L1 changes plans,
L2 creates own-customer bookings through app.services.bookings.

A booking is the agreement between the customer and the named provider (we are their
booking and payment agent). source decides the fee: platform -> standard 15%,
own_customer -> 5% with a 100p minimum (app.core.money).
"""

from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import Field

from app.models.common import Address, BookingSource, IsoDate, Model, Pence, TimePref, Timestamped, Weekday
from app.models.quotes import Unit

Frequency = Literal[
    "oneoff",
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


class Booking(Timestamped):
    COLLECTION: ClassVar[str] = "bookings"

    ref: str = Field(description="Human reference, e.g. B-1104")
    source: BookingSource
    customer_id: str
    provider_id: str
    category_id: str
    request_id: str | None = None
    invite_id: str | None = None
    via: Literal["guide", "counter", "invite", "direct"]
    price_pence: Pence = Field(description="Agreed price per visit")
    first_price_pence: Pence | None = Field(default=None, description="First-visit price, if different")
    unit: Unit
    recurring: bool
    frequency: Frequency
    series_id: str | None = None
    address: Address
    answers: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    when: TimePref = "either"
    thread_id: str | None = None
    status: Literal["active", "completed", "cancelled"] = "active"
    cancelled_at: datetime | None = None


class Pause(Model):
    winter: bool = Field(default=False, description="Outside jobs: no visits November to February")
    away_from: IsoDate | None = None
    away_to: IsoDate | None = None


class Series(Timestamped):
    """A recurring plan. Visits are materialised a few weeks ahead (services.schedule)."""

    COLLECTION: ClassVar[str] = "series"

    booking_id: str
    customer_id: str
    provider_id: str
    category_id: str
    frequency: Frequency
    days: list[Weekday] = Field(description="Weekdays visits fall on (several for dog walks)")
    start_time: str = Field(description='London wall-clock "HH:MM"')
    anchor_date: IsoDate = Field(description="First visit date; intervals count from here")
    price_pence: Pence
    est_mins: int = Field(description="Estimated minutes for a routine visit")
    window: TimePref = "either"
    status: Literal["active", "paused", "cancelled"] = "active"
    pause: Pause = Field(default_factory=Pause)
    cover_when_away: bool = True
    horizon_until: IsoDate | None = Field(default=None, description="Visits exist up to this date")
