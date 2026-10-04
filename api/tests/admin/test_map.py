"""The admin map (A30 to A35): admins only, only the layers asked for, completed jobs in the date
range, one pin per booking, the H3 concentration grid, the uncovered-demand rule, and providers
at their postcode's centroid, never their address."""

from datetime import date, timedelta

import h3
import pytest
from fastapi import HTTPException

from app.admin import map as admin_map
from app.core.geo import miles_between
from app.core.ids import new_id
from app.core.timeutil import london_today, utcnow
from app.models.bookings import Booking
from app.models.common import GeoPoint
from app.models.visits import Performer, Visit
from app.repos import Bookings, JobRequests, Providers, Visits
from app.services.eligibility import alert_targets, within_reach
from tests.admin.conftest import ok
from tests.conftest import new_client, sign_in, signed_out
from tests.factories import HAZLEMERE, make_customer, make_provider, make_request

RISBOROUGH = HAZLEMERE.model_copy(
    update={
        "line1": "7 Bell Street",
        "locality": "Princes Risborough",
        "town": "Princes Risborough",
        "postcode": "HP27 0AA",
        "district": "HP27",
        "lat": 51.7243,
        "lng": -0.834,
        "label": "7 Bell Street, Princes Risborough, HP27 0AA",
    }
)
MARLOW = HAZLEMERE.model_copy(
    update={"locality": "Marlow", "town": "Marlow", "postcode": "SL7 1DD", "district": "SL7"}
    | {"lat": 51.5718, "lng": -0.7735}
)
EVERY_LAYER = ["open", "uncovered", "booked", "completed", "providers"]


async def get_map(client, **params):
    return ok(await client.get("/api/admin/map", params=params))


async def request_at(db, customer, address=HAZLEMERE, *, hours_old: float = 0, category: str = "mowing"):
    req = await make_request(db, customer, category)
    await JobRequests(db).update(
        req.id,
        {"address": address.model_dump(mode="python"), "created_at": utcnow() - timedelta(hours=hours_old)},
    )
    return await JobRequests(db).get(req.id)


async def booking_at(db, customer, provider, address=HAZLEMERE, *, price: int = 3000) -> Booking:
    b = Booking(
        ref=f"B-{new_id()[-4:]}",
        source="platform",
        customer_id=customer.id,
        provider_id=provider.id,
        category_id="mowing",
        via="guide",
        price_pence=price,
        unit="a visit",
        recurring=True,
        frequency="weekly",
        address=address,
    )
    await Bookings(db).insert(b)
    return b


async def visit_on(db, booking: Booking, provider, day: date, status: str = "scheduled") -> Visit:
    v = Visit(
        booking_id=booking.id,
        customer_id=booking.customer_id,
        provider_id=provider.id,
        performer=Performer(provider_id=provider.id, user_id=provider.user_id, name=provider.short),
        category_id=booking.category_id,
        source="platform",
        local_date=day,
        scheduled_start=utcnow().replace(year=day.year, month=day.month, day=day.day, hour=9, minute=0),
        price_pence=booking.price_pence,
        est_mins=40,
        status=status,  # type: ignore[arg-type]
    )
    await Visits(db).insert(v)
    return v


# ---------------------------------------------------------------- who may see it


async def test_admins_only(client, db, catalogue):
    assert signed_out(await client.get("/api/admin/map"))
    await sign_in(client, db, "07700 900456")  # a new customer
    r = await client.get("/api/admin/map", params={"layers": EVERY_LAYER})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "admins_only"


async def test_providers_cant_see_it(app, db, catalogue):
    await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    async with await new_client(app) as c:
        await sign_in(c, db, "07700 900201")
        r = await c.get("/api/admin/map", params={"layers": ["providers"]})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "admins_only"


async def test_pins_carry_the_area_never_the_address_or_the_customer(jo, db, catalogue):
    customer = await make_customer(db)
    await request_at(db, customer, hours_old=2)
    provider = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    booking = await booking_at(db, customer, provider)
    await visit_on(db, booking, provider, london_today() + timedelta(days=1))
    r = await jo.get("/api/admin/map", params={"layers": EVERY_LAYER})
    assert r.status_code == 200
    for private in ("Orchard Way", "HP15 7QT", "Sarah", "Whitfield", "+44"):
        assert private not in r.text
    pin = r.json()["open"]["features"][0]
    assert (pin["properties"]["area"], pin["properties"]["district"]) == ("Hazlemere", "HP15")
    assert pin["geometry"] == {"type": "Point", "coordinates": [HAZLEMERE.lng, HAZLEMERE.lat]}


# ---------------------------------------------------------------- layers


async def test_only_the_layers_asked_for_are_sent(jo, db, catalogue):
    customer = await make_customer(db)
    provider = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    await request_at(db, customer)
    booking = await booking_at(db, customer, provider)
    await visit_on(db, booking, provider, london_today() + timedelta(days=2))

    d = await get_map(jo, layers=["open"], shade="none")
    assert len(d["open"]["features"]) == 1
    assert [d[k] for k in ("uncovered", "booked", "completed", "providers", "reach", "hexes")] == [None] * 6

    # Shading by booked visits reads them, but doesn't send them as pins.
    d = await get_map(jo, layers=["providers"], shade="booked")
    assert d["open"] is None and d["booked"] is None
    assert len(d["providers"]["features"]) == len(d["reach"]["features"]) == 1
    assert (d["hexes"]["shade_by"], d["hexes"]["total"]) == ("booked", 1)

    # Nothing asked for: only the grid, of open requests by default.
    d = await get_map(jo)
    assert all(d[k] is None for k in ("open", "uncovered", "booked", "completed", "providers", "reach"))
    assert (d["hexes"]["shade_by"], d["hexes"]["total"]) == ("open", 1)

    d = await get_map(jo, layers=EVERY_LAYER)
    assert all(d[k] is not None for k in ("open", "uncovered", "booked", "completed", "providers", "reach"))

    r = await jo.get("/api/admin/map", params={"layers": ["everything"]})
    assert r.status_code == 422
    r = await jo.get("/api/admin/map", params={"shade": "providers"})
    assert r.status_code == 422


async def test_requests_open_an_hour_without_a_taker_are_highlighted(jo, db, catalogue):
    customer = await make_customer(db)
    old = await request_at(db, customer, hours_old=2)
    new = await request_at(db, customer, hours_old=0.5)
    booked = await request_at(db, customer, hours_old=3)
    await JobRequests(db).update(booked.id, {"status": "booked"})

    d = await get_map(jo, layers=["open"])
    pins = {f["properties"]["ref"]: f["properties"] for f in d["open"]["features"]}
    assert set(pins) == {old.ref, new.ref}, "only open requests"
    assert (pins[old.ref]["waiting"], pins[old.ref]["age_text"]) == (True, "2 hours")
    assert (pins[new.ref]["waiting"], pins[new.ref]["age_text"]) == (False, "30 minutes")
    assert d["waiting_after_minutes"] == 60
    assert pins[old.ref]["guide_pence"] == old.guide_pence and pins[old.ref]["category_name"] == "Lawn mowing"


async def test_booked_visits_are_one_pin_per_booking_from_today_on(jo, db, catalogue):
    customer = await make_customer(db)
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    today = london_today()
    weekly = await booking_at(db, customer, dave, price=3200)
    for days in (1, 8, 15):
        await visit_on(db, weekly, dave, today + timedelta(days=days))
    await visit_on(db, weekly, dave, today + timedelta(days=3), status="cancelled")
    await visit_on(db, weekly, dave, today - timedelta(days=2))  # overdue, not to come
    await visit_on(db, weekly, dave, today - timedelta(days=9), status="finished")
    other = await booking_at(db, customer, mike, MARLOW, price=2800)
    await visit_on(db, other, mike, today)

    d = await get_map(jo, layers=["booked"], shade="booked")
    pins = {f["id"]: f["properties"] for f in d["booked"]["features"]}
    assert set(pins) == {weekly.id, other.id}
    assert pins[weekly.id]["visits"] == 3 and pins[weekly.id]["visit_date"] == (today + timedelta(days=1)).isoformat()
    assert (pins[weekly.id]["provider_short"], pins[weekly.id]["price_pence"]) == ("Dave H.", 3200)
    assert (pins[other.id]["area"], pins[other.id]["visits"], pins[other.id]["visit_date"]) == (
        "Marlow",
        1,
        today.isoformat(),
    )
    assert d["booked"]["visits"] == 4
    assert d["hexes"]["total"] == 4 and d["hexes"]["max"] == 3, "the grid counts visits, not pins"


async def test_completed_jobs_follow_the_date_range(jo, db, catalogue):
    customer = await make_customer(db)
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    today = london_today()
    b = await booking_at(db, customer, dave)
    for days in (1, 10, 40):
        await visit_on(db, b, dave, today - timedelta(days=days), status="finished")
    await visit_on(db, b, dave, today - timedelta(days=5), status="skipped")
    await visit_on(db, b, dave, today + timedelta(days=4))

    def pin(d):
        [f] = d["completed"]["features"]
        return f["properties"]["visits"], f["properties"]["visit_date"]

    d = await get_map(jo, layers=["completed"])  # the last 30 days, today included
    assert (d["from_date"], d["to_date"]) == ((today - timedelta(days=29)).isoformat(), today.isoformat())
    assert pin(d) == (2, (today - timedelta(days=1)).isoformat()), "the latest finished visit in the range"
    back = {"from": today - timedelta(days=45), "to": today - timedelta(days=20)}
    d = await get_map(jo, layers=["completed"], **back)
    assert pin(d) == (1, (today - timedelta(days=40)).isoformat())
    d = await get_map(jo, layers=["completed"], to=today - timedelta(days=20))  # 30 days ending then
    assert d["from_date"] == (today - timedelta(days=49)).isoformat() and pin(d)[0] == 1
    d = await get_map(jo, layers=["completed"], **{"from": today - timedelta(days=10)})  # to today
    assert d["to_date"] == today.isoformat() and pin(d)[0] == 2
    d = await get_map(jo, layers=["completed"], **{"from": today, "to": today})
    assert d["completed"]["features"] == [] and d["completed"]["visits"] == 0
    d = await get_map(jo, layers=["completed"], shade="completed", **{"from": today - timedelta(days=60)})
    assert d["hexes"]["total"] == 3

    for params in (
        {"from": today, "to": today - timedelta(days=1)},
        {"from": today + timedelta(days=1)},
        {"from": today - timedelta(days=366), "to": today},
    ):
        r = await jo.get("/api/admin/map", params={"layers": ["completed"], **params})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_range", params
    ok(await jo.get("/api/admin/map", params={"from": today - timedelta(days=365), "to": today}))


async def test_a_visit_without_its_booking_has_no_address_and_is_left_out(jo, db, catalogue):
    from tests.payments.helpers import card_customer, finished_visit, payable_provider

    await finished_visit(db, await card_customer(db), await payable_provider(db), days_ago=1)
    d = await get_map(jo, layers=["completed"], shade="completed")
    assert d["completed"]["features"] == [] and d["hexes"]["total"] == 0 and d["hexes"]["legend"] == []


# ---------------------------------------------------------------- concentration (A34)


def test_legend_bands_cover_every_count_once():
    assert admin_map.bands(0) == []
    assert [b.label for b in admin_map.bands(1)] == ["1"]
    assert [b.label for b in admin_map.bands(3)] == ["1", "2", "3"]
    assert [b.label for b in admin_map.bands(12)] == ["1 to 2", "3 to 4", "5 to 7", "8 to 9", "10 to 12"]
    for top in range(1, 80):
        legend = admin_map.bands(top)
        assert len(legend) == min(top, 5)
        covered = [n for b in legend for n in range(b.min, b.max + 1)]
        assert covered == list(range(1, top + 1)), top
        assert [b.level for b in legend] == list(range(len(legend)))
        assert admin_map.level_of(top, legend) == len(legend) - 1 and admin_map.level_of(1, legend) == 0


def test_the_grid_counts_points_per_resolution_8_cell():
    grid = admin_map.hex_grid(
        "booked", [(HAZLEMERE.lat, HAZLEMERE.lng, 3), (HAZLEMERE.lat, HAZLEMERE.lng, 1), (MARLOW.lat, MARLOW.lng, 2)]
    )
    assert (grid.resolution, grid.total, grid.max) == (8, 6, 4)
    cells = {f.properties.cell: f for f in grid.cells.features}
    hazlemere = h3.latlng_to_cell(HAZLEMERE.lat, HAZLEMERE.lng, 8)
    assert {c: f.properties.count for c, f in cells.items()} == {
        hazlemere: 4,
        h3.latlng_to_cell(MARLOW.lat, MARLOW.lng, 8): 2,
    }
    assert all(h3.get_resolution(c) == 8 for c in cells)
    assert grid.cells.features[0].properties.cell == hazlemere, "densest first"
    assert [f.properties.level for f in grid.cells.features] == [3, 1]
    [ring] = cells[hazlemere].geometry.coordinates
    assert len(ring) == 7 and ring[0] == ring[-1], "a closed hexagon"
    # About 1 km across: a corner is an edge's length (some 460 m) from the centre.
    lat, lng = h3.cell_to_latlng(hazlemere)
    for x, y in ring:
        assert 0.22 < miles_between(lat, lng, y, x) < 0.38


async def test_shading_open_requests(jo, db, catalogue):
    customer = await make_customer(db)
    for _ in range(3):
        await request_at(db, customer)
    await request_at(db, customer, RISBOROUGH)
    d = await get_map(jo, layers=["open"], shade="open")
    assert (d["hexes"]["total"], d["hexes"]["max"]) == (4, 3)
    assert sorted(f["properties"]["count"] for f in d["hexes"]["cells"]["features"]) == [1, 3]
    assert [b["label"] for b in d["hexes"]["legend"]] == ["1", "2", "3"]


# ---------------------------------------------------------------- uncovered demand (A32)


async def test_uncovered_demand_is_outside_every_active_providers_radius(jo, db, catalogue):
    customer = await make_customer(db)
    near = await request_at(db, customer, HAZLEMERE)
    far = await request_at(db, customer, RISBOROUGH, category="hedges")
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])  # Hazlemere, 4 miles

    async def pins():
        d = await get_map(jo, layers=["open", "uncovered"])
        return {f["properties"]["ref"]: f["properties"] for f in d["open"]["features"]}, [
            f["properties"]["ref"] for f in d["uncovered"]["features"]
        ]

    got, uncovered = await pins()
    assert uncovered == [far.ref]
    assert (got[near.ref]["uncovered"], got[near.ref]["in_reach"], got[near.ref]["in_reach_doing_it"]) == (False, 1, 1)
    assert (got[far.ref]["uncovered"], got[far.ref]["in_reach"]) == (True, 0)

    # Providers who can't take new jobs don't cover anywhere, however close they live.
    in_risborough = {"home.location": {"lat": 51.725, "lng": -0.83}, "home.postcode": "HP27 0AA"}
    for i, status in enumerate(("suspended", "signing_up")):
        p = await make_provider(db, f"Pat Smith{i}", f"+44770090030{i}", ["hedges"], status=status)
        await Providers(db).update(p.id, in_risborough)
    assert (await pins())[1] == [far.ref]

    # Payouts paused still takes jobs, so it covers; one who doesn't do hedges still counts.
    jan = await make_provider(db, "Jan Kowalski", "+447700900211", ["mowing"], status="payouts_paused")
    await Providers(db).update(jan.id, in_risborough)
    got, uncovered = await pins()
    assert uncovered == [] and (got[far.ref]["in_reach"], got[far.ref]["in_reach_doing_it"]) == (1, 0)

    # A wider radius reaches further.
    await Providers(db).update(jan.id, {"status": "suspended"})
    assert (await pins())[1] == [far.ref]
    await Providers(db).update(dave.id, {"travel_radius_miles": 8})
    got, uncovered = await pins()
    assert uncovered == [] and got[far.ref]["in_reach"] == 1


async def test_uncovered_means_the_broadcast_reaches_nobody_by_distance(db, catalogue):
    """The rule is the broadcast's own distance test (eligibility.within_reach), right up to the
    edge of the radius."""
    customer = await make_customer(db)
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    home = dave.home.location
    for miles in (3.9, 3.999, 4.001, 4.2):
        lng, lat = admin_map.circle(home.lat, home.lng, miles, n=4)[1]  # due east
        req = await request_at(db, customer, HAZLEMERE.model_copy(update={"lat": lat, "lng": lng}))
        cov = admin_map.coverage(req, [dave])
        assert within_reach(dave, req) == (miles <= 4) == (not cov.uncovered), miles
        alerted = [t.provider.id for t in await alert_targets(db, req, catalogue["mowing"])]
        assert (dave.id in alerted) == (not cov.uncovered), miles


def test_a_travel_radius_circle_is_that_far_all_round():
    ring = admin_map.circle(51.656, -0.716, 4)
    assert len(ring) == admin_map.REACH_POINTS + 1 and ring[0] == ring[-1]
    for lng, lat in ring:
        assert miles_between(51.656, -0.716, lat, lng) == pytest.approx(4, abs=0.01)


# ---------------------------------------------------------------- providers (A33)


async def test_providers_sit_at_their_postcodes_centroid_never_their_address(jo, db, catalogue):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing", "hedges"])
    await Providers(db).update(
        dave.id, {"home.postcode": "HP15 7LH", "home.location": {"lat": 51.6461, "lng": -0.6929}}
    )
    # HP15 7AB isn't in the table: rounded to about 1 km, never the address itself.
    ken = await make_provider(db, "Ken Ashworth", "+447700900212", ["mowing"], status="signing_up")
    gary = await make_provider(db, "Gary Tomlinson", "+447700900209", ["hedges"], status="suspended")

    d = await get_map(jo, layers=["providers"])
    pins = {f["id"]: f for f in d["providers"]["features"]}
    assert pins[dave.id]["geometry"]["coordinates"] == [-0.6935, 51.6455]
    assert pins[dave.id]["properties"]["placed_at"] == "postcode"
    assert pins[dave.id]["properties"]["jobs"] == ["Lawn mowing", "Hedge trimming"]
    assert pins[ken.id]["geometry"]["coordinates"] == [-0.72, 51.66]
    assert pins[ken.id]["geometry"]["coordinates"] != [ken.home.location.lng, ken.home.location.lat]
    assert pins[ken.id]["properties"]["placed_at"] == "approximate"
    statuses = {p["properties"]["short"]: (p["properties"]["status"], p["properties"]["covers"]) for p in pins.values()}
    assert statuses == {
        "Dave H.": ("active", True),
        "Ken A.": ("signing_up", False),
        "Gary T.": ("suspended", False),
    }
    reach = {f["id"]: f for f in d["reach"]["features"]}
    assert set(reach) == set(pins)
    [ring] = reach[dave.id]["geometry"]["coordinates"]
    for lng, lat in ring:
        assert miles_between(51.6455, -0.6935, lat, lng) == pytest.approx(4, abs=0.01)
    assert reach[gary.id]["properties"] == {
        "provider_id": gary.id,
        "status": "suspended",
        "travel_radius_miles": 4,
        "covers": False,
    }


def test_place_home():
    from app.services.postcodes import place_home

    home = GeoPoint(lat=51.65678, lng=-0.71234)
    assert place_home("hp15 7lh", home) == (GeoPoint(lat=51.6455, lng=-0.6935), "postcode")
    assert place_home("HP15 7AB", home) == (GeoPoint(lat=51.66, lng=-0.71), "approximate")
    assert place_home("not a postcode", home)[1] == "approximate"


def test_date_range_rules():
    today = date(2026, 10, 4)
    assert admin_map.date_range(None, None, today) == (date(2026, 9, 5), today)
    assert admin_map.date_range(None, date(2026, 9, 1), today) == (date(2026, 8, 3), date(2026, 9, 1))
    assert admin_map.date_range(date(2026, 9, 20), None, today) == (date(2026, 9, 20), today)
    with pytest.raises(HTTPException):
        admin_map.date_range(date(2026, 10, 5), None, today)
    assert admin_map.date_range(date(2025, 10, 4), today, today)[0] == date(2025, 10, 4)  # a year
    with pytest.raises(HTTPException):
        admin_map.date_range(date(2025, 10, 3), today, today)
