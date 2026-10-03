"""DEMO_MODE's "Simulate local responses": seeded providers counter and accept through the real
offer endpoints; none of it exists when DEMO_MODE is off."""

import asyncio

import httpx
import pytest

from app.customer import simulator
from app.main import create_app
from app.repos import Bookings, JobRequests, Offers, Sessions, Users
from tests.conftest import make_settings
from tests.customer.helpers import make_request_via_api, signed_in_with_card
from tests.factories import make_provider


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(simulator, "COUNTER_AFTER", 0)
    monkeypatch.setattr(simulator, "ACCEPT_AFTER", 0)


async def seeded(db, name: str, phone: str, skills: list[str], key: str, lat: float):
    from app.models.common import GeoPoint
    from app.repos import Providers

    p = await make_provider(db, name, phone, skills)
    await Users(db).update(p.user_id, {"demo_key": key})
    await Providers(db).patch(p.id, {"home.location": GeoPoint(lat=lat, lng=-0.716).model_dump()})
    return await Providers(db).get(p.id)


async def _wait(req_id: str) -> None:
    task = simulator.task_for(req_id)
    if task:
        await asyncio.wait_for(task, 10)


async def test_nearest_counters_at_guide_plus_20_and_the_next_accepts_at_guide(client, db, catalogue, fast):
    near = await seeded(db, "Dave Hughes", "+447700900201", ["mowing"], "dave", 51.655)
    nxt = await seeded(db, "Mike Reynolds", "+447700900202", ["mowing"], "mike", 51.66)
    await make_provider(db, "Not Seeded", "+447700900209", ["mowing"])  # real people are never played
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    assert detail["demo_simulator"] is True
    r = await client.post(f"/api/c/requests/{detail['ref']}/demo/simulate")
    assert r.status_code == 202, r.text
    assert r.json() == {"provider_short": "Dave H.", "counter_in_seconds": 0, "accept_in_seconds": 0}
    req = await JobRequests(db).by_ref(detail["ref"])
    await _wait(req.id)

    (offer,) = await Offers(db).for_request(req.id)
    assert offer.provider_id == near.id and offer.price_pence == 3700, "£31 + 20%, whole pounds"
    assert offer.status == "lapsed", "the guide acceptance booked it first"
    stored = await JobRequests(db).get(req.id)
    assert stored.status == "booked" and stored.booked.provider_id == nxt.id and stored.booked.via == "guide"
    assert await Bookings(db).count({}) == 1
    # Through the real endpoints: the counter texted the customer, the booking texted both sides.
    for t in ("counter_offer", "request_booked", "booking_confirmed", "job_taken"):
        assert await db["outbox"].count_documents({"template_id": t}) == 1, t
    assert await Sessions(db).count({"via": "demo"}) == 0, "the simulator's sessions end with it"


async def test_the_customer_can_accept_the_counter_before_the_guide_acceptance(client, db, catalogue, monkeypatch):
    monkeypatch.setattr(simulator, "COUNTER_AFTER", 0)
    monkeypatch.setattr(simulator, "ACCEPT_AFTER", 1)
    await seeded(db, "Dave Hughes", "+447700900201", ["mowing"], "dave", 51.655)
    await seeded(db, "Mike Reynolds", "+447700900202", ["mowing"], "mike", 51.66)
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    await client.post(f"/api/c/requests/{detail['ref']}/demo/simulate")
    req = await JobRequests(db).by_ref(detail["ref"])
    for _ in range(50):
        view = (await client.get(f"/api/c/requests/{detail['ref']}")).json()
        if view["pending_offers"]:
            break
        await asyncio.sleep(0.05)
    assert view["simulating"] is True
    offer_id = view["pending_offers"][0]["offer_id"]
    r = await client.post(f"/api/c/offers/{offer_id}/accept")
    assert r.status_code == 200 and r.json()["via"] == "counter" and r.json()["price_pence"] == 3700
    await _wait(req.id)
    stored = await JobRequests(db).get(req.id)
    assert stored.booked.via == "counter" and await Bookings(db).count({}) == 1


async def test_one_simulation_at_a_time_and_only_while_open(client, db, catalogue, monkeypatch):
    monkeypatch.setattr(simulator, "COUNTER_AFTER", 0)
    monkeypatch.setattr(simulator, "ACCEPT_AFTER", 0.3)
    await seeded(db, "Dave Hughes", "+447700900201", ["mowing"], "dave", 51.655)
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    assert (await client.post(f"/api/c/requests/{detail['ref']}/demo/simulate")).status_code == 202
    again = await client.post(f"/api/c/requests/{detail['ref']}/demo/simulate")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_simulating"
    req = await JobRequests(db).by_ref(detail["ref"])
    await _wait(req.id)
    assert (await JobRequests(db).get(req.id)).status == "booked", "one seeded provider: they accept at guide"
    assert await Offers(db).count({}) == 0
    late = await client.post(f"/api/c/requests/{detail['ref']}/demo/simulate")
    assert late.status_code == 409 and late.json()["detail"]["code"] == "not_open"


async def test_no_seeded_provider_means_nothing_to_simulate(client, db, catalogue, fast):
    await make_provider(db, "Not Seeded", "+447700900209", ["mowing"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    r = await client.post(f"/api/c/requests/{detail['ref']}/demo/simulate")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_demo_providers"


async def test_the_simulator_vanishes_when_demo_mode_is_off(db, catalogue, fast):
    app = create_app(make_settings(demo_mode=False))
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="https://test") as c:
        await seeded(db, "Dave Hughes", "+447700900201", ["mowing"], "dave", 51.655)
        await signed_in_with_card(c, db)
        detail = await make_request_via_api(c)
        assert detail["demo_simulator"] is False
        r = await c.post(f"/api/c/requests/{detail['ref']}/demo/simulate")
        assert r.status_code == 404
        assert (await c.get(f"/api/c/requests/{detail['ref']}")).json()["demo_simulator"] is False
    assert await Offers(db).count({}) == 0 and (await JobRequests(db).by_ref(detail["ref"])).status == "open"
