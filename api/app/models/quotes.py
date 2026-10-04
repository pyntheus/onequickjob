"""quotes: every priced estimate, with the pricing version it used. Owner: F (L1 reads)."""

from typing import Any, ClassVar, Literal

from pydantic import Field

from app.models.common import Address, Model, Pence, Timestamped

Confidence = Literal["high", "medium", "low"]
Unit = Literal["a visit", "one-off", "a clean", "a walk"]


class MeasuredLawn(Model):
    """One lawn the customer paced out or measured (decisions.md A26)."""

    length: float = Field(description="As the customer gave it, in the measure's unit")
    width: float = Field(description="As the customer gave it, in the measure's unit")
    length_m: float
    width_m: float
    area_m2: int = Field(description="length_m x width_m, rounded half-up to whole m²")


class Measure(Model):
    """How the lawn area was worked out. Only for categories with measure == lawn."""

    estimator: str = Field(description="AreaEstimator id: manual_bands_v0 or customer_measured_v0")
    method: Literal["band", "paced", "measured"] = Field(
        default="band",
        description="How the customer sized the lawn: picked a size band, paced it out, or gave its length and width",
    )
    area_m2: int = Field(description="What the engine prices: the band's area, or the lawns' areas summed")
    confidence: Literal["high", "medium", "low"] | None = Field(
        default=None, description="How sure the estimator is; becomes the quote's confidence"
    )
    band: str | None = None
    adjust: Literal["smaller", "right", "bigger"] | None = None
    unit: Literal["strides", "m", "ft"] | None = Field(
        default=None, description="paced: strides (a big stride counts as a metre); measured: m or ft"
    )
    lawns: list[MeasuredLawn] = Field(default_factory=list, description="paced and measured: each lawn, as given")
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
