"""The earnings limit: only the limit is stored, never the benefits answer; it filters job
alerts and marks jobs that would go over it."""

from app.core import money
from app.core.timeutil import utcnow
from app.repos import Providers
from app.services import ledger
from app.services.eligibility import alert_targets
from tests.factories import make_customer, make_request
from tests.provider.conftest import book


async def test_only_the_limit_is_stored_never_the_benefits_answer(dave_client, db, dave):
    r = await dave_client.put("/api/p/limit", json={"on": True, "period": "month", "amount_pence": 30000})
    assert r.status_code == 200, r.text
    assert r.json()["on"] and r.json()["period"] == "month" and r.json()["amount_pence"] == 30000
    raw = await db["providers"].find_one({"_id": dave.id})
    assert raw["earnings_limit"] == {"on": True, "period": "month", "amount_pence": 30000}
    for field in ("benefit", "benefits", "pension_credit"):
        bad = await dave_client.put(
            "/api/p/limit", json={"on": True, "period": "week", "amount_pence": 25000, field: "pc"}
        )
        assert bad.status_code == 422, "a benefits answer is refused, not quietly dropped"
    raw = await db["providers"].find_one({"_id": dave.id})
    assert raw["earnings_limit"] == {"on": True, "period": "month", "amount_pence": 30000}
    assert "benefit" not in str(raw).lower()


async def test_limit_preview_works_out_a_draft_without_saving_it(dave_client, db, world):
    v = world.first
    split = money.split_for_visit(v.price_pence, v.source, v.performer.kind)
    await ledger.record_charge(db, v, split, at=utcnow(), gateway="fake", charge_id="ch_1")
    r = await dave_client.get("/api/p/limit/preview", params={"period": "week", "amount_pence": 5000})
    p = r.json()
    assert p["earned_pence"] == 2550 and p["remaining_pence"] == 2450 and p["used_percent"] == 51
    assert not p["reached"]
    reached = (await dave_client.get("/api/p/limit/preview", params={"period": "week", "amount_pence": 2500})).json()
    assert reached["reached"] and reached["remaining_pence"] == 0 and reached["used_percent"] == 100
    assert (await Providers(db).get(world.dave.id)).earnings_limit.on is False, "nothing was saved"


async def test_a_reached_limit_stops_job_alerts_and_a_near_one_marks_the_job(dave_client, db, world, catalogue):
    """The limit filter: alert_targets (the broadcast, L1) leaves out a provider at their limit;
    the job list marks jobs that would take them over it."""
    customer = await make_customer(db, "Robert Brown", "+447700900131")
    req = await make_request(db, customer)
    cat = catalogue["mowing"]
    assert [t.provider.id for t in await alert_targets(db, req, cat)] == [world.dave.id]

    await dave_client.put("/api/p/limit", json={"on": True, "period": "week", "amount_pence": 3000})
    card = next(c for c in (await dave_client.get("/api/p/jobs")).json() if c["request_ref"] == req.ref)
    assert card["over_limit"] is False  # £26.35 fits in £30

    v = world.first
    await ledger.record_charge(
        db,
        v,
        money.split_for_visit(v.price_pence, v.source, v.performer.kind),
        at=utcnow(),
        gateway="fake",
        charge_id="ch_1",
    )  # £25.50 earned: £4.50 left
    card = next(c for c in (await dave_client.get("/api/p/jobs")).json() if c["request_ref"] == req.ref)
    assert card["over_limit"] is True
    assert [t.provider.id for t in await alert_targets(db, req, cat)] == [world.dave.id], "still has headroom"

    _, v2 = await book(db, world.customer, world.dave, price=1000)
    await ledger.record_charge(
        db, v2, money.split_for_visit(1000, "platform", "provider"), at=utcnow(), gateway="fake", charge_id="ch_2"
    )  # £34 earned: limit reached
    assert (await dave_client.get("/api/p/limit")).json()["reached"]
    assert await alert_targets(db, req, cat) == [], "no alerts once the limit is reached"


async def test_limit_amounts_are_checked(dave_client, db, dave):
    for amount in (400, 600_000):
        r = await dave_client.put("/api/p/limit", json={"on": True, "period": "week", "amount_pence": amount})
        assert r.status_code == 422
