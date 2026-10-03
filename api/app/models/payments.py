"""payment_events and payment_refunds: the payment gateway's records. Owner: L3.

payment_events logs every verified Stripe webhook by its event id, written in the same
transaction as the event's effects, so an event is applied at most once however often Stripe
sends it. payment_refunds holds each refund from the moment it's asked for: the intent is
recorded before the gateway is called and the result after, so a webhook arriving in between
(or a retry) never counts a refund twice.
"""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.common import Doc, Pence, Timestamped

RefundStatus = Literal["pending", "fee_pending", "succeeded", "failed"]


class PaymentEvent(Doc):
    """_id is the gateway's event id (evt_...)."""

    COLLECTION: ClassVar[str] = "payment_events"

    gateway: Literal["stripe"] = "stripe"
    type: str
    account: str | None = Field(default=None, description="Connected account the event came from, if any")
    object_id: str | None = None
    livemode: bool = False
    outcome: Literal["applied", "ignored", "no_match"] = "applied"
    note: str = ""
    received_at: datetime


class RefundIntent(Timestamped):
    """One refund of a visit's charge. Its id is the gateway idempotency key."""

    COLLECTION: ClassVar[str] = "payment_refunds"

    visit_id: str
    charge_id: str
    dispute_id: str | None = None
    gateway: Literal["fake", "stripe"]
    amount_pence: Pence
    fee_pence: Pence = Field(description="Our fee returned (money.refund_split, cumulative)")
    provider_pence: Pence = Field(description="What comes back out of the provider's earnings")
    reason: str
    requested_by: str | None = Field(default=None, description="Admin user id; None for the system")
    status: RefundStatus = "pending"
    refund_id: str | None = None
    failure_reason: str | None = None
    recorded_at: datetime | None = None
