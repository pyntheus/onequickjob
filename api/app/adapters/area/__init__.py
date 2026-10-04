from app.adapters.area.base import AreaEstimator, AreaInput, AreaOptions
from app.adapters.area.customer_measured import CustomerMeasuredV0
from app.adapters.area.manual_bands import ManualBandsV0
from app.core.config import Settings
from app.models.common import Address
from app.models.quotes import Measure


class ThreeWays:
    """The lawn step's three ways to one area (decisions.md A26): a size band from one
    estimator, paced out or measured from the other. Callers see a single AreaEstimator; each
    Measure names the estimator that made it."""

    id = "three_ways_v0"

    def __init__(self, bands: AreaEstimator, measured: AreaEstimator):
        self.bands, self.measured = bands, measured

    async def options(self, address: Address | None) -> AreaOptions:
        b, m = await self.bands.options(address), await self.measured.options(address)
        return b.model_copy(update={"estimator": self.id, "methods": [*b.methods, *m.methods], "limits": m.limits})

    async def estimate(self, address: Address | None, given: AreaInput) -> Measure:
        return await (self.bands if given.method == "band" else self.measured).estimate(address, given)


def make_area_estimator(settings: Settings) -> AreaEstimator:
    match settings.area_estimator:
        case "manual_bands_v0":
            # Size bands, with the customer's own strides or measurements alongside.
            return ThreeWays(ManualBandsV0(), CustomerMeasuredV0())
    raise ValueError(f"unknown AREA_ESTIMATOR {settings.area_estimator!r}")  # pragma: no cover
