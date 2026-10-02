"""make seed: idempotent, and the demo data the lanes rely on is there and consistent."""

from datetime import UTC, datetime

import pytest

from app.core import money
from app.repos import Categories, PricingVersions, Providers, Users
from app.seed.__main__ import main_async
from app.seed.context import sid
from app.seed.run import SUMMARY_COLLECTIONS, seed
from app.services.eligibility import can_take
from tests.conftest import make_settings

# A fixed "now" (a Friday) so both runs in the idempotency test see the same clock.
NOW = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
SAMPLE = {
    "users": [sid("user", "dave"), sid("user", "sarah")],
    "customers": [sid("customer", "sarah")],
    "providers": [sid("provider", "dave"), sid("provider", "alan")],
    "job_requests": [sid("request", "R-2292"), sid("request", "R-2288")],
    "quotes": [sid("quote", "R-2292")],
    "offers": [sid("offer", "R-2288", "gary")],
    "bookings": [sid("booking", "regular:margaret"), sid("booking", "cal:40")],
    "series": [sid("series", "margaret")],
    "visits": [sid("visit", "cal:40"), sid("visit", "past:sarah_mow_2")],
    "ledger_entries": [sid("ledger", "cal:0")],
    "disputes": [sid("dispute", "D-013")],
    "message_threads": [sid("thread", "past:sarah_mow_2")],
}


async def _wipe(db) -> None:
    for name in await db.list_collection_names():
        await db[name].delete_many({})


@pytest.fixture(scope="module")
async def seeded(app):
    db = app.state.db
    await _wipe(db)
    summary = await seed(db, make_settings(), now=NOW)
    return db, summary


async def _snapshot(db) -> tuple[dict[str, int], dict[str, list[dict]]]:
    counts = {n: await db[n].count_documents({}) for n in SUMMARY_COLLECTIONS}
    docs = {c: [await db[c].find_one({"_id": i}) for i in ids] for c, ids in SAMPLE.items()}
    return counts, docs


async def test_seeding_twice_changes_nothing(seeded):
    db, _ = seeded
    before = await _snapshot(db)
    await seed(db, make_settings(), now=NOW)
    after = await _snapshot(db)
    assert after[0] == before[0], "per-collection counts must not change"
    for collection, docs in before[1].items():
        assert all(d is not None for d in docs), f"missing seeded {collection}"
        assert after[1][collection] == docs, f"{collection} documents changed on re-seed"


async def test_reseeding_keeps_what_people_created(seeded):
    db, _ = seeded
    await db["job_requests"].insert_one({"_id": "user-made", "ref": "R-2301", "status": "open"})
    await seed(db, make_settings(), now=NOW)
    assert await db["job_requests"].find_one({"_id": "user-made"})
    await db["job_requests"].delete_one({"_id": "user-made"})


async def test_catalogue_and_one_live_pricing_version(seeded):
    db, _ = seeded
    live = await Categories(db).live()
    assert len(live) == 15
    versions = await PricingVersions(db).find({"status": "live"})
    assert [v.version for v in versions] == [1]


async def test_demo_users(seeded):
    db, summary = seeded
    users = {u.demo_key: u for u in await Users(db).demo_users()}
    assert {"sarah", "dave", "mike", "ken", "tom", "admin_jo", "admin_sam"} <= set(users)
    assert users["sarah"].phone == "+447700900123" and users["sarah"].roles == ["customer"]
    assert "provider" in users["dave"].roles
    assert [k for k, u in users.items() if "admin" in u.roles] == ["admin_jo", "admin_sam"]
    dave = await Providers(db).by_user(users["dave"].id)
    assert users["tom"].helper_of == dave.id and dave.helpers[0].name == "Tom Hughes"
    assert "mary" not in users, "Mary is only invited, not a user yet"
    assert {d[0] for d in summary["demo_users"]} == set(users)


async def test_dave_can_take_and_is_alerted_about_his_three_jobs(seeded):
    db, _ = seeded
    dave = await Providers(db).get(sid("provider", "dave"))
    cats = {c.id: c for c in await Categories(db).all()}
    for ref in ("R-2292", "R-2293", "R-2294"):
        req = await db["job_requests"].find_one({"ref": ref})
        assert req["status"] == "open"
        assert can_take(dave, cats[req["category_id"]], NOW.date()).ok
        assert dave.id in req["broadcast"]["provider_ids"]
        alert = await db["outbox"].find_one(
            {"template_id": "job_alert", "recipient.user_id": dave.user_id, "related.request_id": req["_id"]}
        )
        assert alert and f"/p/j/{ref}?t=" in alert["body"]
    mowing = await db["outbox"].find_one(
        {"template_id": "job_alert", "related.request_id": sid("request", "R-2292"), "recipient.user_id": dave.user_id}
    )
    assert "Guide price £31, you'd get £26.35" in mowing["body"]


async def test_open_requests_and_guides(seeded):
    db, _ = seeded
    guides = {r["ref"]: r["guide_pence"] async for r in db["job_requests"].find({"status": "open"})}
    assert guides == {"R-2291": 7200, "R-2288": 11000, "R-2284": 2800, "R-2292": 3100, "R-2293": 6100, "R-2294": 8800}
    r2284 = await db["job_requests"].find_one({"ref": "R-2284"})
    assert r2284["broadcast"]["provider_ids"] == [], "nobody within 4 miles of Princes Risborough"
    gary = await db["offers"].find_one({"_id": sid("offer", "R-2288", "gary")})
    assert gary["status"] == "pending" and gary["price_pence"] == 15000


async def test_calibration_visits(seeded):
    db, _ = seeded
    finished = await db["visits"].count_documents(
        {"status": "finished", "minutes_actual": {"$gt": 0}, "est_mins": {"$gt": 0}}
    )
    assert finished >= 72
    cal = [v async for v in db["visits"].find({"_id": {"$in": [sid("visit", f"cal:{i}") for i in range(72)]}})]
    assert len(cal) == 72
    assert sum(v["is_first"] for v in cal) == 12
    for v in cal:
        assert v["overrun"] == (v["minutes_actual"] * 10 > v["est_mins"] * 11)
    first = await db["visits"].find_one({"_id": sid("visit", "cal:0")})
    assert (first["est_mins"], first["minutes_actual"]) == (41, 42), "CAL_POINTS[0] from the prototype"
    assert await db["bookings"].count_documents({"via": "counter"}) > 0


async def test_ledger_is_consistent_with_money_py(seeded):
    db, _ = seeded
    n = 0
    async for e in db["ledger_entries"].find({}):
        n += 1
        assert e["gross_pence"] == e["fee_pence"] + e["net_pence"]
        split = money.split_for_source(e["gross_pence"], e["source"])
        assert (e["fee_pence"], e["net_pence"]) == (split.fee_pence, split.provider_pence)
        visit = await db["visits"].find_one({"_id": e["visit_id"]})
        assert visit["charge"]["status"] == "succeeded" and visit["charge"]["fee_pence"] == e["fee_pence"]
    assert n >= 100


async def test_disputes(seeded):
    db, _ = seeded
    stages = {d["ref"]: d["stage"] async for d in db["disputes"].find({})}
    assert stages == {"D-011": 3, "D-013": 2, "D-014": 1}
    d011 = await db["disputes"].find_one({"ref": "D-011"})
    visit = await db["visits"].find_one({"_id": d011["visit_id"]})
    assert visit["performer"]["kind"] == "cover" and d011["closed_at"]


async def test_own_customer_invites(seeded):
    db, _ = seeded
    statuses = sorted([i["status"] async for i in db["own_customer_invites"].find({})])
    assert statuses == ["accepted", "accepted", "blocked", "blocked", "invited"]
    mary = await db["own_customer_invites"].find_one({"name": "Mary Bishop"})
    assert mary["status"] == "invited" and mary["token_hash"]
    msg = await db["outbox"].find_one({"_id": mary["outbox_id"]})
    assert "/invite/" in msg["body"] and "£25 a visit" in msg["body"]
    blocked = await db["own_customer_invites"].find_one({"phone": "+447700900123"})
    assert blocked["status"] == "blocked"


async def test_refuses_a_database_that_isnt_ours():
    with pytest.raises(ValueError, match="oqj"):
        await main_async([], settings=make_settings(mongo_db="production"))
