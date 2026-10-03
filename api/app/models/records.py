"""ledger_entries, mileage_logs, expenses: the provider's money records. Owner: L2
(L3 writes refund entries). The tax pack and the HMRC export derive from these.
"""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.common import BookingSource, IsoDate, Model, Pence, SignedPence, Timestamped


class LedgerEntry(Timestamped):
    """One charge entry per charged visit (unique on visit_id + kind=charge), plus tip,
    refund and adjustment entries. gross = what the customer paid, fee = ours,
    net = what the provider receives; gross == fee + net always."""

    COLLECTION: ClassVar[str] = "ledger_entries"

    provider_id: str
    customer_id: str
    visit_id: str | None
    booking_id: str | None
    kind: Literal["charge", "tip", "refund", "adjustment"]
    source: BookingSource
    gross_pence: SignedPence
    fee_pence: SignedPence
    net_pence: SignedPence
    occurred_at: datetime = Field(description="When the money moved (UTC)")
    local_date: IsoDate = Field(description="London date of occurred_at")
    tax_year: str = Field(description='UK tax year, e.g. "2026-27"')
    gateway: Literal["fake", "stripe"]
    gateway_ref: str | None = Field(default=None, description="Charge or refund id at the gateway")


class MileageLeg(Model):
    from_label: str
    to_label: str
    straight_miles: float
    road_miles: float


class MileageLog(Timestamped):
    """One per provider per working day: home -> job -> job -> home, straight line x 1.25."""

    COLLECTION: ClassVar[str] = "mileage_logs"

    provider_id: str
    local_date: IsoDate
    tax_year: str
    legs: list[MileageLeg]
    miles: float = Field(description="Road miles, one decimal place")
    rate_pence_per_mile: int = 45
    amount_pence: Pence
    method: Literal["calculated_estimate", "manual"] = "calculated_estimate"
    visit_ids: list[str] = Field(default_factory=list)


class Expense(Timestamped):
    COLLECTION: ClassVar[str] = "expenses"

    provider_id: str
    local_date: IsoDate
    tax_year: str
    description: str
    category: Literal["kit", "supplies", "fuel", "other"] = "kit"
    amount_pence: Pence
    receipt_file_id: str | None = None
