"""The pricing engine: category + answers + params (+ lawn area) -> Estimate.

Pure: no database, no clock. app.services.quotes loads the live pricing version and
the area estimate, calls price(), and records the version on the quote.
"""

from typing import Any

from app.models.categories import Category
from app.pricing.answers import validate_answers
from app.pricing.models import PRICING_MODELS, Estimate


class PricingError(ValueError):
    pass


def price(category: Category, answers: dict[str, Any], params: dict[str, Any], area_m2: int | None = None) -> Estimate:
    """Price validated or raw answers. Raises AnswerError for bad answers, PricingError otherwise."""
    if category.status != "live":
        raise PricingError(f"{category.name} isn't something we book")
    model = PRICING_MODELS.get(category.pricing_model)
    if model is None:
        raise PricingError(f"no pricing model {category.pricing_model!r}")
    full = validate_answers(category, answers)
    if category.measure == "lawn":
        if area_m2 is None or area_m2 <= 0:
            raise PricingError("a lawn area is needed to price mowing")
        full = {**full, "area": area_m2}
    return model(full, params)


def params_for(version_params: dict[str, dict[str, Any]], category_id: str) -> dict[str, Any]:
    try:
        return version_params[category_id]
    except KeyError as e:
        raise PricingError(f"the live pricing version has no params for {category_id}") from e
