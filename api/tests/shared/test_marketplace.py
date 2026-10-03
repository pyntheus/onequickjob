"""Guide price and bidding: the FIRST provider to accept the guide price books the job,
atomically; counters wait for the customer. Each action is one transaction: the claim, the
booking, its plan, visits and thread, lapsed counters and every message commit together or not
at all (decisions.md A7)."""

import asyncio
import itertools

import pytest

from app.core.db import transaction
from app.repos import Bookings, JobRequests, MessageThreads, Offers, SeriesRepo, Visits
from app.services import bookings as bookings_service
from app.services import marketplace, schedule
from tests.conftest import make_settings, new_client, sign_in
from tests.factories import make_customer, make_provider, make_request

BOOKING_MESSAGES = ("request_booked", "booking_confirmed")


async def _outbox(db, template_id: str) -> int:
    return await db["outbox"].count_documents({"template_id": template_id})


async def _exactly_one_booking_of_everything(db, req) -> None:
    """One booking for the request, its first visit and plan visits only, one thread, and each
    booking message once: whatever raced, nothing was duplicated."""
    assert await Bookings(db).count({}) == 1
    booking = await Bookings(db).by_request(req.id)
    assert booking is not None
    assert await Visits(db).count({"booking_id": {"$ne": booking.id}}) == 0
    assert await Visits(db).count({"booking_id": booking.id, "is_first": True}) == 1
    days = [v.local_date for v in await Visits(db).for_booking(booking.id)]
    assert len(days) == len(set(days)), "no visit twice on one day"
    assert await MessageThreads(db).count({}) == 1
    for t in BOOKING_MESSAGES:
        assert await _outbox(db, t) == 1, t


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
    assert losses[0].detail["code"] == "already_taken"
    stored = await JobRequests(db).get(req.id)
    assert stored.status == "booked" and stored.booked.provider_id == wins[0].booking.provider_id
    assert stored.booked.booking_id == wins[0].booking.id
    await _exactly_one_booking_of_everything(db, req)


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
    winner = next(r.json() for r in responses if r.status_code == 200)
    assert winner["via"] == "guide" and winner["price_pence"] == 3100
    assert winner["provider_pence"] == 2635 and winner["fee_pence"] == 465
    await _exactly_one_booking_of_everything(db, req)
    assert (await db["counters"].find_one({"_id": "booking"}))["seq"] == 1, "losers' booking refs rolled back"


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


def test_counter_first_visit_price_scales_by_the_same_ratio():
    """Ruling after F review (a): first = first-visit guide x counter / guide, half-up to whole pounds."""
    assert marketplace.scaled_first_price(2200, 3300, 2600) == 3900  # windows: £22/£33, counter £26
    assert marketplace.scaled_first_price(2000, 3000, 2100) == 3200  # £31.50 rounds half-up to £32
    assert marketplace.scaled_first_price(3100, 4200, 3700) == 5000  # £50.13 -> £50
    assert marketplace.scaled_first_price(3100, None, 3700) is None  # no dearer first visit


async def test_a_counter_on_a_job_with_a_dearer_first_visit(app, client, db, catalogue):
    customer = await make_customer(db)
    await make_provider(db, "Mike Reynolds", "+447700900202", ["windows"])
    req = await make_request(db, customer, "windows")  # £22 a clean, first £33
    assert (req.guide_pence, req.first_pence) == (2200, 3300)
    async with await new_client(app) as mc:
        await sign_in(mc, db, "+447700900202")
        offer = (await mc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 2600})).json()
        assert (offer["price_pence"], offer["first_price_pence"]) == (2600, 3900), "both prices on the offer"
        assert (offer["guide_pence"], offer["first_guide_pence"]) == (2200, 3300)
        ignored = await mc.post(
            f"/api/p/requests/{req.ref}/counter", json={"price_pence": 2600, "first_price_pence": 9900}
        )
        assert ignored.status_code == 422, "the first-visit price isn't the provider's to set"
    text = (await db["outbox"].find_one({"template_id": "counter_offer"}))["body"]
    assert "suggested £26 (first visit £39) for your window cleaning, instead of £22" in text
    await sign_in(client, db, "+447700900123")
    r = await client.post(f"/api/c/offers/{offer['id']}/accept")
    booking = await Bookings(db).get(r.json()["booking_id"])
    assert (booking.price_pence, booking.first_price_pence) == (2600, 3900)
    assert r.json()["first_visit"]["price_pence"] == 3900


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


async def test_guide_accept_books_the_dearer_first_visit(db, catalogue):
    customer = await make_customer(db)
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    req = await make_request(db, customer, answers={"grassState": "overgrown"})
    assert req.first_pence and req.first_pence > req.guide_pence
    out = await marketplace.accept_at_guide(db, make_settings(), req.ref, dave)
    assert (out.booking.price_pence, out.booking.first_price_pence) == (req.guide_pence, req.first_pence)
    assert out.first_visit.price_pence == req.first_pence
    later = (await Visits(db).for_booking(out.booking.id))[1]
    assert later.price_pence == req.guide_pence


def _fail_first(original, when=lambda *a, **k: True):
    """Wrap a coroutine function so its first matching call raises, as a crash would."""
    state = {"failed": False}

    async def wrapper(*args, **kwargs):
        if not state["failed"] and when(*args, **kwargs):
            state["failed"] = True
            raise RuntimeError("crash")
        return await original(*args, **kwargs)

    return wrapper


def _template_is(template_id):
    return lambda *args, **kwargs: args[1] == template_id


FAILURE_POINTS = {
    "plan": lambda mp: mp.setattr(SeriesRepo, "insert", _fail_first(SeriesRepo.insert)),
    "first_visit": lambda mp: mp.setattr(Visits, "insert", _fail_first(Visits.insert)),
    "horizon": lambda mp: mp.setattr(schedule, "ensure_horizon", _fail_first(schedule.ensure_horizon)),
    "thread": lambda mp: mp.setattr(MessageThreads, "insert", _fail_first(MessageThreads.insert)),
    "booking": lambda mp: mp.setattr(Bookings, "insert", _fail_first(Bookings.insert)),
    "booking_message": lambda mp: mp.setattr(
        marketplace, "notify", _fail_first(marketplace.notify, _template_is("booking_confirmed"))
    ),
    # Codex post-review (medium): a lapsed counter's job-taken notice can't be lost.
    "job_taken_notice": lambda mp: mp.setattr(
        marketplace, "notify", _fail_first(marketplace.notify, _template_is("job_taken"))
    ),
}


@pytest.mark.parametrize("where", FAILURE_POINTS)
async def test_a_failure_anywhere_in_booking_leaves_nothing_behind(app, db, catalogue, monkeypatch, where):
    """The claim, booking, plan, visits, thread, lapsed counter and messages are one
    transaction: a failure at any point undoes all of it, and accepting again books it once."""
    customer = await make_customer(db)
    await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    req = await make_request(db, customer)  # fortnightly: a plan and a horizon of visits
    async with await new_client(app) as mc:
        await sign_in(mc, db, "+447700900202")
        counter = (await mc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700})).json()
    FAILURE_POINTS[where](monkeypatch)

    with pytest.raises(RuntimeError, match="crash"):
        await marketplace.accept_at_guide(db, make_settings(), req.ref, dave)
    stored = await JobRequests(db).get(req.id)
    assert stored.status == "open" and stored.booked is None, "the claim was rolled back too"
    assert (await Offers(db).get(counter["id"])).status == "pending"
    for coll in ("bookings", "series", "visits", "message_threads"):
        assert await db[coll].count_documents({}) == 0, coll
    for t in (*BOOKING_MESSAGES, "job_taken"):
        assert await _outbox(db, t) == 0, t
    assert await db["counters"].find_one({"_id": "booking"}) is None, "no booking ref used up"

    await marketplace.accept_at_guide(db, make_settings(), req.ref, dave)  # the retry
    await _exactly_one_booking_of_everything(db, req)
    assert (await Offers(db).get(counter["id"])).status == "lapsed"
    assert await _outbox(db, "job_taken") == 1


async def test_a_counter_acceptance_racing_a_guide_acceptance_books_once(app, db, catalogue):
    customer = await make_customer(db)
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    req = await make_request(db, customer)
    async with await new_client(app) as mc:
        await sign_in(mc, db, "+447700900202")
        offer = (await mc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700})).json()
    s = make_settings()
    by_customer, by_dave = await asyncio.gather(
        marketplace.accept_counter(db, s, offer["id"], customer),
        marketplace.accept_at_guide(db, s, req.ref, dave),
        return_exceptions=True,
    )
    outcomes = [r for r in (by_customer, by_dave) if isinstance(r, marketplace.BookingOutcome)]
    errors = [r for r in (by_customer, by_dave) if not isinstance(r, marketplace.BookingOutcome)]
    assert len(outcomes) == 1 and len(errors) == 1 and errors[0].status_code == 409, (by_customer, by_dave)
    await _exactly_one_booking_of_everything(db, req)
    stored_offer = await Offers(db).get(offer["id"])
    if outcomes[0].via == "counter":
        assert outcomes[0].booking.provider_id == mike.id and stored_offer.status == "accepted"
        assert await _outbox(db, "job_taken") == 0
    else:
        assert outcomes[0].booking.provider_id == dave.id and stored_offer.status == "lapsed"
        assert await _outbox(db, "job_taken") == 1


async def test_a_counter_made_while_the_job_is_booked_never_stays_pending(db, catalogue):
    """The counter writes an event on the open request, so it can't slip in beside a booking."""
    customer = await make_customer(db)
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    s = make_settings()
    for _ in range(5):
        req = await make_request(db, customer)
        results = await asyncio.gather(
            marketplace.make_counter(db, s, req.ref, mike, price_pence=3700, reasons=[]),
            marketplace.accept_at_guide(db, s, req.ref, dave),
            return_exceptions=True,
        )
        for r in results:
            assert not isinstance(r, Exception) or getattr(r, "status_code", None) == 409, r
        assert (await JobRequests(db).get(req.id)).status == "booked"
        assert await Offers(db).count({"request_id": req.id, "status": "pending"}) == 0
        countered = await Offers(db).count({"request_id": req.id, "status": "lapsed"})
        assert (
            await db["outbox"].count_documents({"template_id": "job_taken", "related.request_id": req.id}) == countered
        )


async def test_accepting_a_counter_while_it_is_replaced(app, db, catalogue):
    """Offers are immutable: the customer gets the offer they accepted, or a 409, never a mix."""
    customer = await make_customer(db)
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    req = await make_request(db, customer)
    s = make_settings()
    first = await marketplace.make_counter(db, s, req.ref, mike, price_pence=3700, reasons=[])
    accepted, revised = await asyncio.gather(
        marketplace.accept_counter(db, s, first.id, customer),
        marketplace.make_counter(db, s, req.ref, mike, price_pence=5000, reasons=[]),
        return_exceptions=True,
    )
    if isinstance(accepted, marketplace.BookingOutcome):
        assert accepted.booking.price_pence == 3700 and revised.status_code == 409
        assert await Offers(db).count({"request_id": req.id, "status": "pending"}) == 0
    else:
        assert accepted.status_code == 409 and revised.price_pence == 5000
        assert (await Offers(db).get(first.id)).status == "withdrawn"
        assert (await JobRequests(db).get(req.id)).status == "open"


async def test_a_suspended_providers_counter_cannot_be_accepted(app, client, db, catalogue):
    """Eligibility is checked when the customer accepts, not just when the counter was made."""
    from app.repos import Providers

    customer = await make_customer(db)
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    req = await make_request(db, customer)
    offer = await marketplace.make_counter(db, make_settings(), req.ref, mike, price_pence=3700, reasons=[])
    await Providers(db).set_status(mike.id, "suspended", "test")
    await sign_in(client, db, "+447700900123")
    r = await client.post(f"/api/c/offers/{offer.id}/accept")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "provider_unavailable"
    assert r.json()["detail"]["message"] == "Mike can no longer take this job. We're still finding someone local."
    stored = await JobRequests(db).get(req.id)
    assert stored.status == "open", "still bookable by someone eligible"
    assert await Bookings(db).count({}) == 0
    # Ruling A9: the counter lapses, the request records it, the provider is told why.
    assert (await Offers(db).get(offer.id)).status == "lapsed"
    assert [e.offer_id for e in stored.events if e.kind == "counter_lapsed"] == [offer.id]
    msg = await db["outbox"].find_one({"template_id": "counter_lapsed"})
    assert msg["recipient"]["phone"] == "+447700900202"
    assert "Sarah tried to accept your price of £37 for the lawn mowing job in Hazlemere" in msg["body"]
    assert "Your account isn't active for new jobs." in msg["body"]
    again = await client.post(f"/api/c/offers/{offer.id}/accept")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "offer_not_pending"
    assert await db["outbox"].count_documents({"template_id": "counter_lapsed"}) == 1


async def test_a_counter_lapses_when_documents_run_out_inside_the_acceptance(db, catalogue, monkeypatch):
    """Ruling A9 when ineligibility is only seen inside the acceptance's transaction: the refused
    acceptance rolls back, then the lapse commits in a transaction of its own."""
    from app.repos import Providers

    customer = await make_customer(db)
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    req = await make_request(db, customer)
    s = make_settings()
    offer = await marketplace.make_counter(db, s, req.ref, mike, price_pence=3700, reasons=[])
    original = marketplace._provider_now

    async def insurance_runs_out(db_, provider_id, session):
        provider = await original(db_, provider_id, session)
        return provider.model_copy(update={"documents": [d for d in provider.documents if d.type != "insurance"]})

    monkeypatch.setattr(marketplace, "_provider_now", insurance_runs_out)
    with pytest.raises(Exception) as e:
        await marketplace.accept_counter(db, s, offer.id, customer)
    assert (e.value.status_code, e.value.detail["code"]) == (409, "provider_unavailable")
    assert (await Offers(db).get(offer.id)).status == "lapsed"
    assert (await JobRequests(db).get(req.id)).status == "open"
    assert (await Providers(db).get(mike.id)).last_booked_at is None, "the refused acceptance rolled back"
    assert (
        await Bookings(db).count({}) == 0 and await db["outbox"].count_documents({"template_id": "request_booked"}) == 0
    )
    assert await db["outbox"].count_documents({"template_id": "counter_lapsed"}) == 1


@pytest.mark.parametrize("path", ["guide", "counter"])
async def test_a_suspension_during_the_transaction_is_seen_by_its_retry(db, catalogue, monkeypatch, path):
    """Codex (high): eligibility is checked inside every attempt. A suspension that commits after
    an attempt began conflicts with it; the driver re-runs the attempt, which refuses."""
    from fastapi import HTTPException

    from app.repos import Providers

    customer = await make_customer(db)
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    req = await make_request(db, customer)
    s = make_settings()
    offer = await marketplace.make_counter(db, s, req.ref, mike, price_pence=3700, reasons=[])
    go, done = asyncio.Event(), asyncio.Event()

    async def admin_suspends():  # its own task, outside the transaction, like an admin's request
        await go.wait()
        await Providers(db).set_status(mike.id, "suspended", "test")
        done.set()

    admin = asyncio.create_task(admin_suspends())
    original, attempts = marketplace._provider_now, []

    async def provider_now(db_, provider_id, session):
        attempts.append(provider_id)
        if len(attempts) == 1:
            await JobRequests(db_).get(req.id, session=session)  # the attempt's snapshot starts here
            go.set()
            await done.wait()  # ... and the suspension commits after it
        return await original(db_, provider_id, session)

    monkeypatch.setattr(marketplace, "_provider_now", provider_now)
    with pytest.raises(HTTPException) as e:
        if path == "guide":
            await marketplace.accept_at_guide(db, s, req.ref, mike)
        else:
            await marketplace.accept_counter(db, s, offer.id, customer)
    await admin
    assert len(attempts) == 2, "the write conflict made the driver re-run the attempt"
    assert (e.value.status_code, e.value.detail["code"]) == (
        (403, "not_eligible") if path == "guide" else (409, "provider_unavailable")
    )
    assert (await JobRequests(db).get(req.id)).status == "open"
    # A refused counter acceptance lapses the counter (ruling A9); a refused guide acceptance leaves it alone.
    assert await Bookings(db).count({}) == 0
    assert (await Offers(db).get(offer.id)).status == ("pending" if path == "guide" else "lapsed")


async def _own_customer_cover(db):
    """Dave's own customer (£28 fortnightly mowing) with a cover request for a later visit."""
    from app.models.job_requests import JobRequest
    from tests.factories import HAZLEMERE

    customer = await make_customer(db, "Pat Green", "+447700900137")
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])

    async def book(session):
        return await bookings_service.create_booking(
            db,
            session=session,
            source="own_customer",
            via="invite",
            customer=customer,
            provider=dave,
            category_id="mowing",
            price_pence=2800,
            first_price_pence=None,
            unit="a visit",
            frequency="fortnightly",
            est_mins=38,
            first_est_mins=None,
            address=HAZLEMERE,
            answers={},
            notes="",
            days="weekdays",
            window="morning",
            invite_id="inv-pat",
        )

    booking, _ = await transaction(db, book)
    later = (await Visits(db).for_booking(booking.id))[2]
    req = await make_request(db, customer)
    cover = JobRequest.model_validate(
        {
            **req.model_dump(exclude={"id", "ref", "status", "booked", "events"}),
            "ref": "R-9101",
            "cover_for_visit_id": later.id,
            "guide_pence": later.price_pence,
            "first_pence": None,
        }
    )
    await JobRequests(db).insert(cover)
    await db["job_requests"].delete_one({"_id": req.id})
    return customer, dave, mike, later, cover


async def test_cover_acceptance_shows_the_cover_providers_terms_at_the_standard_fee(app, db, catalogue):
    """Codex post-review (medium): the response must use the covered visit and A4's fee."""
    _, _dave, mike, later, cover = await _own_customer_cover(db)
    async with await new_client(app) as mc:
        await sign_in(mc, db, "+447700900202")
        r = await mc.post(f"/api/p/requests/{cover.ref}/accept")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["provider_id"], body["provider_short"]) == (mike.id, "Mike R.")
    assert (body["price_pence"], body["fee_pence"], body["provider_pence"]) == (2800, 420, 2380)
    assert body["first_visit"]["id"] == later.id
    msg = await db["outbox"].find_one({"template_id": "booking_confirmed", "related.provider_id": mike.id})
    assert msg and "You'll get £23.80 one-off after the 15% OneQuickJob fee" in msg["body"]


async def test_cover_notices_are_written_with_the_reassignment_or_not_at_all(db, catalogue, monkeypatch):
    """Codex post-review (medium): a failed notice undoes the cover; taking it again sends each once."""
    _, dave, mike, later, cover = await _own_customer_cover(db)
    monkeypatch.setattr(marketplace, "notify", _fail_first(marketplace.notify, _template_is("cover_coming")))
    with pytest.raises(RuntimeError, match="crash"):
        await marketplace.accept_at_guide(db, make_settings(), cover.ref, mike)
    v = await Visits(db).get(later.id)
    assert v.provider_id == dave.id and v.cover.state != "covered", "the reassignment was rolled back"
    assert (await JobRequests(db).get(cover.id)).status == "open"

    await marketplace.accept_at_guide(db, make_settings(), cover.ref, mike)
    v = await Visits(db).get(later.id)
    assert v.provider_id == mike.id and v.performer.kind == "cover" and v.cover.original_provider_id == dave.id
    assert await _outbox(db, "cover_coming") == 1
    assert await db["outbox"].count_documents({"template_id": "booking_confirmed", "related.provider_id": mike.id}) == 1


async def test_a_visit_can_only_be_covered_once(db, catalogue):
    from app.models.job_requests import JobRequest

    _, _dave, mike, later, cover = await _own_customer_cover(db)
    jan = await make_provider(db, "Jan Kowalski", "+447700900204", ["mowing"])
    second = JobRequest.model_validate(
        {**cover.model_dump(exclude={"id", "ref", "status", "booked", "events"}), "ref": "R-9102"}
    )
    await JobRequests(db).insert(second)
    await marketplace.accept_at_guide(db, make_settings(), cover.ref, mike)
    with pytest.raises(Exception) as e:
        await marketplace.accept_at_guide(db, make_settings(), "R-9102", jan)
    assert e.value.status_code == 409
    assert (await JobRequests(db).get(second.id)).status == "open", "the second claim was undone"
    assert (await Visits(db).get(later.id)).provider_id == mike.id


async def test_a_cover_for_a_visit_no_longer_scheduled_cant_be_taken(db, catalogue, monkeypatch):
    """Contract-changes L2: cover acceptance checks, inside its transaction, that the visit is
    still scheduled. A visit the customer skips while its cover request is open can't be taken,
    even when the skip commits during the acceptance."""
    from app.core.timeutil import utcnow
    from app.repos import Providers

    _, _dave, mike, later, cover = await _own_customer_cover(db)
    real_update = Providers.update
    skipped = False

    async def update_then_skip(self, id_, set_, **kw):
        nonlocal skipped
        if not skipped:  # inside the acceptance's transaction: the customer skips the visit now
            skipped = True
            await db["visits"].update_one(
                {"_id": later.id}, {"$set": {"status": "skipped", "skipped_reason": "customer", "updated_at": utcnow()}}
            )
        return await real_update(self, id_, set_, **kw)

    monkeypatch.setattr(Providers, "update", update_then_skip)
    with pytest.raises(Exception) as e:
        await marketplace.accept_at_guide(db, make_settings(), cover.ref, mike)
    assert skipped and e.value.status_code == 409 and e.value.detail["code"] == "visit_not_scheduled"
    assert (await JobRequests(db).get(cover.id)).status == "open", "the claim was undone"
    v = await Visits(db).get(later.id)
    assert v.status == "skipped" and v.performer.kind == "provider" and v.cover.state != "covered"
    assert await _outbox(db, "cover_coming") == 0


async def test_helpers_never_accept_counter_or_price_a_job(app, db, catalogue):
    """A17: helper_of links a helper to the provider whose visits they do, and nothing more. The
    shared offer endpoints refuse a helper (even one holding every document) with helpers_cant."""
    from app.models.providers import Helper, ProviderDocument
    from app.models.users import User
    from app.repos import Providers, Users

    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    tom = User(name="Tom Hughes", phone="+447700900220", roles=[], helper_of=dave.id)
    await Users(db).insert(tom)
    docs = [
        ProviderDocument(type=t, status="verified", expires_on=dave.documents[0].expires_on)
        for t in ("identity", "insurance")
    ]
    helper = Helper(user_id=tom.id, name="Tom Hughes", status="ready", documents=docs)
    await Providers(db).update(dave.id, {}, push={"helpers": helper.model_dump(mode="python")})
    req = await make_request(db, await make_customer(db))
    async with await new_client(app) as tc:
        await sign_in(tc, db, "07700 900220")
        accept = await tc.post(f"/api/p/requests/{req.ref}/accept")
        counter = await tc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700})
    for r in (accept, counter):
        assert r.status_code == 403 and r.json()["detail"]["code"] == "helpers_cant", r.text
        assert r.json()["detail"]["message"].startswith("Dave takes on jobs and sets the prices.")
    assert (await JobRequests(db).get(req.id)).status == "open"
    assert await Offers(db).count({}) == 0
