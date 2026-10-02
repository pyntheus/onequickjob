"""Guide price and bidding: the FIRST provider to accept the guide price books the job,
atomically; counters wait for the customer."""

import asyncio
import itertools

import pytest

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
    claimed = await marketplace.claim_request(
        db, req.id, provider_id=dave.id, price_pence=req.guide_pence, first_price_pence=None, via="guide"
    )
    assert claimed is not None and await Bookings(db).count({}) == 0  # crashed before booking
    await repair_claimed(db, make_settings())
    assert await Bookings(db).count({}) == 0, "fresh claims are left to the request that won them"
    from datetime import timedelta

    from app.core.timeutil import utcnow

    await db["job_requests"].update_one({"_id": req.id}, {"$set": {"booked.at": utcnow() - timedelta(minutes=5)}})
    await repair_claimed(db, make_settings())
    assert await Bookings(db).count({"request_id": req.id}) == 1
    await repair_claimed(db, make_settings())
    assert await Bookings(db).count({"request_id": req.id}) == 1, "idempotent"


FAILURE_POINTS = ["series", "first_visit", "horizon", "thread", "messages"]


@pytest.mark.parametrize("where", FAILURE_POINTS)
async def test_interrupted_booking_setup_is_resumed_by_the_repair_task(db, catalogue, monkeypatch, where):
    """Codex F-1: a crash after any write leaves a claimed request; repair finishes it exactly."""
    from datetime import timedelta

    from app.core.timeutil import utcnow
    from app.repos import MessageThreads, SeriesRepo
    from app.services import bookings as bookings_service
    from app.services import schedule
    from app.shared.tasks import repair_claimed

    customer = await make_customer(db)
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    req = await make_request(db, customer)  # fortnightly: series, horizon and all

    calls = {"n": 0}

    def boom_once(original):
        async def wrapper(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError(f"crash at {where}")
            return await original(*args, **kwargs)

        return wrapper

    targets = {
        "series": (SeriesRepo, "insert"),
        "first_visit": (Visits, "insert"),
        "horizon": (schedule, "ensure_horizon"),
        "thread": (MessageThreads, "insert"),
        "messages": (marketplace, "_notify_booked"),
    }
    obj, name = targets[where]
    monkeypatch.setattr(obj, name, boom_once(getattr(obj, name)))
    if where == "horizon":
        monkeypatch.setattr(bookings_service.schedule, "ensure_horizon", getattr(obj, name))

    with pytest.raises(RuntimeError):
        await marketplace.accept_at_guide(db, make_settings(), req.ref, dave)
    assert (await JobRequests(db).get(req.id)).status == "booked", "the claim itself stands"

    # The repair task leaves fresh claims for two minutes; age this one.
    await db["job_requests"].update_one({"_id": req.id}, {"$set": {"booked.at": utcnow() - timedelta(minutes=5)}})
    await repair_claimed(db, make_settings())
    await repair_claimed(db, make_settings())  # and it's a no-op once complete

    booking = await Bookings(db).by_request(req.id)
    assert booking.setup_complete and booking.confirmations_sent_at and booking.thread_id and booking.series_id
    assert await Bookings(db).count({}) == 1
    assert await Visits(db).count({"booking_id": booking.id, "is_first": True}) == 1
    assert await Visits(db).count({"booking_id": booking.id}) >= 3
    assert await MessageThreads(db).count({"booking_id": booking.id}) == 1
    assert await db["outbox"].count_documents({"template_id": "request_booked"}) == 1
    assert await db["outbox"].count_documents({"template_id": "booking_confirmed"}) == 1


async def test_a_revised_counter_cannot_change_what_the_customer_accepts(app, client, db, catalogue):
    """Codex F-2: offers are immutable; a re-send withdraws the old one."""
    customer = await make_customer(db)
    await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    req = await make_request(db, customer)
    async with await new_client(app) as mc:
        await sign_in(mc, db, "+447700900202")
        first = (await mc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700})).json()
        second = (await mc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 5000})).json()
    assert second["id"] != first["id"] and second["supersedes"] == first["id"]
    assert (await Offers(db).get(first["id"])).status == "withdrawn"
    assert (await Offers(db).get(first["id"])).price_pence == 3700, "the old terms are untouched"

    await sign_in(client, db, "+447700900123")
    stale = await client.post(f"/api/c/offers/{first['id']}/accept")
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "offer_not_pending"
    assert (await JobRequests(db).get(req.id)).status == "open"
    ok = await client.post(f"/api/c/offers/{second['id']}/accept")
    assert ok.status_code == 200 and ok.json()["price_pence"] == 5000


async def test_completion_uses_the_prices_frozen_in_the_claim(db, catalogue):
    customer = await make_customer(db)
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    req = await make_request(db, customer, answers={"grassState": "overgrown"})
    assert req.first_pence and req.first_pence > req.guide_pence
    claimed = await marketplace.claim_request(
        db, req.id, provider_id=dave.id, price_pence=req.guide_pence, first_price_pence=req.first_pence, via="guide"
    )
    # Anything changing on the request afterwards must not leak into the booking.
    await db["job_requests"].update_one({"_id": req.id}, {"$set": {"guide_pence": 9900, "first_pence": 9900}})
    out = await marketplace.complete_claimed(db, make_settings(), claimed)
    assert (out.booking.price_pence, out.booking.first_price_pence) == (req.guide_pence, req.first_pence)
    assert out.first_visit.price_pence == req.first_pence


async def test_a_counter_with_its_own_first_visit_price(app, client, db, catalogue):
    customer = await make_customer(db)
    await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    req = await make_request(db, customer)
    async with await new_client(app) as mc:
        await sign_in(mc, db, "+447700900202")
        offer = (
            await mc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3500, "first_price_pence": 4500})
        ).json()
    await sign_in(client, db, "+447700900123")
    r = await client.post(f"/api/c/offers/{offer['id']}/accept")
    booking = await Bookings(db).get(r.json()["booking_id"])
    assert (booking.price_pence, booking.first_price_pence) == (3500, 4500)
    assert r.json()["first_visit"]["price_pence"] == 4500


async def test_guide_accept_fails_if_the_guide_changed_since_it_was_read(db, catalogue):
    customer = await make_customer(db)
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    req = await make_request(db, customer)
    stale = await marketplace.claim_request(
        db,
        req.id,
        provider_id=dave.id,
        price_pence=req.guide_pence,
        first_price_pence=None,
        via="guide",
        expect_guide_pence=req.guide_pence - 100,
    )
    assert stale is None and (await JobRequests(db).get(req.id)).status == "open"
