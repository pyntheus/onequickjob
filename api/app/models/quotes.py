"""quotes: every priced estimate, with the pricing version it used. Owner: F (L1 reads)."""

from typing import Any, ClassVar, Literal

from pydantic import Field

from app.models.common import Address, Model, Pence, Timestamped

Confidence = Literal["high", "medium", "low"]
Unit = Literal["a visit", "one-off", "a clean", "a walk"]


class Measure(Model):
    """How the lawn area was worked out. Only for categories with measure == lawn."""

    estimator: str = Field(description="AreaEstimator id, e.g. manual_bands_v0")
    area_m2: int
    band: str | None = None
    adjust: Literal["smaller", "right", "bigger"] | None = None
    detail: dict[str, Any] | None = Field(default=None, description="Estimator-specific, e.g. LIDAR polygons")


class FeeSplit(Model):
    """What the customer pays, our fee and what the provider gets. From money.py only."""

    mode: Literal["standard", "own_customer", "tip"]
    rate_percent: int
    price_pence: Pence
    fee_pence: Pence
    provider_pence: Pence


class QuoteResult(Model):
    price_pence: Pence
    first_pence: Pence | None = None
    first_reason: str | None = None
    mins: int
    first_mins: int | None = None
    low_pence: Pence
    high_pence: Pence
    spread: tuple[float, float]
    confidence: Confidence
    unit: Unit
    note: str | None = None
    conf_note: str | None = None


class Quote(Timestamped):
    COLLECTION: ClassVar[str] = "quotes"

    category_id: str
    answers: dict[str, Any] = Field(description="Validated answers with defaults filled in")
    measure: Measure | None = None
    address: Address | None = None
    pricing_version_id: str
    pricing_version: int
    result: QuoteResult
    fee: FeeSplit
    first_fee: FeeSplit | None = None
    user_id: str | None = Field(default=None, description="Set if the visitor was signed in")
    request_id: str | None = Field(default=None, description="Set when the quote becomes a job request")
