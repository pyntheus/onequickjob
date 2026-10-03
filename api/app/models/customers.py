"""customers: one per user who books. Owner: L1."""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.common import Address, BookingSource, Model, Timestamped


class SavedCard(Model):
    brand: str
    last4: str
    exp_month: int
    exp_year: int


class CustomerPayment(Model):
    gateway: Literal["fake", "stripe"]
    gateway_customer_id: str | None = None
    setup_id: str | None = None
    setup_status: Literal["none", "pending", "succeeded", "failed"] = "none"
    card: SavedCard | None = None


class Customer(Timestamped):
    COLLECTION: ClassVar[str] = "customers"

    user_id: str
    name: str
    addresses: list[Address] = Field(default_factory=list)
    payment: CustomerPayment | None = None
    joined_via: BookingSource = Field(
        description="platform: found us; own_customer: invited by a provider. Drives the invite-only rule."
    )
    invited_by_provider_id: str | None = None
    terms_accepted_at: datetime | None = None
