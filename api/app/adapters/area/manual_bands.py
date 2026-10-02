"""manual_bands_v0: the customer picks a lawn size band, then nudges it.

Bands are from the build pack; the adjustment factors are the prototype's AREA_ADJ.
The Medium comparison was missing from the brief and is a ruling (decisions.md).
"""

from app.adapters.area.base import AreaAdjustment, AreaBand, AreaEstimateError, AreaInput, AreaOptions
from app.core.rounding import D, round_half_up
from app.models.common import Address
from app.models.quotes import Measure

BANDS = [
    AreaBand(id="small", label="Small", area_m2=40, comparison="About a double garage"),
    AreaBand(id="medium", label="Medium", area_m2=85, comparison="About a badminton court"),
    AreaBand(id="large", label="Large", area_m2=190, comparison="About a singles tennis court"),
    AreaBand(id="very_large", label="Very large", area_m2=350, comparison="Bigger than a doubles tennis court"),
]
ADJUSTMENTS = [
    AreaAdjustment(id="smaller", label="Looks smaller", factor=0.8),
    AreaAdjustment(id="right", label="About right", factor=1),
    AreaAdjustment(id="bigger", label="Looks bigger", factor=1.2),
]


class ManualBandsV0:
    id = "manual_bands_v0"

    async def options(self, address: Address | None) -> AreaOptions:
        return AreaOptions(
            estimator=self.id,
            bands=BANDS,
            adjustments=ADJUSTMENTS,
            tolerance_note="Your provider sees the same figure and can suggest a different price if it's off.",
        )

    async def estimate(self, address: Address | None, given: AreaInput) -> Measure:
        band = next((b for b in BANDS if b.id == given.band), None)
        if band is None:
            raise AreaEstimateError("Choose the size that's closest to your lawn")
        factor = next(a.factor for a in ADJUSTMENTS if a.id == given.adjust)
        area = round_half_up(D(band.area_m2) * D(factor))
        return Measure(estimator=self.id, area_m2=area, band=band.id, adjust=given.adjust)
