"""PaymentGateway: the only way any lane touches money movement.

Fake by default (app/adapters/payments/fake.py). L3 writes the Stripe implementation:
Connect Express accounts; a Customer on the PLATFORM with the card saved by a
SetupIntent; each visit charged off-session as a destination charge with on_behalf_of
the provider's account (the provider is the settlement merchant), transfer_data to that
account and application_fee_amount = the fee from app.core.money. Webhooks are the
source of truth for final states.

Every amount is integer pence. Callers compute fees with app.core.money, never here.
"""

from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class ProviderRef(BaseModel):
    provider_id: str
    name: str
    email: str | None = None
    phone: str | None = None


class CustomerRef(BaseModel):
    customer_id: str
    name: str
    email: str | None = None
    phone: str | None = None
    gateway_customer_id: str | None = Field(default=None, description="Reuse if we already created one")


class VisitRef(BaseModel):
    """What the gateway needs to know about the visit being charged."""

    visit_id: str
    booking_id: str
    customer_id: str
    gateway_customer_id: str
    description: str = Field(description='e.g. "Lawn mowing, Tuesday 13 October, Dave H."')


class ProviderAccount(BaseModel):
    account_id: str
    status: Literal["pending", "enabled", "restricted"]
    payouts_enabled: bool
    bank_last4: str | None = None
    requirements_due: list[str] = Field(default_factory=list)


class CardSetup(BaseModel):
    """Start of saving a card. With Stripe the browser confirms client_secret with Stripe.js."""

    gateway: Literal["fake", "stripe"]
    gateway_customer_id: str
    setup_id: str
    client_secret: str | None = None
    publishable_key: str | None = None
    status: Literal["requires_confirmation", "succeeded"]


class SavedCardInfo(BaseModel):
    brand: str
    last4: str
    exp_month: int
    exp_year: int


class CardSetupStatus(BaseModel):
    setup_id: str
    status: Literal["requires_confirmation", "processing", "succeeded", "failed"]
    card: SavedCardInfo | None = None
    failure_reason: str | None = None


class ChargeResult(BaseModel):
    status: Literal["succeeded", "pending", "requires_action", "failed"]
    charge_id: str | None = None
    payment_intent_id: str | None = None
    amount_pence: int
    fee_pence: int
    idempotency_key: str
    failure_reason: str | None = None
    failure_code: str | None = Field(
        default=None,
        description="The card network's or gateway's code, e.g. card_declined or authentication_required. "
        "Codes starting \"platform:\" mean the problem is ours or the provider's account, not the customer's "
        "card (L3 addition)",
    )
    created_at: datetime


PLATFORM_FAILURE = "platform:"


class RefundResult(BaseModel):
    """status is the customer's refund: succeeded; pending (the gateway is still processing it, or
    we couldn't tell, with refund_id None: repeat with the same key); failed (definitely not made).
    fee_refunded_pence is how much of our fee went back to the provider with it (L3)."""

    status: Literal["succeeded", "pending", "failed"]
    refund_id: str | None = None
    amount_pence: int
    fee_refunded_pence: int
    failure_reason: str | None = None


class TransferResult(BaseModel):
    """Money sent back to a provider's account (L3 addition): status succeeded; pending (unknown:
    repeat with the same key); failed."""

    status: Literal["succeeded", "pending", "failed"]
    transfer_id: str | None = None
    amount_pence: int
    failure_reason: str | None = None


class Payout(BaseModel):
    payout_id: str
    arrival_date: date
    amount_pence: int
    status: Literal["paid", "in_transit", "pending", "failed"]
    bank_last4: str | None = None


class PayoutSummary(BaseModel):
    account_id: str
    payouts: list[Payout]
    pending_pence: int = Field(description="Charged but not yet paid out")
    next_payout_date: date | None = None


class PaymentGateway(Protocol):
    name: Literal["fake", "stripe"]

    async def create_provider_account(self, provider: ProviderRef) -> ProviderAccount: ...

    async def onboarding_link(self, account_id: str, *, return_url: str, refresh_url: str) -> str: ...

    async def account_status(self, account_id: str) -> ProviderAccount: ...

    async def save_card_setup(self, customer: CustomerRef) -> CardSetup: ...

    async def card_setup_status(self, setup_id: str) -> CardSetupStatus: ...

    async def charge_visit(
        self,
        visit: VisitRef,
        price_pence: int,
        fee_pence: int,
        provider_account: str,
        *,
        idempotency_key: str | None = None,
        purpose: Literal["visit", "tip"] = "visit",
    ) -> ChargeResult:
        """Charge the customer's saved card off-session for one visit (or its tip).
        The idempotency key defaults to f"visit:{visit_id}:{purpose}"."""
        ...

    async def refund(
        self,
        charge_id: str,
        amount_pence: int,
        fee_refund_pence: int,
        *,
        reason: str,
        idempotency_key: str | None = None,
    ) -> RefundResult:
        """Refund part or all of a charge, reversing the transfer (the provider funds it), and once
        the customer's refund has succeeded return exactly fee_refund_pence of our fee (from
        money.refund_split). With an idempotency_key, repeating the call returns the same refund
        (L3 addition); never repeat it once the refund id is known: use refund_status."""
        ...

    async def refund_status(self, refund_id: str) -> RefundResult:
        """Where a refund stands now (fee_refunded_pence 0: the fee is a separate step) (L3 addition)."""
        ...

    async def refund_fee(self, charge_id: str, fee_refund_pence: int, *, idempotency_key: str) -> RefundResult:
        """Return fee_refund_pence of our fee on a charge to the provider: the fee part of a refund
        whose customer refund has succeeded. status is this step's (L3 addition)."""
        ...

    async def charge_status(self, payment_intent_id: str) -> ChargeResult:
        """Where a charge attempt stands now, e.g. before retrying it (L3 addition)."""
        ...

    async def find_charge(self, idempotency_key: str, gateway_customer_id: str) -> ChargeResult | None:
        """The payment an attempt made, looked up by its idempotency key, or None if the request
        never reached the gateway. A read: recovering an unknown outcome never repeats a charge
        (L3 addition)."""
        ...

    async def cancel_charge(self, payment_intent_id: str) -> ChargeResult:
        """Cancel an attempt that hasn't succeeded (one waiting for the customer to confirm),
        so a retry can't leave two payments open. Returns the attempt's state afterwards:
        succeeded if it had already gone through (L3 addition)."""
        ...

    async def restore_transfer(self, charge_id: str, amount_pence: int, *, idempotency_key: str) -> TransferResult:
        """Give a provider back what a failed refund's transfer reversal took (a failed refund's
        money returns to the platform, not the provider) (L3 addition)."""
        ...

    async def payout_summary(self, provider_account: str, *, limit: int = 8) -> PayoutSummary: ...
