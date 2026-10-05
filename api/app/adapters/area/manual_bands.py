"""manual_bands_v0: the customer picks a lawn size band, then nudges it.

The bands' areas are the build pack's; their wording compares them with cars (decisions.md
A26: tennis courts were too close to each other to anchor two bands, and people picture the
whole fenced court). The adjustment factors are the prototype's AREA_ADJ.
"""

from app.adapters.area.base import AreaAdjustment, AreaBand, AreaEstimateError, AreaInput, AreaOptions
from app.core.rounding import D, round_half_up
from app.models.common import Address
from app.models.quotes import Measure

BANDS = [
    AreaBand(
        id="small",
        label="Small",
        area_m2=40,
        comparison="About 5 × 8 metres (40 m²). Nearly 2 car lengths long and 1 wide.",
        width_m=5,
        length_m=8,
    ),
    AreaBand(
        id="medium",
        label="Medium",
        area_m2=85,
        comparison="About 7 × 12 metres (85 m²). Nearly 3 car lengths long and 1½ wide.",
        width_m=7,
        length_m=12,
    ),
    AreaBand(
        id="large",
        label="Large",
        area_m2=190,
        comparison="About 10 × 19 metres (190 m²). 4 car lengths long and 2 wide.",
        width_m=10,
        length_m=19,
        house=True,
    ),
    AreaBand(
        id="very_large",
        label="Very large",
        area_m2=350,
        comparison="About 15 × 23 metres (350 m²). 5 car lengths long and 3 wide.",
        width_m=15,
        length_m=23,
        house=True,
    ),
]
ADJUSTMENTS = [
    AreaAdjustment(id="smaller", label="Looks smaller", factor=0.8),
    AreaAdjustment(id="right", label="About right", factor=1),
    AreaAdjustment(id="bigger", label="Looks bigger", factor=1.2),
]
TOLERANCE_NOTE = "Your provider sees the same figure and can suggest a different price if it's off."


class ManualBandsV0:
    id = "manual_bands_v0"
    # The customer picked a size band, so the price is "Fairly close", not "Usually close".
    confidence = "medium"

    async def options(self, address: Address | None) -> AreaOptions:
        return AreaOptions(
            estimator=self.id,
            confidence=self.confidence,
            methods=["band"],
            bands=BANDS,
            adjustments=ADJUSTMENTS,
            tolerance_note=TOLERANCE_NOTE,
        )

    async def estimate(self, address: Address | None, given: AreaInput) -> Measure:
        band = next((b for b in BANDS if b.id == given.band), None)
        if band is None:
            raise AreaEstimateError("Choose the size that's closest to your lawn")
        factor = next(a.factor for a in ADJUSTMENTS if a.id == given.adjust)
        area = round_half_up(D(band.area_m2) * D(factor))
        return Measure(
            estimator=self.id,
            method="band",
            area_m2=area,
            band=band.id,
            adjust=given.adjust,
            confidence=self.confidence,
        )
