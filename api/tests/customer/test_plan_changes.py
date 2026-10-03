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
from tests.customer.helpers import address, book_at_guide, make_request_via_api, signed_in_with_card
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


async def _ask(client, db, series_id: str, frequency: str) -> str:
    r = await client.patch(f"/api/c/plans/{series_id}", json={"frequency": frequency})
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

    r = await client.patch(f"/api/c/plans/{sid}", json={"frequency": "weekly"})
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
    r = await client.patch(f"/api/c/plans/{booking.series_id}", json={"frequency": "monthly"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "frequency_not_offered"
    r = await client.patch(f"/api/c/plans/{booking.series_id}", json={"frequency": "fortnightly"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "same_frequency"
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


async def test_an_own_customers_plan_scales_from_the_engines_price_now(client, db, catalogue):
    """No request on record: the reference guide is the engine's price at the current frequency
    (Medium band for a lawn with no size)."""
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
    expected = round_to_pound(
        await _engine_price(db, "weekly", "medium") * 2500 / await _engine_price(db, "fortnightly", "medium")
    )
    preview = (await client.get(f"/api/c/plans/{card['series_id']}/reprice", params={"frequency": "weekly"})).json()
    assert preview["price_pence"] == expected


async def test_plan_change_links_are_single_purpose_and_private(app, client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db)
    assert (await client.get("/api/c/plan-changes/not-a-token-at-all")).status_code == 404
    from tests.conftest import new_client

    async with await new_client(app) as other:
        await sign_in(other, db, "+447700900130", "Robert Brown")
        assert (
            await other.get(f"/api/c/plans/{booking.series_id}/reprice", params={"frequency": "weekly"})
        ).status_code in (403, 404)
