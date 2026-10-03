"""Differential test: the Python engine against the prototype's own JavaScript.

tests/fixtures/prototype_cases.json is produced by running PRICING_MODELS from
docs/design/prototype.jsx in Node (scripts/prototype-extract.mjs cases 80): every
category's defaults plus 80 random answer sets each, with JavaScript's Math.round.

Where the exact value is a half (138 min x £45/60 = £103.50) JavaScript's float maths can
land a hair below it and round down. The generator flags those cases
(float_half_boundary); there the port must round the exact value up, so it may be exactly
one unit (£1 or 1 minute) above the JavaScript figure and nowhere else.
"""

import json
from pathlib import Path

import pytest

from app.pricing.engine import price
from tests.catalogue_fixtures import categories, pricing_v1_params

CASES = json.loads((Path(__file__).parents[1] / "fixtures" / "prototype_cases.json").read_text())["cases"]

# Deliberate copy change (decisions.md ruling R7): with manual size bands the lawn area is
# no longer "measured from survey data", so the mowing confidence note was corrected.
COPY_CHANGES = {
    ("mowing", "conf_note"): (
        "Measured from survey data, so most providers accept it as it is.",
        "Based on the lawn size you chose, so most providers accept it as it is.",
    ),
}


def test_fixture_covers_every_category():
    assert {c["category"] for c in CASES} == set(categories())
    assert len(CASES) >= 15 * 80


@pytest.mark.parametrize("case", CASES, ids=[f"{c['category']}-{i}" for i, c in enumerate(CASES)])
def test_matches_prototype(case):
    cat = categories()[case["category"]]
    # The prototype measured lawns (LIDAR), so its mowing quotes are "high": pass that as the
    # area estimator's confidence. With manual bands the estimator says "medium" instead.
    est = price(
        cat, case["answers"], pricing_v1_params()[cat.id], case["area_m2"], "high" if cat.measure == "lawn" else None
    )
    exp = case["expected"]
    got = {
        "price_pence": est.price_pence,
        "first_pence": est.first_pence,
        "mins": est.mins,
        "first_mins": est.first_mins,
        "low_pence": est.low_pence,
        "high_pence": est.high_pence,
        "spread": [float(est.spread[0]), float(est.spread[1])],
        "confidence": est.confidence,
        "unit": est.unit,
        "note": est.note,
        "first_reason": est.first_reason,
        "conf_note": est.conf_note,
    }
    exp = {k: v for k, v in exp.items() if k != "float_half_boundary"}
    for (cat_id, field), (old, new) in COPY_CHANGES.items():
        if cat.id == cat_id:
            assert exp[field] == old
            assert got[field] == new
            exp = {**exp, field: new}
    if case["expected"]["float_half_boundary"]:
        for field, unit in UNITS.items():
            if got[field] != exp[field]:
                assert got[field] == exp[field] + unit, f"{field}: only a float half may round up by one unit"
                exp = {**exp, field: got[field]}
    assert got == exp


UNITS = {"price_pence": 100, "first_pence": 100, "low_pence": 100, "high_pence": 100, "mins": 1, "first_mins": 1}


def test_float_half_cases_are_rare_and_flagged():
    flagged = [c for c in CASES if c["expected"]["float_half_boundary"]]
    assert 0 < len(flagged) < len(CASES) // 50
