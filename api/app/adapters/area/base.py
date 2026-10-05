"""AreaEstimator: how big is the lawn?

The lawn step offers three ways to one area (decisions.md A26): pick a size band
(manual_bands_v0), pace the lawn out, or give its length and width (both
customer_measured_v0). A LIDAR estimator can join or replace them later without touching
callers: the quote service only ever calls options() and estimate(), and stores the
returned Measure on the quote.
"""

from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import Address
from app.models.quotes import Measure

Adjust = Literal["smaller", "right", "bigger"]
Method = Literal["band", "paced", "measured"]
LengthUnit = Literal["m", "ft"]


class AreaBand(BaseModel):
    id: str
    label: str
    area_m2: int = Field(description="The area the engine prices for this band")
    comparison: str = Field(description='The band in words: "About 5 × 8 metres (40 m²). Nearly 2 car lengths ..."')
    width_m: float = Field(description="The drawing's lawn: its short side")
    length_m: float = Field(description="The drawing's lawn: its long side")
    house: bool = Field(default=False, description="Draw a house beside the lawn, for scale")


class AreaAdjustment(BaseModel):
    id: Adjust
    label: str
    factor: float


class AreaLimits(BaseModel):
    """What the customer's own figures must be (paced and measured)."""

    side_min_m: int
    side_max_m: int
    total_min_m2: int
    total_max_m2: int
    max_lawns: int


class AreaOptions(BaseModel):
    """What the quote flow's lawn step shows. LIDAR would add measured lawns here."""

    estimator: str
    confidence: Literal["high", "medium", "low"] = Field(description="The confidence quotes from this estimator get")
    methods: list[Method] = Field(default_factory=lambda: ["band"], description="The ways offered, in order")
    bands: list[AreaBand] = Field(default_factory=list)
    adjustments: list[AreaAdjustment] = Field(default_factory=list, description="The nudges, for bands only")
    limits: AreaLimits | None = Field(default=None, description="For paced and measured lawns")
    tolerance_note: str


class LawnSides(BaseModel):
    """One lawn's sides as the customer gave them: whole strides (paced), or metres or feet
    (measured). Sent as numbers or strings ("7.5"), so decimals arrive exactly."""

    model_config = ConfigDict(extra="forbid")

    length: Decimal = Field(ge=0, le=10_000)
    width: Decimal = Field(ge=0, le=10_000)


class AreaInput(BaseModel):
    """What the customer told us on the lawn step."""

    model_config = ConfigDict(extra="forbid")

    method: Method = Field(default="band", description="band: a size band; paced: strides; measured: length x width")
    band: str | None = None
    adjust: Adjust = "right"
    unit: LengthUnit = Field(default="m", description="measured only: what the sides are in (paced is in strides)")
    lawns: list[LawnSides] = Field(
        default_factory=list, max_length=4, description="paced and measured: each lawn (front, back...), summed"
    )


class AreaEstimateError(ValueError):
    """The lawn step's answer can't give an area. The message is shown to the customer."""

    def __init__(self, message: str, code: str = "lawn_size_needed", **extra: object):
        super().__init__(message)
        self.code = code
        self.extra = extra


class AreaEstimator(Protocol):
    """Estimators own the confidence of lawn quotes: estimate() returns a Measure whose
    confidence becomes the quote's (bands and the customer's own figures: medium; a
    measured estimator such as LIDAR may say high)."""

    id: str

    async def options(self, address: Address | None) -> AreaOptions: ...

    async def estimate(self, address: Address | None, given: AreaInput) -> Measure: ...


def input_for(measure: Measure, default_band: str) -> AreaInput:
    """The lawn step's answer that gives this measure again: a re-price (A10) sizes the lawn
    exactly as the customer did. A measure with no band on record takes default_band."""
    if measure.method == "band" or not measure.lawns:
        return AreaInput(band=measure.band or default_band, adjust=measure.adjust or "right")
    return AreaInput(
        method=measure.method,
        unit="ft" if measure.unit == "ft" else "m",
        # Floats as stored go back through repr, so 9.14 is Decimal("9.14") again.
        lawns=[LawnSides(length=Decimal(repr(lw.length)), width=Decimal(repr(lw.width))) for lw in measure.lawns],
    )
