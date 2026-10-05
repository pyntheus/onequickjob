"""The lawn step's three ways to one area (decisions.md A26, A27): a size band, paced out in
strides, or measured in metres or feet; up to four lawns, summed. The area is worked out here,
never in the web app, and the quote records how it was sized."""

import pytest

from app.adapters.area import make_area_estimator
from app.adapters.area.base import AreaInput, input_for
from app.adapters.area.describe import fact_text, result_text, size_phrase
from app.repos import JobRequests, Quotes
from tests.conftest import make_settings
from tests.customer.helpers import request_body, signed_in_with_card


def paced(*lawns: tuple) -> dict:
    return {"method": "paced", "lawns": [{"length": a, "width": b} for a, b in lawns]}


def measured(unit: str, *lawns: tuple) -> dict:
    return {"method": "measured", "unit": unit, "lawns": [{"length": a, "width": b} for a, b in lawns]}


async def estimate(client, body: dict) -> dict:
    r = await client.post("/api/area/estimate", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def refused(client, body: dict) -> dict:
    r = await client.post("/api/area/estimate", json=body)
    assert r.status_code == 422, r.text
    return r.json()["detail"]


# ------------------------------------------------------------------------- the options


async def test_the_options_offer_three_ways_and_the_bands_compare_with_cars(client):
    opts = (await client.get("/api/area/options")).json()
    assert opts["methods"] == ["band", "paced", "measured"] and opts["confidence"] == "medium"
    assert [(b["id"], b["label"], b["area_m2"], b["comparison"]) for b in opts["bands"]] == [
        ("small", "Small", 40, "About 5 × 8 metres (40 m²). Nearly 2 car lengths long and 1 wide."),
        ("medium", "Medium", 85, "About 7 × 12 metres (85 m²). Nearly 3 car lengths long and 1½ wide."),
        ("large", "Large", 190, "About 10 × 19 metres (190 m²). 4 car lengths long and 2 wide."),
        ("very_large", "Very large", 350, "About 15 × 23 metres (350 m²). 5 car lengths long and 3 wide."),
    ]
    assert [(b["width_m"], b["length_m"], b["house"]) for b in opts["bands"]] == [
        (5, 8, False),
        (7, 12, False),
        (10, 19, True),
        (15, 23, True),
    ]
    assert opts["limits"] == {
        "side_min_m": 1,
        "side_max_m": 100,
        "total_min_m2": 5,
        "total_max_m2": 2000,
        "max_lawns": 4,
    }
    assert [a["label"] for a in opts["adjustments"]] == ["Looks smaller", "About right", "Looks bigger"]
    text = str(opts).lower()
    assert "tennis" not in text and "badminton" not in text and "garage" not in text


# ------------------------------------------------------------------------- bands


@pytest.mark.parametrize(
    ("band", "adjust", "area"),
    [("small", "right", 40), ("medium", "right", 85), ("large", "smaller", 152), ("very_large", "bigger", 420)],
)
async def test_bands_with_their_nudges(client, band, adjust, area):
    out = await estimate(client, {"method": "band", "band": band, "adjust": adjust})
    m = out["measure"]
    assert (m["estimator"], m["method"], m["area_m2"], m["band"], m["adjust"]) == (
        "manual_bands_v0",
        "band",
        area,
        band,
        adjust,
    )
    assert m["confidence"] == "medium" and m["lawns"] == [] and m["unit"] is None


async def test_a_band_is_needed_for_the_band_method(client):
    assert (await refused(client, {"method": "band"}))["code"] == "lawn_size_needed"
    assert (await refused(client, {"band": "enormous"}))["code"] == "lawn_size_needed"


# ------------------------------------------------------------------------- paced and measured


async def test_strides_count_as_metres(client):
    out = await estimate(client, paced((12, 8)))
    m = out["measure"]
    assert (m["estimator"], m["method"], m["unit"], m["area_m2"], m["confidence"]) == (
        "customer_measured_v0",
        "paced",
        "strides",
        96,
        "medium",
    )
    assert m["lawns"] == [{"length": 12, "width": 8, "length_m": 12, "width_m": 8, "area_m2": 96}]
    assert out["text"] == "That's about 12 × 8 metres (96 m²)"
    assert out["lawn_texts"] == ["about 12 × 8 metres (96 m²)"]


async def test_metres_with_decimals(client):
    out = await estimate(client, measured("m", ("7.5", "4.25")))  # 31.875 m²
    assert out["measure"]["area_m2"] == 32 and out["measure"]["unit"] == "m"
    assert out["measure"]["lawns"][0]["length"] == 7.5 and out["measure"]["lawns"][0]["width"] == 4.25
    assert out["text"] == "That's about 7.5 × 4.3 metres (32 m²)", "sides to the nearest 10 cm, half-up"


async def test_feet_are_converted_at_0_3048_metres(client):
    out = await estimate(client, measured("ft", (30, 20)))  # 9.144 × 6.096 = 55.741824 m²
    lawn = out["measure"]["lawns"][0]
    assert (lawn["length"], lawn["width"], lawn["length_m"], lawn["width_m"]) == (30, 20, 9.144, 6.096)
    assert out["measure"]["area_m2"] == 56 and out["measure"]["unit"] == "ft"
    assert out["text"] == "That's about 9.1 × 6.1 metres (56 m²)"


async def test_several_lawns_are_added_up(client):
    out = await estimate(client, paced((12, 8), (7, 6), (5, 3)))
    assert out["measure"]["area_m2"] == 96 + 42 + 15
    assert [lw["area_m2"] for lw in out["measure"]["lawns"]] == [96, 42, 15]
    assert out["text"] == "That's about 153 m² in total across 3 lawns"
    assert out["lawn_texts"] == [
        "about 12 × 8 metres (96 m²)",
        "about 7 × 6 metres (42 m²)",
        "about 5 × 3 metres (15 m²)",
    ]
    four = await estimate(client, measured("m", (10, 10), (10, 10), (10, 10), (10, 10)))
    assert four["measure"]["area_m2"] == 400 and len(four["measure"]["lawns"]) == 4
    r = await client.post("/api/area/estimate", json=measured("m", *[(10, 10)] * 5))
    assert r.status_code == 422, "four lawns at most"


async def test_rounding_is_half_up_per_lawn_and_the_lawns_are_summed(client):
    # 1.5 × 3 = 4.5 m²: half-up makes it 5 (Python's round() would make it 4, below the minimum).
    assert (await estimate(client, measured("m", ("1.5", 3))))["measure"]["area_m2"] == 5
    # 2.6 × 2.5 = 6.5 m², twice: each lawn is 7, so the total is 14 and the figures shown add up.
    out = await estimate(client, measured("m", ("2.6", "2.5"), ("2.6", "2.5")))
    assert [lw["area_m2"] for lw in out["measure"]["lawns"]] == [7, 7] and out["measure"]["area_m2"] == 14
    # Exact decimals, never floats: 2.32 × 6.25 is 14.5 m² (floats make it 14.499999999999998).
    assert (await estimate(client, measured("m", ("2.32", "6.25"))))["measure"]["area_m2"] == 15
    assert (await estimate(client, measured("m", ("2.32", "6.25"))))["text"] == "That's about 2.3 × 6.3 metres (15 m²)"


async def test_each_side_is_1_to_100_metres(client):
    assert (await estimate(client, measured("m", (1, 5))))["measure"]["area_m2"] == 5
    assert (await estimate(client, measured("m", (100, 20))))["measure"]["area_m2"] == 2000
    short = await refused(client, measured("m", ("0.99", 10)))
    assert short == {
        "code": "lawn_size_invalid",
        "message": "The length must be between 1 and 100 metres.",
        "extra": {"lawn": 0, "side": "length"},
    }
    long = await refused(client, measured("m", (10, 10), (8, "100.01")))
    assert long["message"] == "Lawn 2: the width must be between 1 and 100 metres."
    assert long["extra"] == {"lawn": 1, "side": "width"}
    assert (await refused(client, paced((101, 2))))["message"] == "The length must be 1 to 100 strides."
    assert (await refused(client, paced((0, 10))))["code"] == "lawn_size_invalid"


async def test_feet_limits_are_the_same_metres(client):
    # 3.3 ft is 1.006 m, 328 ft is 99.97 m; 3.28 ft (0.9997 m) and 328.1 ft (100.005 m) aren't.
    assert (await estimate(client, measured("ft", ("3.3", 30))))["measure"]["area_m2"] == 9
    assert (await estimate(client, measured("ft", (328, 10))))["measure"]["area_m2"] == 305
    for sides in [("3.28", 30), ("328.1", 10)]:
        detail = await refused(client, measured("ft", sides))
        assert detail["message"] == "The length must be between 3.3 and 328 feet (1 to 100 metres)."


async def test_the_total_is_5_to_2000_square_metres(client):
    small = await refused(client, paced((2, 2)))
    assert small["message"] == "That's only 4 m². Check the sizes: we can price lawns from 5 m²."
    big = await refused(client, measured("m", (100, "20.01")))
    assert big["message"] == "That's 2,001 m², more than the 2,000 m² we can price here. Check the sizes."
    across = await refused(client, paced((50, 30), (40, 20), (10, 10)))  # 1500 + 800 + 100
    assert across["message"].startswith("That's 2,400 m²")


async def test_strides_are_whole_and_measurements_have_two_decimal_places_at_most(client):
    assert (await refused(client, paced(("12.5", 8))))["message"] == "The length is a whole number of strides."
    assert (await estimate(client, paced(("12.0", 8))))["measure"]["area_m2"] == 96
    assert (await refused(client, measured("m", ("7.255", 4))))["message"] == (
        "The length needs at most two decimal places."
    )
    assert (await refused(client, {"method": "paced", "lawns": []}))["code"] == "lawn_size_needed"
    r = await client.post("/api/area/estimate", json=measured("yards", (10, 10)))
    assert r.status_code == 422


# ------------------------------------------------------------------------- quotes record the method


async def test_a_quote_records_the_method_and_its_inputs(client, db, catalogue):
    r = await client.post(
        "/api/quotes", json={"category_id": "mowing", "lawn": measured("ft", ("62.34", "32.81"), (10, 10))}
    )
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["measure"]["method"] == "measured" and q["measure"]["estimator"] == "customer_measured_v0"
    assert q["measure"]["unit"] == "ft" and [(lw["length"], lw["width"]) for lw in q["measure"]["lawns"]] == [
        (62.34, 32.81),
        (10, 10),
    ]
    assert q["confidence"]["label"] == "Fairly close", "A2 still applies: the customer's own figures"
    assert q["size_text"] == "2 lawns, about 199 m² in total"  # 190 + 9
    stored = await Quotes(db).get(q["id"])
    assert stored.measure.method == "measured" and stored.measure.area_m2 == 199
    assert stored.measure.lawns[0].length_m == pytest.approx(19.001232)


async def test_three_ways_to_the_same_area_give_one_price(client, catalogue):
    """The engine prices an area, however it was sized: 190 m² as the Large band, 19 × 10
    strides, or 19 × 10 metres is the same £31 (the golden £30 is at 186 m²: 31 × 6 strides)."""
    prices = []
    for lawn in [{"band": "large"}, paced((19, 10)), measured("m", (19, 10)), measured("m", ("12.5", 8), (9, 10))]:
        r = await client.post("/api/quotes", json={"category_id": "mowing", "lawn": lawn})
        assert r.status_code == 201, r.text
        assert r.json()["measure"]["area_m2"] == 190
        prices.append(r.json()["result"]["price_pence"])
    assert prices == [3100] * 4
    golden = await client.post("/api/quotes", json={"category_id": "mowing", "lawn": paced((31, 6))})
    assert golden.json()["result"]["price_pence"] == 3000


async def test_an_invalid_lawn_is_refused_by_the_quote_too(client, catalogue):
    r = await client.post("/api/quotes", json={"category_id": "mowing", "lawn": paced((2, 2))})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "lawn_size_invalid"
    r = await client.post("/api/quotes", json={"category_id": "mowing", "lawn": {"method": "paced"}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "lawn_size_needed"


async def test_the_request_page_says_what_the_price_is_for(client, db, catalogue):
    await signed_in_with_card(client, db)
    for lawn, text in [
        ({"band": "large"}, "a large lawn (about 190 m²)"),
        ({"band": "medium", "adjust": "bigger"}, "a medium lawn, a bit bigger than that (about 102 m²)"),
        (paced((12, 8)), "a lawn of about 12 × 8 metres, paced out (96 m²)"),
        (measured("ft", (30, 20)), "a lawn of about 9.1 × 6.1 metres (56 m²)"),
        (paced((12, 8), (7, 6)), "2 lawns paced out, about 138 m² in total"),
    ]:
        q = (await client.post("/api/quotes", json={"category_id": "mowing", "lawn": lawn})).json()
        assert q["size_text"] == text
        r = await client.post("/api/c/requests", json=request_body(q["id"]))
        assert r.status_code == 201, r.text
        assert r.json()["size_text"] == text
        req = await JobRequests(db).by_ref(r.json()["ref"])
        assert req.measure.method == q["measure"]["method"], "the request keeps how the lawn was sized"
        await client.post(f"/api/c/requests/{r.json()['ref']}/cancel")


# ------------------------------------------------------------------------- the same lawn again


@pytest.mark.parametrize(
    "lawn",
    [
        {"band": "very_large", "adjust": "smaller"},
        paced((12, 8), (7, 6)),
        measured("ft", ("30.5", "20.25")),
        measured("m", ("7.5", "4.25"), ("2.6", "2.5")),
    ],
)
async def test_input_for_sizes_the_lawn_exactly_as_the_customer_did(lawn):
    estimator = make_area_estimator(make_settings())
    first = await estimator.estimate(None, AreaInput(**lawn))
    again = await estimator.estimate(None, input_for(first, "medium"))
    assert again == first


async def test_wording_for_providers_and_old_records():
    estimator = make_area_estimator(make_settings())
    two = await estimator.estimate(None, AreaInput(**paced((12, 8), (7, 6))))
    assert fact_text(two) == "About 138 m² across 2 lawns"
    one = await estimator.estimate(None, AreaInput(**measured("m", (12, 8))))
    assert fact_text(one) == "About 96 m²"
    band = await estimator.estimate(None, AreaInput(band="large"))
    assert (fact_text(band), result_text(band)) == ("About 190 m²", "That's about 190 m²")
    # A record from before A26 has no method: it was a band.
    from app.models.quotes import Measure

    old = Measure.model_validate({"estimator": "manual_bands_v0", "area_m2": 190, "band": "large", "adjust": "right"})
    assert old.method == "band" and size_phrase(old) == "a large lawn (about 190 m²)"
    assert input_for(old, "medium") == AreaInput(band="large", adjust="right")
    no_band = Measure(estimator="lidar", area_m2=210)
    assert size_phrase(no_band) == "a lawn of about 210 m²" and input_for(no_band, "medium").band == "medium"
