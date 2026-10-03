from app.adapters.area.base import AreaEstimator
from app.adapters.area.manual_bands import ManualBandsV0
from app.core.config import Settings


def make_area_estimator(settings: Settings) -> AreaEstimator:
    match settings.area_estimator:
        case "manual_bands_v0":
            return ManualBandsV0()
    raise ValueError(f"unknown AREA_ESTIMATOR {settings.area_estimator!r}")  # pragma: no cover
