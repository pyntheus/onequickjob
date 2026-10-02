"""AreaEstimator: how big is the lawn?

v0 is manual_bands_v0 (the customer picks a size band). A LIDAR estimator can replace it
later without touching callers: the quote service only ever calls options() and
estimate(), and stores the returned Measure on the quote.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.models.common import Address
from app.models.quotes import Measure

Adjust = Literal["smaller", "right", "bigger"]


class AreaBand(BaseModel):
    id: str
    label: str
    area_m2: int
    comparison: str


class AreaAdjustment(BaseModel):
    id: Adjust
    label: str
    factor: float


class AreaOptions(BaseModel):
    """What the quote flow's lawn step shows. LIDAR would add measured lawns here."""

    estimator: str
    bands: list[AreaBand] = Field(default_factory=list)
    adjustments: list[AreaAdjustment]
    tolerance_note: str


class AreaInput(BaseModel):
    """What the customer told us on the lawn step."""

    band: str | None = None
    adjust: Adjust = "right"


class AreaEstimateError(ValueError):
    pass


class AreaEstimator(Protocol):
    id: str

    async def options(self, address: Address | None) -> AreaOptions: ...

    async def estimate(self, address: Address | None, given: AreaInput) -> Measure: ...
