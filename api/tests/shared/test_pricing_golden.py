"""GOLDEN TESTS (decisions.md): each category's default answers, 186 m² for mowing.
These numbers are fixed. If a change makes one fail, the change is wrong."""

import pytest

from app.pricing.answers import defaults_for
from app.pricing.engine import price
from tests.catalogue_fixtures import categories, pricing_v1_params

GOLDEN = {
    # category: (price_pence, first_pence, unit)
    "mowing": (3000, None, "a visit"),
    "hedges": (6100, None, "one-off"),
    "clearance": (11000, None, "one-off"),
    "jetwash": (8800, None, "one-off"),
    "gutters": (8500, None, "one-off"),
    "windows": (2200, 3300, "a clean"),
    "cleaning": (6600, 8800, "a clean"),
    "deepclean": (20400, None, "one-off"),
    "oven": (7000, None, "one-off"),
    "decorating": (18200, None, "one-off"),
    "flatpack": (13300, None, "one-off"),
    "mounting": (11000, None, "one-off"),
    "repairs": (6000, None, "one-off"),
    "techhelp": (2500, None, "one-off"),
    "dogwalking": (1600, None, "a walk"),
}


def test_every_live_category_has_a_golden_value():
    assert set(GOLDEN) == {c.id for c in categories().values() if c.status == "live"}
    assert len(GOLDEN) == 15


@pytest.mark.parametrize(("category_id", "expected"), GOLDEN.items())
def test_golden_price_with_default_answers(category_id, expected):
    cat = categories()[category_id]
    params = pricing_v1_params()[category_id]
    area = 186 if cat.measure == "lawn" else None
    est = price(cat, defaults_for(cat), params, area)
    price_pence, first_pence, unit = expected
    assert est.price_pence == price_pence
    assert est.first_pence == first_pence
    assert est.unit == unit


def test_mowing_large_band_is_31_pounds():
    """L1's acceptance figure: default answers with the Large band (190 m²)."""
    cat = categories()["mowing"]
    assert price(cat, {}, pricing_v1_params()["mowing"], 190).price_pence == 3100


def test_lawn_confidence_comes_from_the_area_estimator():
    """Ruling after F review (b): no hard-coded mowing confidence; the estimator decides."""
    cat, params = categories()["mowing"], pricing_v1_params()["mowing"]
    assert price(cat, {}, params, 190, "medium").confidence == "medium"  # manual size bands
    assert price(cat, {}, params, 190, "high").confidence == "high"  # a measured estimator, later
    assert price(cat, {}, params, 190).confidence is None  # the model alone doesn't decide
    assert "confidence" not in params
