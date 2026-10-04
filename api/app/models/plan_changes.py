"""plan_changes: a customer's request to change how often a plan's visits happen. Owner: L1.

Ruling A10 (kind reprice, a platform plan): the new frequency is re-priced from the pricing engine,
keeping any counter the provider negotiated in proportion, and the provider accepts or declines it.
Ruling A22 (kind provider_price, an own customer's plan): the price is the provider's to set, so the
provider names the new price (or declines) and then the customer approves or declines it. Either
way the plan carries on unchanged until the change is agreed, and each wait lapses after 48 hours.
While a change is open its status is pending; `awaiting` says whose answer it waits for.
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
    kind: Literal["reprice", "provider_price"] = Field(
        default="reprice",
        description="reprice: priced by the engine, the provider accepts (A10); provider_price: an own customer's "
        "plan, the provider names the price and the customer approves (A22)",
    )
    to_price_pence: Pence | None = Field(
        description="A10: new guide x agreed price / original guide, half-up to whole pounds. A22: the provider's "
        "price, once they've named it"
    )
    new_guide_pence: Pence | None = Field(default=None, description="A10: the engine's price at the new frequency")
    original_guide_pence: Pence | None = Field(
        default=None, description="A10: the guide the agreed price was set against (the request's guide)"
    )
    quote_id: str | None = Field(default=None, description="A10: the quote for the new frequency")
    reference_quote_id: str | None = None
    status: PlanChangeStatus = "pending"
    awaiting: Literal["provider", "customer"] = Field(
        default="provider", description="While pending: whose answer it waits for (the customer's only under A22)"
    )
    declined_by: Literal["provider", "customer"] | None = None
    token_hash: str = Field(description="HMAC of the token in the provider's link")
    requested_by: str = Field(description="Customer's user id")
    expires_at: datetime = Field(description="When the current wait lapses (48 hours from its start)")
    priced_at: datetime | None = Field(default=None, description="A22: when the provider named the price")
    decided_at: datetime | None = None
