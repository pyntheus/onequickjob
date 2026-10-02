"""Guide price and bidding: the FIRST provider to accept the guide price books the job,
atomically; counters wait for the customer."""

import asyncio
import itertools

from app.repos import Bookings, JobRequests, Offers, Visits
from app.services import marketplace
from tests.conftest import make_settings, new_client, sign_in
from tests.factories import make_customer, make_provider, make_request


async def test_two_concurrent_accepts_exactly_one_wins(db, catalogue):
    customer = await make_customer(db)
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    req = await make_request(db, customer)
    s = make_settings()

    results = await asyncio.gather(
        marketplace.accept_at_guide(db, s, req.ref, dave),
        marketplace.accept_at_guide(db, s, req.ref, mike),
        return_exceptions=True,
    )
    for r in results:
        if not isinstance(r, marketplace.BookingOutcome) and getattr(r, "status_code", None) != 409:
            raise r
    wins = [r for r in results if isinstance(r, marketplace.BookingOutcome)]
    losses = [r for r in results if not isinstance(r, marketplace.BookingOutcome)]
    assert len(wins) == 1 and len(losses) == 1
    assert getattr(losses[0], "status_code", None) == 409
    assert losses[0].detail["code"] == "already_taken"
    assert await Bookings(db).count({"request_id": req.id}) == 1
    stored = await JobRequests(db).get(req.id)
    assert stored.status == "booked" and stored.booked.provider_id == wins[0].booking.provider_id


async def test_many_concurrent_accepts_over_http(app, db, catalogue):
    """Ten providers, each with their own session, race to accept the same request."""
    customer = await make_customer(db)
    req = await make_request(db, customer)
    clients = []
    for i in range(10):
        await make_provider(db, f"Provider Number{i}", f"+4477009003{i:02d}", ["mowing"])
        c = await new_client(app)
        await sign_in(c, db, f"+4477009003{i:02d}")
        clients.append(c)
    try:
        responses = await asyncio.gather(*(c.post(f"/api/p/requests/{req.ref}/accept") for c in clients))
    finally:
        for c in clients:
            await c.aclose()
    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [409] * 9, codes
    assert await Bookings(db).count({}) == 1
    winner = next(r.json() for r in responses if r.status_code == 200)
    assert winner["via"] == "guide" and winner["price_pence"] == 3100
    assert winner["provider_pence"] == 2635 and winner["fee_pence"] == 465


async def test_accept_creates_booking_series_visits_thread_and_messages(db, catalogue):
    customer = await make_customer(db)
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    req = await make_request(db, customer)  # fortnightly by default
    out = await marketplace.accept_at_guide(db, make_settings(), req.ref, dave)
    b = out.booking
    assert b.source == "platform" and b.recurring and b.frequency == "fortnightly" and b.series_id and b.thread_id
    visits = await Visits(db).for_booking(b.id)
    assert visits[0].is_first and len(visits) >= 3
    assert all((v2.local_date - v1.local_date).days == 14 for v1, v2 in itertools.pairwise(visits))
    t = {m["template_id"] async for m in db["outbox"].find({})}
    assert {"request_booked", "booking_confirmed"} <= t
    assert out.first_visit.scheduled_start.utcoffset().total_seconds() == 0, "UTC, always"
    confirmed = await db["outbox"].find_one({"template_id": "booking_confirmed"})
    assert "it's yours. Lawn mowing in Hazlemere. First visit " in confirmed["body"]


async def test_ineligible_provider_cannot_accept(db, catalogue):
    customer = await make_customer(db)
    no_skill = await make_provider(db, "Lorna Baines", "+447700900203", ["cleaning"])
    no_ladder = await make_provider(db, "Jan Kowalski", "+447700900204", ["gutters"], docs=["insurance"])
    req = await make_request(db, customer)
    gutters = await make_request(db, customer, "gutters")
    for provider, ref in ((no_skill, req.ref), (no_ladder, gutters.ref)):
        try:
            await marketplace.accept_at_guide(db, make_settings(), ref, provider)
            raise AssertionError("should have been refused")
        except Exception as e:
            assert getattr(e, "status_code", None) == 403
    assert (await JobRequests(db).get(req.id)).status == "open"


async def test_counter_then_customer_accepts(app, client, db, catalogue):
    customer = await make_customer(db)
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    req = await make_request(db, customer)
    async with await new_client(app) as mc:
        await sign_in(mc, db, "+447700900202")
        bad = await mc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3150, "reasons": []})
        assert bad.status_code == 422, "whole pounds only"
        r = await mc.post(
            f"/api/p/requests/{req.ref}/counter",
            json={"price_pence": 3700, "reasons": ["Tricky access"], "message": "The gate is narrow."},
        )
        assert r.status_code == 200, r.text
        offer = r.json()
    msg = await db["outbox"].find_one({"template_id": "counter_offer"})
    assert "Mike R. suggested £37" in msg["body"] and "instead of £31" in msg["body"]

    await sign_in(client, db, "+447700900123")
    r = await client.post(f"/api/c/offers/{offer['id']}/accept")
    assert r.status_code == 200, r.text
    assert r.json()["via"] == "counter" and r.json()["price_pence"] == 3700 and r.json()["provider_id"] == mike.id
    assert (await Offers(db).get(offer["id"])).status == "accepted"


async def test_guide_acceptance_beats_a_pending_counter(app, client, db, catalogue):
    customer = await make_customer(db)
    await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    req = await make_request(db, customer)
    async with await new_client(app) as mc:
        await sign_in(mc, db, "+447700900202")
        offer = (await mc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700})).json()
    await marketplace.accept_at_guide(db, make_settings(), req.ref, dave)
    assert (await Offers(db).get(offer["id"])).status == "lapsed"
    assert await db["outbox"].count_documents({"template_id": "job_taken"}) == 1
    await sign_in(client, db, "+447700900123")
    r = await client.post(f"/api/c/offers/{offer['id']}/accept")
    assert r.status_code == 409


async def test_keep_waiting_declines_and_tells_the_provider(app, client, db, catalogue):
    customer = await make_customer(db)
    await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    req = await make_request(db, customer)
    async with await new_client(app) as mc:
        await sign_in(mc, db, "+447700900202")
        offer = (await mc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700})).json()
    await sign_in(client, db, "+447700900123")
    r = await client.post(f"/api/c/offers/{offer['id']}/decline")
    assert r.status_code == 200 and r.json()["status"] == "declined"
    assert (await JobRequests(db).get(req.id)).status == "open"
    assert await db["outbox"].count_documents({"template_id": "counter_declined"}) == 1


async def test_customer_cannot_touch_someone_elses_offer(app, client, db, catalogue):
    customer = await make_customer(db)
    await make_customer(db, "Robert Brown", "+447700900130")
    await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    req = await make_request(db, customer)
    async with await new_client(app) as mc:
        await sign_in(mc, db, "+447700900202")
        offer = (await mc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700})).json()
    await sign_in(client, db, "+447700900130")
    assert (await client.post(f"/api/c/offers/{offer['id']}/accept")).status_code == 404


async def test_cover_request_reassigns_one_visit_without_a_new_booking(db, catalogue):
    """Time-off cover (L2 creates the request): accepting it hands that visit to the cover provider."""
    from app.models.job_requests import JobRequest

    customer = await make_customer(db)
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    req = await make_request(db, customer)
    s = make_settings()
    out = await marketplace.accept_at_guide(db, s, req.ref, dave)
    later = (await Visits(db).for_booking(out.booking.id))[2]
    cover = JobRequest.model_validate(
        {
            **req.model_dump(exclude={"id", "ref", "status", "booked", "events"}),
            "ref": "R-9001",
            "cover_for_visit_id": later.id,
            "guide_pence": later.price_pence,
        }
    )
    await JobRequests(db).insert(cover)
    try:
        await marketplace.accept_at_guide(db, s, "R-9001", dave)
        raise AssertionError("the regular provider can't cover their own visit")
    except Exception as e:
        assert getattr(e, "status_code", None) == 403
    bookings_before = await Bookings(db).count({})
    await marketplace.accept_at_guide(db, s, "R-9001", mike)
    v = await Visits(db).get(later.id)
    assert v.provider_id == mike.id and v.performer.kind == "cover" and v.cover.original_provider_id == dave.id
    assert v.price_pence == later.price_pence, "cover is at the same price"
    assert await Bookings(db).count({}) == bookings_before, "no new booking: the customer stays Dave's"
    assert await db["outbox"].count_documents({"template_id": "cover_coming"}) == 1


async def test_repair_task_finishes_an_interrupted_booking(db, catalogue):
    from app.shared.tasks import repair_claimed

    customer = await make_customer(db)
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    req = await make_request(db, customer)
    claimed = await marketplace.claim_request(db, req.id, provider_id=dave.id, price_pence=req.guide_pence, via="guide")
    assert claimed is not None and await Bookings(db).count({}) == 0  # crashed before booking
    await repair_claimed(db, make_settings())
    assert await Bookings(db).count({"request_id": req.id}) == 1
    await repair_claimed(db, make_settings())
    assert await Bookings(db).count({"request_id": req.id}) == 1, "idempotent"
