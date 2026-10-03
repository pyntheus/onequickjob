"""payment_events, payment_refunds and payment_attempts: the payment gateway's records. Owner: L3.

payment_events logs every verified Stripe webhook by its event id, written in the same
transaction as the event's effects, so an event is applied at most once however often Stripe
sends it. A refund event that arrives before its charge is recorded is kept (with its payload)
and replayed when the charge is. payment_refunds holds each refund from the moment it's asked
for: the intent is recorded before the gateway is called and the result after, so a webhook
arriving in between (or a retry) never counts a refund twice. payment_attempts records when each
charge attempt (idempotency key) began, so automatic retries stop before Stripe forgets the key.
"""

from datetime import datetime
from typing import Any, ClassVar, Literal

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
    outcome: Literal["applied", "ignored", "no_match", "deferred"] = "applied"
    note: str = ""
    received_at: datetime
    payment_intent: str | None = Field(default=None, description="For deferred refund events: the charge's intent")
    payload: dict[str, Any] | None = Field(default=None, description="The event's object, kept only while deferred")


class RefundIntent(Timestamped):
    """One refund of a visit's charge. Its id is the gateway idempotency key (and `<id>:fee` the
    fee refund's). status: pending (the customer's refund isn't confirmed yet, so nothing is
    recorded and the amount stays reserved), fee_pending (the customer's refund is confirmed and
    recorded; returning our fee to the provider still needs doing), succeeded, failed."""

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
    restore: Literal["none", "needed", "done"] = Field(
        default="none",
        description="A refund that failed after it was made: its transfer reversal took the provider's money, "
        "which a failed refund returns to the platform, so it's transferred back (needed until done)",
    )
    restore_transfer_id: str | None = None


class ChargeAttempt(Doc):
    """When a charge attempt began. _id is its idempotency key (visit:<id>:visit[:retryN])."""

    COLLECTION: ClassVar[str] = "payment_attempts"

    visit_id: str
    purpose: Literal["visit", "tip"]
    created_at: datetime
