"""Quote pricing: live pricing version + area estimate + engine + fee split -> stored quote."""

from typing import Any

from fastapi import status

from app.adapters.area import make_area_estimator
from app.adapters.area.base import AreaEstimateError, AreaInput
from app.core import money
from app.core.config import Settings
from app.core.db import Db, DbSession
from app.core.errors import fail
from app.models.categories import Category
from app.models.common import Address
from app.models.pricing_versions import PricingVersion
from app.models.quotes import FeeSplit, Measure, Quote, QuoteResult
from app.pricing.answers import AnswerError, has_empty_counts, validate_answers
from app.pricing.engine import PricingError, params_for, price
from app.repos.categories import Categories
from app.repos.pricing_versions import PricingVersions
from app.repos.quotes import Quotes

CONFIDENCE_COPY = {
    "high": ("Usually close", "Most providers accept prices like this as they are."),
    "medium": ("Fairly close", "Some providers adjust the price once they see the details."),
    "low": (
        "A rough starting point",
        "Jobs like this vary a lot. Most providers will look at your photos or description and suggest their "
        "own price.",
    ),
}
CONFIDENCE_BARS = {"high": 3, "medium": 2, "low": 1}


def fee_split(price_pence: int, mode: money.FeeMode = "standard", settings: Settings | None = None) -> FeeSplit:
    sp = money.split(price_pence, mode, settings)
    return FeeSplit(
        mode=sp.mode,
        rate_percent=sp.rate_percent,
        price_pence=sp.price_pence,
        fee_pence=sp.fee_pence,
        provider_pence=sp.provider_pence,
    )


async def live_version(db: Db, *, session: DbSession | None = None) -> PricingVersion:
    v = await PricingVersions(db).live(session=session)
    if v is None:
        fail(status.HTTP_503_SERVICE_UNAVAILABLE, "no_live_pricing", "Prices aren't available right now.")
    return v


async def bookable_category(db: Db, category_id: str, *, session: DbSession | None = None) -> Category:
    cat = await Categories(db).get(category_id, session=session)
    if cat is None:
        fail(status.HTTP_404_NOT_FOUND, "unknown_category", "We don't know that kind of job.")
    if cat.status != "live":
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_bookable", f"{cat.name} isn't something we book yet.")
    return cat


async def create_quote(
    db: Db,
    s: Settings,
    *,
    category_id: str,
    answers: dict[str, Any],
    lawn: AreaInput | None,
    address: Address | None,
    user_id: str | None,
    session: DbSession | None = None,
) -> Quote:
    cat = await bookable_category(db, category_id, session=session)
    version = await live_version(db, session=session)
    measure: Measure | None = None
    if cat.measure == "lawn":
        if lawn is None:
            fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "lawn_size_needed", "Tell us roughly how big the lawn is.")
        try:
            measure = await make_area_estimator(s).estimate(address, lawn)
        except AreaEstimateError as e:
            fail(status.HTTP_422_UNPROCESSABLE_CONTENT, e.code, str(e), **e.extra)
    try:
        full = validate_answers(cat, answers)
        if has_empty_counts(cat, full):
            fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "nothing_to_price", "Add at least one item to see a price.")
        est = price(
            cat,
            full,
            params_for(version.params, cat.id),
            measure.area_m2 if measure else None,
            measure.confidence if measure else None,
        )
        if est.confidence is None:
            raise PricingError("the area estimator gave no confidence")
    except AnswerError as e:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_answer", e.message, key=e.key)
    except PricingError as e:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "cannot_price", str(e))

    quote = Quote(
        category_id=cat.id,
        answers=full,
        measure=measure,
        address=address,
        pricing_version_id=version.id,
        pricing_version=version.version,
        result=QuoteResult(
            price_pence=est.price_pence,
            first_pence=est.first_pence,
            first_reason=est.first_reason,
            mins=est.mins,
            first_mins=est.first_mins,
            low_pence=est.low_pence,
            high_pence=est.high_pence,
            spread=(float(est.spread[0]), float(est.spread[1])),
            confidence=est.confidence,
            unit=est.unit,
            note=est.note,
            conf_note=est.conf_note,
        ),
        fee=fee_split(est.price_pence, settings=s),
        first_fee=fee_split(est.first_pence, settings=s) if est.first_pence is not None else None,
        user_id=user_id,
    )
    await Quotes(db).insert(quote, session=session)
    return quote
