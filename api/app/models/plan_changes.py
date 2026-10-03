"""plan_changes: a customer's request to change how often a plan's visits happen. Owner: L1.

Ruling A10: the new frequency is re-priced from the pricing engine, keeping any counter the
provider negotiated in proportion, and the provider accepts or declines it. Until they accept,
the plan carries on unchanged; unanswered for 48 hours, the change lapses.
"""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.bookings import Frequency
from app.models.common import Pence, Timestamped

PlanChangeStatus = Literal["pending", "accepted", "declined", "lapsed", "withdrawn"]


class PlanChange(Timestamped):
    COLLECTION: ClassVar[str] = "plan_changes"

    series_id: str
    booking_id: str
    customer_id: str
    provider_id: str
    category_id: str
    from_frequency: Frequency
    to_frequency: Frequency
    from_price_pence: Pence = Field(description="The plan's price per visit when the change was asked for")
    to_price_pence: Pence = Field(
        description="new guide x agreed price / original guide, half-up to whole pounds (A10)"
    )
    new_guide_pence: Pence = Field(description="The engine's price at the new frequency (quote_id)")
    original_guide_pence: Pence = Field(
        description="The guide the agreed price was set against: the request's guide, or for an own customer's "
        "plan the engine's price at the current frequency (reference_quote_id)"
    )
    quote_id: str
    reference_quote_id: str | None = None
    status: PlanChangeStatus = "pending"
    token_hash: str = Field(description="HMAC of the token in the provider's link")
    requested_by: str = Field(description="Customer's user id")
    expires_at: datetime
    decided_at: datetime | None = None
