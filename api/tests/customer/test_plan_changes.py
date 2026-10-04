"""Ruling A10: changing a plan's frequency is re-priced from the pricing engine, keeping any
counter in proportion; the provider accepts or declines; unanswered for 48 hours it lapses.
The plan carries on unchanged until the provider accepts."""

import itertools
from datetime import timedelta

from app.adapters.area.base import AreaInput
from app.core import money
from app.core.ids import new_token, token_hash
from app.core.rounding import round_to_pound
from app.core.timeutil import utcnow
from app.customer import plan_changes
from app.models.provider_ops import OwnCustomerInvite
from app.repos import Bookings, OwnCustomerInvites, SeriesRepo, Visits
from app.repos.plan_changes import PlanChanges
from app.services import marketplace
from app.services.quotes import create_quote
from tests.conftest import make_settings, sign_in
from tests.customer.helpers import (
    address,
    book_at_guide,
    make_request_via_api,
    quote,
    request_body,
    signed_in_with_card,
)
from tests.factories import HAZLEMERE, make_provider


async def _engine_price(db, frequency: str, band: str = "large", category_id: str = "mowing") -> int:
    lawn = AreaInput(band=band) if category_id == "mowing" else None
    q = await create_quote(
        db, make_settings(), category_id=category_id, answers={"frequency": frequency}, lawn=lawn, address=HAZLEMERE,
        user_id=None,
    )  # fmt: skip
    return q.result.price_pence


async def _mowing_plan(client, db, counter_pence: int | None = None):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    if counter_pence:
        offer = await marketplace.make_counter(
            db, make_settings(), detail["ref"], dave, price_pence=counter_pence, reasons=[]
        )
        assert (await client.post(f"/api/c/offers/{offer.id}/accept")).status_code == 200
        booking = await Bookings(db).find_one({})
    else:
        booking = (await book_at_guide(db, detail["ref"], dave)).booking
    return dave, booking


def _token_from(body: str) -> str:
    return body.split("/plan-change/")[1].split()[0]


async def _preview(client, series_id: str, frequency: str) -> int:
    r = await client.get(f"/api/c/plans/{series_id}/reprice", params={"frequency": frequency})
    assert r.status_code == 200, r.text
    return r.json()["price_pence"]


async def _ask(client, db, series_id: str, frequency: str) -> str:
    price = await _preview(client, series_id, frequency)
    r = await client.patch(f"/api/c/plans/{series_id}", json={"frequency": frequency, "expected_price_pence": price})
    assert r.status_code == 200, r.text
    msg = await db["outbox"].find_one({"template_id": "plan_change_proposed"}, sort=[("created_at", -1), ("_id", -1)])
    return _token_from(msg["body"])


async def test_asking_reprices_and_waits_for_the_provider(client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db)
    sid = booking.series_id
    weekly = await _engine_price(db, "weekly")
    preview = (await client.get(f"/api/c/plans/{sid}/reprice", params={"frequency": "weekly"})).json()
    assert preview == {
        "frequency": "weekly",
        "frequency_label": "every week",
        "price_pence": weekly,
        "current_price_pence": 3100,
    }
    plan = (await client.get(f"/api/c/plans/{sid}")).json()
    assert [o["value"] for o in plan["frequency_options"]] == ["weekly", "fortnightly", "threeweekly"]
    before = sorted(v.local_date for v in await Visits(db).find({"series_id": sid, "status": "scheduled"}))

    r = await client.patch(f"/api/c/plans/{sid}", json={"frequency": "weekly", "expected_price_pence": weekly})
    assert r.status_code == 200
    out = r.json()
    assert out["frequency"] == "fortnightly" and out["price_pence"] == 3100, "unchanged until the provider accepts"
    assert out["pending_change"]["to_frequency"] == "weekly" and out["pending_change"]["to_price_pence"] == weekly
    series = await SeriesRepo(db).get(sid)
    assert (series.frequency, series.price_pence) == ("fortnightly", 3100)
    assert sorted(v.local_date for v in await Visits(db).find({"series_id": sid, "status": "scheduled"})) == before
    proposed = await db["outbox"].find_one({"template_id": "plan_change_proposed"})
    assert proposed["recipient"]["phone"] == "+447700900201"
    assert "would like their lawn mowing every week instead of every 2 weeks" in proposed["body"]
    assert f"the price would be £{weekly // 100} a visit (it's £31 now)" in proposed["body"]
    assert "/plan-change/" in proposed["body"]
    requested = await db["outbox"].find_one({"template_id": "plan_change_requested"})
    assert "Your plan carries on as it is unless they accept." in requested["body"]


async def test_at_the_minimum_price_weekly_costs_the_same_as_fortnightly(client, db, catalogue):
    """Session S, item 1c: weekly is discounted more than fortnightly (12% against 8%), so it's
    cheaper a visit, except on a lawn small enough that both fall below mowing's £28 minimum:
    then both guides are £28 and the plan's price doesn't change. (Margaret's £32 weekly price was
    this, at a lawn size her seeded plan never had: test_seed.py.)"""
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    await signed_in_with_card(client, db)
    q = await quote(client, "mowing", band="small", adjust="right")
    r = await client.post("/api/c/requests", json=request_body(q["id"]))
    assert r.status_code == 201, r.text
    booking = (await book_at_guide(db, r.json()["ref"], dave)).booking
    assert booking.price_pence == 2800
    assert await _engine_price(db, "weekly", band="small") == await _engine_price(db, "fortnightly", band="small")
    assert await _preview(client, booking.series_id, "weekly") == 2800
    assert await _engine_price(db, "weekly") < await _engine_price(db, "fortnightly")  # a large lawn


async def test_a_negotiated_price_stays_in_proportion_and_applies_on_acceptance(client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db, counter_pence=3700)
    sid = booking.series_id
    weekly = await _engine_price(db, "weekly")
    expected = round_to_pound(weekly * 3700 / 3100)  # the request's guide was £31
    token = await _ask(client, db, sid, "weekly")
    page = (await client.get(f"/api/c/plan-changes/{token}")).json()
    assert page["status"] == "pending" and page["to_price_pence"] == expected and page["from_price_pence"] == 3700
    assert page["provider_pence"] == money.split(expected, "standard", make_settings()).provider_pence

    r = await client.post(f"/api/c/plan-changes/{token}/accept")
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    series = await SeriesRepo(db).get(sid)
    assert (series.frequency, series.price_pence) == ("weekly", expected)
    b = await Bookings(db).get(booking.id)
    assert (b.frequency, b.price_pence) == ("weekly", expected)
    upcoming = await Visits(db).find({"series_id": sid, "status": "scheduled"}, sort=[("local_date", 1)])
    assert {(y.local_date - x.local_date).days for x, y in itertools.pairwise(upcoming)} == {7}
    assert all(v.price_pence == expected for v in upcoming if not v.is_first)
    accepted = await db["outbox"].find_one({"template_id": "plan_change_accepted"})
    assert f"Your lawn mowing is now every week at £{expected // 100} a visit." in accepted["body"]
    again = await client.post(f"/api/c/plan-changes/{token}/accept")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "change_accepted"


async def test_a_declined_change_leaves_the_plan_as_it_is(client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db)
    token = await _ask(client, db, booking.series_id, "threeweekly")
    r = await client.post(f"/api/c/plan-changes/{token}/decline")
    assert r.status_code == 200 and r.json()["status"] == "declined"
    series = await SeriesRepo(db).get(booking.series_id)
    assert (series.frequency, series.price_pence) == ("fortnightly", 3100)
    msg = await db["outbox"].find_one({"template_id": "plan_change_declined"})
    assert "would rather keep your lawn mowing every 2 weeks at £31 a visit" in msg["body"]
    assert (await client.get(f"/api/c/plans/{booking.series_id}")).json()["pending_change"] is None


async def test_an_unanswered_change_lapses_after_48_hours(client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db)
    token = await _ask(client, db, booking.series_id, "weekly")
    assert await plan_changes.lapse_stale(db, make_settings()) == 0
    await PlanChanges(db).coll.update_many({}, {"$set": {"expires_at": utcnow() - timedelta(minutes=1)}})
    assert await plan_changes.lapse_stale(db, make_settings()) == 1
    msg = await db["outbox"].find_one({"template_id": "plan_change_lapsed"})
    assert "hasn't answered within 48 hours, so your lawn mowing plan stays every 2 weeks at £31" in msg["body"]
    late = await client.post(f"/api/c/plan-changes/{token}/accept")
    assert late.status_code == 409 and late.json()["detail"]["code"] == "change_lapsed"
    assert (await SeriesRepo(db).get(booking.series_id)).frequency == "fortnightly"
    assert await plan_changes.lapse_stale(db, make_settings()) == 0


async def test_a_late_answer_lapses_the_change_even_before_the_task_runs(client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db)
    token = await _ask(client, db, booking.series_id, "weekly")
    await PlanChanges(db).coll.update_many({}, {"$set": {"expires_at": utcnow() - timedelta(minutes=1)}})
    assert (await client.get(f"/api/c/plan-changes/{token}")).json()["status"] == "lapsed"
    assert await db["outbox"].count_documents({"template_id": "plan_change_lapsed"}) == 1


async def test_frequencies_the_category_doesnt_offer_are_refused(client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db)
    r = await client.patch(
        f"/api/c/plans/{booking.series_id}", json={"frequency": "monthly", "expected_price_pence": 1}
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "frequency_not_offered"
    r = await client.patch(f"/api/c/plans/{booking.series_id}", json={"frequency": "fortnightly"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "same_frequency"
    r = await client.patch(f"/api/c/plans/{booking.series_id}", json={"frequency": "weekly"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "price_needed"
    assert await PlanChanges(db).count({}) == 0


async def test_asking_again_replaces_the_waiting_change(client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db)
    first = await _ask(client, db, booking.series_id, "weekly")
    second = await _ask(client, db, booking.series_id, "threeweekly")
    assert first != second
    r = await client.post(f"/api/c/plan-changes/{first}/accept")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "change_withdrawn"
    assert (await client.post(f"/api/c/plan-changes/{second}/accept")).status_code == 200
    assert (await SeriesRepo(db).get(booking.series_id)).frequency == "threeweekly"


async def test_cancelling_the_plan_withdraws_a_waiting_change(client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db)
    token = await _ask(client, db, booking.series_id, "weekly")
    assert (await client.post(f"/api/c/plans/{booking.series_id}/cancel")).status_code == 200
    r = await client.post(f"/api/c/plan-changes/{token}/accept")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "change_withdrawn"


async def _own_customer_plan(client, db):
    """Mary, Dave's own customer: £25 fortnightly mowing, from his invite."""
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    token = new_token(24)
    await OwnCustomerInvites(db).insert(
        OwnCustomerInvite(
            provider_id=dave.id, name="Mary Bishop", phone="+447700900140", category_id="mowing", price_pence=2500,
            frequency="fortnightly", token_hash=token_hash(token, make_settings().pepper),
        )
    )  # fmt: skip
    await signed_in_with_card(client, db, "+447700900140", "Mary Bishop")
    card = (
        await client.post(f"/api/c/invites/{token}/accept", json={"agree_terms": True, "address": address()})
    ).json()
    return dave, card["series_id"]


async def _ask_own(client, db, series_id: str, frequency: str = "weekly") -> str:
    r = await client.patch(f"/api/c/plans/{series_id}", json={"frequency": frequency})
    assert r.status_code == 200, r.text
    msg = await db["outbox"].find_one({"template_id": "plan_change_price_asked"}, sort=[("created_at", -1)])
    return _token_from(msg["body"])


async def test_an_own_customers_plan_is_never_repriced_by_the_engine(client, db, catalogue):
    """A22: the price of an own customer's plan is the provider's to set. Asking for another
    frequency asks Dave for a price; Mary approves it; the plan changes only then. Texts at each step."""
    dave, sid = await _own_customer_plan(client, db)
    plan = (await client.get(f"/api/c/plans/{sid}")).json()
    assert plan["provider_sets_price"] is True
    r = await client.get(f"/api/c/plans/{sid}/reprice", params={"frequency": "weekly"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "provider_sets_price"
    quotes_before = await db["quotes"].count_documents({})
    token = await _ask_own(client, db, sid)
    assert await db["quotes"].count_documents({}) == quotes_before, "the engine wasn't asked"
    asked = await db["outbox"].find_one({"template_id": "plan_change_price_asked"})
    assert asked["recipient"]["phone"] == "+447700900201"
    assert "As they're your own customer, you set the price: name it or decline by" in asked["body"]
    assert "/p/plan-change/" in asked["body"]
    told = await db["outbox"].find_one({"template_id": "plan_change_price_requested"})
    assert told["recipient"]["phone"] == "+447700900140" and "we've asked Dave H. for a price" in told["body"]
    plan = (await client.get(f"/api/c/plans/{sid}")).json()
    pending = plan["pending_change"]
    assert (pending["kind"], pending["awaiting"], pending["to_price_pence"]) == ("provider_price", "provider", None)
    assert (plan["frequency"], plan["price_pence"]) == ("fortnightly", 2500), "unchanged until agreed"

    page = (await client.get(f"/api/c/plan-changes/{token}")).json()
    assert (page["kind"], page["awaiting"], page["to_price_pence"], page["provider_pence"]) == (
        "provider_price",
        "provider",
        None,
        None,
    )
    assert (await client.post(f"/api/c/plan-changes/{token}/accept")).json()["detail"]["code"] == "name_a_price"
    preview = (await client.get(f"/api/c/plan-changes/{token}/preview", params={"price_pence": 2200})).json()
    assert preview == {
        "mode": "own_customer",
        "rate_percent": 5,
        "price_pence": 2200,
        "fee_pence": 110,
        "provider_pence": 2090,
    }
    low = (await client.get(f"/api/c/plan-changes/{token}/preview", params={"price_pence": 1000})).json()
    assert (low["fee_pence"], low["provider_pence"]) == (100, 900), "the own-customer fee's £1 minimum"
    bad = await client.post(f"/api/c/plan-changes/{token}/price", json={"price_pence": 2250})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "price_out_of_range"
    page = (await client.post(f"/api/c/plan-changes/{token}/price", json={"price_pence": 2200})).json()
    assert (page["awaiting"], page["to_price_pence"], page["provider_pence"]) == ("customer", 2200, 2090)
    priced = await db["outbox"].find_one({"template_id": "plan_change_priced"})
    assert priced["recipient"]["phone"] == "+447700900140"
    assert (
        "Dave H. can do your lawn mowing every week at £22 a visit (it's £25 now). Approve or decline" in priced["body"]
    )
    assert priced["body"].endswith("/account?tab=plan")
    again = await client.post(f"/api/c/plan-changes/{token}/price", json={"price_pence": 2000})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "with_customer"
    assert (await SeriesRepo(db).get(sid)).frequency == "fortnightly"

    pending = (await client.get(f"/api/c/plans/{sid}")).json()["pending_change"]
    change_id = pending["change_id"]
    # The commission at the new price is disclosed before Mary agrees (money.py: 5%, at least £1).
    assert (pending["split"]["fee_pence"], pending["split"]["provider_pence"], pending["split"]["rate_percent"]) == (
        110,
        2090,
        5,
    )
    stale = await client.post(f"/api/c/plans/{sid}/change/approve", json={"change_id": "an-older-one"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "price_change_changed"
    r = await client.post(f"/api/c/plans/{sid}/change/approve", json={"change_id": change_id})
    assert r.status_code == 200, r.text
    assert (r.json()["frequency"], r.json()["price_pence"], r.json()["pending_change"]) == ("weekly", 2200, None)
    upcoming = await Visits(db).find({"series_id": sid, "status": "scheduled"}, sort=[("local_date", 1)])
    assert {(y.local_date - x.local_date).days for x, y in itertools.pairwise(upcoming)} == {7}
    assert all(v.price_pence == 2200 for v in upcoming if not v.is_first)
    approved = await db["outbox"].find_one({"template_id": "plan_change_approved"})
    assert approved["recipient"]["phone"] == "+447700900201" and "Mary agreed £22 a visit" in approved["body"]
    agreed = await db["outbox"].find_one({"template_id": "plan_change_agreed"})
    assert "Your lawn mowing with Dave H. is now every week at £22 a visit." in agreed["body"]
    assert (await Bookings(db).get((await SeriesRepo(db).get(sid)).booking_id)).price_pence == 2200
    assert dave


async def test_the_provider_or_the_customer_can_keep_an_own_customers_plan_as_it_is(client, db, catalogue):
    _dave, sid = await _own_customer_plan(client, db)
    token = await _ask_own(client, db, sid)
    r = await client.post(f"/api/c/plan-changes/{token}/decline")
    assert r.status_code == 200 and r.json()["declined_by"] == "provider"
    told = await db["outbox"].find_one({"template_id": "plan_change_declined"})
    assert told["recipient"]["phone"] == "+447700900140"

    token = await _ask_own(client, db, sid, "threeweekly")
    await client.post(f"/api/c/plan-changes/{token}/price", json={"price_pence": 2700})
    change_id = (await client.get(f"/api/c/plans/{sid}")).json()["pending_change"]["change_id"]
    assert (await client.post(f"/api/c/plan-changes/{token}/decline")).json()["detail"]["code"] == "with_customer"
    r = await client.post(f"/api/c/plans/{sid}/change/decline", json={"change_id": change_id})
    assert r.status_code == 200 and r.json()["pending_change"] is None
    assert (r.json()["frequency"], r.json()["price_pence"]) == ("fortnightly", 2500)
    msg = await db["outbox"].find_one({"template_id": "plan_change_price_declined"})
    assert msg["recipient"]["phone"] == "+447700900201" and "Mary would rather keep" in msg["body"]
    page = (await client.get(f"/api/c/plan-changes/{token}")).json()
    assert (page["status"], page["declined_by"]) == ("declined", "customer")


async def test_each_wait_on_an_own_customers_change_lapses_after_48_hours(client, db, catalogue):
    _dave, sid = await _own_customer_plan(client, db)
    await _ask_own(client, db, sid)
    await PlanChanges(db).coll.update_many({}, {"$set": {"expires_at": utcnow() - timedelta(minutes=1)}})
    assert await plan_changes.lapse_stale(db, make_settings()) == 1
    assert await db["outbox"].count_documents({"template_id": "plan_change_lapsed"}) == 1  # Dave didn't price it

    token = await _ask_own(client, db, sid)
    await client.post(f"/api/c/plan-changes/{token}/price", json={"price_pence": 2200})
    change = await PlanChanges(db).pending_for(sid)
    assert change.expires_at > utcnow() + timedelta(hours=47), "the customer gets 48 hours from the price"
    await PlanChanges(db).coll.update_one({"_id": change.id}, {"$set": {"expires_at": utcnow() - timedelta(minutes=1)}})
    assert await plan_changes.lapse_stale(db, make_settings()) == 1
    lapsed = await db["outbox"].find_one({"template_id": "plan_change_price_lapsed"})
    assert lapsed["recipient"]["phone"] == "+447700900140" and "stays every 2 weeks at £25" in lapsed["body"]
    unanswered = await db["outbox"].find_one({"template_id": "plan_change_price_unanswered"})
    assert unanswered["recipient"]["phone"] == "+447700900201"
    late = await client.post(f"/api/c/plans/{sid}/change/approve", json={"change_id": change.id})
    assert late.status_code == 409 and (await SeriesRepo(db).get(sid)).frequency == "fortnightly"


async def test_plan_change_links_are_single_purpose_and_private(app, client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db)
    assert (await client.get("/api/c/plan-changes/not-a-token-at-all")).status_code == 404
    from tests.conftest import new_client

    async with await new_client(app) as other:
        await sign_in(other, db, "+447700900130", "Robert Brown")
        assert (
            await other.get(f"/api/c/plans/{booking.series_id}/reprice", params={"frequency": "weekly"})
        ).status_code in (403, 404)


async def test_a_change_priced_from_a_stale_plan_is_refused(client, db, catalogue):
    """Codex (high): the proposal is bound to the plan it was priced from. A change accepted
    between reading the plan and asking makes the new request a 409, not a mispriced proposal."""
    from app.repos import Customers, Users

    _dave, booking = await _mowing_plan(client, db, counter_pence=3700)
    stale_series = await SeriesRepo(db).get(booking.series_id)  # read before the acceptance below
    token = await _ask(client, db, booking.series_id, "weekly")
    assert (await client.post(f"/api/c/plan-changes/{token}/accept")).status_code == 200
    customer = await Customers(db).get(booking.customer_id)
    user = await Users(db).get(customer.user_id)
    try:
        # The price as the customer's stale page would have shown it, so it's the plan guard that refuses.
        price = (
            await plan_changes.reprice(db, make_settings(), stale_series, booking, "threeweekly", user.id)
        ).price_pence
        await plan_changes.request_change(
            db, make_settings(), stale_series, booking, customer, user, "threeweekly", price
        )
        raise AssertionError("should have been refused")
    except Exception as e:
        assert getattr(e, "status_code", None) == 409 and e.detail["code"] == "plan_changed"
    assert await PlanChanges(db).count({"status": "pending"}) == 0
    # Asked afresh, it's priced from the plan as it is now: the weekly guide is the reference.
    series = await SeriesRepo(db).get(booking.series_id)
    weekly, threeweekly = await _engine_price(db, "weekly"), await _engine_price(db, "threeweekly")
    preview = (await client.get(f"/api/c/plans/{series.id}/reprice", params={"frequency": "threeweekly"})).json()
    assert preview["price_pence"] == round_to_pound(threeweekly * series.price_pence / weekly)


async def test_acceptance_refuses_a_change_whose_plan_has_moved_on(client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db)
    token = await _ask(client, db, booking.series_id, "weekly")
    await SeriesRepo(db).update(booking.series_id, {"price_pence": 3300})  # however it moved on
    r = await client.post(f"/api/c/plan-changes/{token}/accept")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_changed"
    assert (await SeriesRepo(db).get(booking.series_id)).frequency == "fortnightly"


async def test_the_provider_is_only_sent_the_price_the_customer_saw(client, db, catalogue, monkeypatch):
    """Codex re-check (high): if pricing moves between the preview and Ask, nothing is sent; the
    customer gets the new price to look at first."""
    _dave, booking = await _mowing_plan(client, db)
    shown = await _preview(client, booking.series_id, "weekly")
    real = plan_changes.reprice

    async def dearer(*a, **kw):
        out = await real(*a, **kw)
        return out.__class__(**{**out.__dict__, "price_pence": out.price_pence + 900})  # a new pricing version

    monkeypatch.setattr(plan_changes, "reprice", dearer)
    r = await client.patch(
        f"/api/c/plans/{booking.series_id}", json={"frequency": "weekly", "expected_price_pence": shown}
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "price_changed"
    assert r.json()["detail"]["extra"]["price_pence"] == shown + 900
    assert await PlanChanges(db).count({}) == 0
    assert await db["outbox"].count_documents({"template_id": "plan_change_proposed"}) == 0


async def test_a_counter_accepted_after_an_approved_raise_keeps_its_own_guide(client, db, catalogue):
    """Codex third review (medium): A12 then A10. A £37 counter against the £31 guide, accepted
    after the customer approved a raise: re-pricing scales from £31 (the counter's guide), not the
    raised guide."""
    from app.core.db import transaction
    from app.customer import price_changes
    from app.models.common import Actor
    from app.repos import JobRequests, Users
    from app.services import guide_raises

    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    offer = await marketplace.make_counter(db, make_settings(), detail["ref"], dave, price_pence=3700, reasons=[])
    req = await JobRequests(db).by_ref(detail["ref"])

    async def raise_(session):
        return await guide_raises.propose(
            db,
            make_settings(),
            req,
            guide_pence=3700,
            first_pence=None,
            percent=20,
            note="",
            actor=Actor(),
            session=session,
        )

    await transaction(db, raise_)
    raised = await JobRequests(db).get(req.id)
    customer_user = await Users(db).by_phone("+447700900123")
    await price_changes.approve(db, make_settings(), raised, customer_user, raised.price_change.id)
    assert (await JobRequests(db).get(req.id)).guide_pence == 3700
    assert (await client.post(f"/api/c/offers/{offer.id}/accept")).status_code == 200
    booking = await Bookings(db).find_one({})
    weekly = await _engine_price(db, "weekly")
    assert await _preview(client, booking.series_id, "weekly") == round_to_pound(weekly * 3700 / 3100)
