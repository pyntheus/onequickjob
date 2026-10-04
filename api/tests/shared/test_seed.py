"""make seed: idempotent, and the demo data the lanes rely on is there and consistent."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.core import money
from app.models.categories import DocumentType
from app.repos import Categories, PricingVersions, Providers, Users
from app.seed.__main__ import main_async
from app.seed.context import sid
from app.seed.run import SUMMARY_COLLECTIONS, seed
from app.services.eligibility import can_take
from tests.conftest import make_settings

# A fixed "now" (a Friday) so both runs in the idempotency test see the same clock.
NOW = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
DBS_TYPE = DocumentType(id="dbs_basic", label="Basic DBS check", expires=True, valid_months=12)
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


# Whose ids are minted fresh each run (outbox messages written through notify, magic links).
FRESH_IDS = {"outbox", "magic_links"}


async def _everything(db) -> dict[str, list[dict]]:
    out = {}
    for name in sorted(await db.list_collection_names()):
        docs = await db[name].find({}).sort("_id", 1).to_list()
        out[name] = [len(docs)] if name in FRESH_IDS else docs
    return out


async def test_seeding_twice_changes_nothing(seeded):
    """A21: a second run leaves exactly the same state, document for document (outbox messages
    and magic links are minted with fresh ids and tokens, so only their numbers are compared;
    invite tokens are fresh too)."""
    db, _ = seeded
    before = await _snapshot(db)
    everything = await _everything(db)
    await seed(db, make_settings(), now=NOW)
    after = await _snapshot(db)
    assert after[0] == before[0], "per-collection counts must not change"
    for collection, docs in before[1].items():
        assert all(d is not None for d in docs), f"missing seeded {collection}"
        assert after[1][collection] == docs, f"{collection} documents changed on re-seed"
    again = await _everything(db)
    assert set(again) == set(everything)
    for name, docs in everything.items():
        if name == "own_customer_invites":  # Mary's link carries a fresh token each run
            docs = [{**d, "token_hash": None, "outbox_id": None} for d in docs]
            again[name] = [{**d, "token_hash": None, "outbox_id": None} for d in again[name]]
        assert again[name] == docs, f"{name} changed on re-seed"


async def test_reseeding_removes_everything_demo_runs_created(seeded):
    """A21 (contract-changes L1 14, L2): make seed resets the demo. What demo runs create goes
    (ledger entries, mileage, time off, cover requests, plan changes, payment attempts, events and
    refunds, sign-ups, messages...); admins' pricing versions and their audit entries, admins
    outside the seed and the sessions of people who remain are kept."""
    from app.core.timeutil import utcnow

    db, _ = seeded
    now = utcnow()
    made = {
        "ledger_entries": {"_id": "demo-ledger", "provider_id": sid("provider", "dave"), "gross_pence": 3100},
        "mileage_logs": {"_id": "demo-mileage", "provider_id": sid("provider", "dave")},
        "time_off": {"_id": "demo-time-off", "provider_id": sid("provider", "dave"), "status": "planned"},
        "job_requests": {"_id": "demo-cover", "ref": "R-2301", "cover_for_visit_id": "v", "status": "open"},
        "plan_changes": {"_id": "demo-plan-change", "series_id": sid("series", "margaret"), "status": "pending"},
        "payment_attempts": {"_id": "visit:x:visit:1"},
        "payment_events": {"_id": "evt_demo"},
        "payment_refunds": {"_id": "demo-refund"},
        "bookings": {"_id": "demo-booking", "invite_id": sid("invite", "mary")},
        "series": {"_id": "demo-series", "booking_id": "demo-booking"},
        "visits": {"_id": "demo-visit", "booking_id": "demo-booking"},
        "ratings": {"_id": "demo-rating", "visit_id": sid("visit", "cal:40")},
        "users": {"_id": "demo-user", "phone": "+447700900140", "roles": ["customer"]},
        "customers": {"_id": "demo-customer", "user_id": "demo-user"},
        "outbox": {"_id": "demo-message", "template_id": "request_sent"},
        "files": {"_id": "demo-file"},
        "fake_gateway": {"_id": "ch_demo", "kind": "charge"},
        "counters": {"_id": "request", "seq": 7},
        "audit_log": {"_id": "demo-audit", "action": "provider.suspended"},
    }
    kept = {
        "pricing_versions": {"_id": "admins-draft", "version": 2, "status": "draft"},
        "audit_log": {"_id": "pricing-audit", "action": "pricing.drafted"},
        "users": {"_id": "hasan", "phone": "+447700900999", "roles": ["admin"]},
    }
    for name, doc in made.items():
        await db[name].insert_one(doc)
    for name, doc in kept.items():
        await db[name].insert_one(doc)
    # An admin made while a seeded person was missing, with their number, doesn't survive: the seed
    # needs the number back.
    await db["users"].delete_one({"_id": sid("user", "sarah")})
    await db["users"].insert_one({"_id": "clashing-admin", "phone": "+447700900123", "roles": ["admin"]})
    await db["sessions"].insert_many(
        [
            {"_id": "s-sarah", "user_id": sid("user", "sarah"), "created_at": now},
            {"_id": "s-demo", "user_id": "demo-user", "created_at": now},
            {"_id": "s-hasan", "user_id": "hasan", "created_at": now},
        ]
    )
    summary = await seed(db, make_settings(), now=NOW)
    for name, doc in made.items():
        assert await db[name].find_one({"_id": doc["_id"]}) is None, f"{name} from a demo run survived"
    for name, doc in kept.items():
        assert await db[name].find_one({"_id": doc["_id"]}), f"{name} should be kept"
    assert {d["_id"] async for d in db["sessions"].find({})} == {"s-sarah", "s-hasan"}
    assert await db["users"].find_one({"_id": "clashing-admin"}) is None
    assert summary["removed"]["ledger_entries"] == 1 and summary["removed"]["sessions"] == 1
    for name, doc in kept.items():  # put the module's seed back as it was
        await db[name].delete_one({"_id": doc["_id"]})
    await db["sessions"].delete_many({})


async def test_marys_invite_can_be_accepted_after_every_reseed(app, seeded):
    """Contract-changes L1 item 14: after Mary accepts in a demo, make seed puts her invite back
    and it can be accepted again (her booking, plan, visits and sign-up from the last run are gone)."""
    from tests.conftest import new_client, sign_in
    from tests.customer.helpers import address

    db, _ = seeded
    for _ in range(2):
        invite = await db["own_customer_invites"].find_one({"_id": sid("invite", "mary")})
        msg = await db["outbox"].find_one({"_id": invite["outbox_id"]})
        token = msg["body"].split("/invite/")[1].split()[0]
        async with await new_client(app) as c:
            await sign_in(c, db, "07700 900140", "Mary Bishop")
            setup = (await c.post("/api/c/payment/setup")).json()
            await c.post(f"/api/c/payment/setup/{setup['setup_id']}/confirm")
            r = await c.post(f"/api/c/invites/{token}/accept", json={"agree_terms": True, "address": address()})
            assert r.status_code == 201, r.text
        assert await db["bookings"].count_documents({"invite_id": sid("invite", "mary")}) == 1
        await seed(db, make_settings(), now=NOW)
        assert await db["bookings"].count_documents({"invite_id": sid("invite", "mary")}) == 0
        assert (await db["own_customer_invites"].find_one({"_id": sid("invite", "mary")}))["status"] == "invited"


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
        visit = await db["visits"].find_one({"_id": e["visit_id"]})
        split = money.split_for_visit(e["gross_pence"], e["source"], visit["performer"]["kind"])
        assert (e["fee_pence"], e["net_pence"]) == (split.fee_pence, split.provider_pence)
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


async def test_seed_dates_are_relative_to_the_moment_of_seeding(app):
    """Ruling after F review (e): the demo never goes stale."""
    from app.core.timeutil import to_london
    from app.services.documents import expiry_for

    db = app.state.db
    for now in (NOW, NOW + timedelta(days=150)):
        await _wipe(db)
        await seed(db, make_settings(), now=now)
        today = to_london(now).date()

        async def expiry(key: str, doc_type: str) -> date:
            p = await db["providers"].find_one({"_id": sid("provider", key)})
            d = next(d for d in p["documents"] if d["type"] == doc_type)
            return date.fromisoformat(d["expires_on"])

        assert (await expiry("alan", "insurance") - today).days == 9
        assert (await expiry("gary", "insurance") - today).days == 48
        lorna = await db["providers"].find_one({"_id": sid("provider", "lorna")})
        dbs = next(d for d in lorna["documents"] if d["type"] == "dbs_basic")
        assert dbs["issued_on"] and dbs["expires_on"]
        assert date.fromisoformat(dbs["expires_on"]) == expiry_for(DBS_TYPE, date.fromisoformat(dbs["issued_on"]), None)
        assert 0 < (date.fromisoformat(dbs["expires_on"]) - today).days <= 30, "inside the reminder window"
    await _wipe(db)  # put back the module fixture's seed for the tests that follow
    await seed(db, make_settings(), now=NOW)


async def test_every_seeded_dbs_check_runs_twelve_months(seeded):
    from app.services.documents import expiry_for

    db, _ = seeded
    n = 0
    async for p in db["providers"].find({"documents.type": "dbs_basic"}):
        for d in p["documents"]:
            if d["type"] == "dbs_basic":
                n += 1
                assert d["expires_on"] == expiry_for(DBS_TYPE, date.fromisoformat(d["issued_on"]), None).isoformat()
    assert n >= 7


async def test_margarets_weekly_reprice_is_cheaper_per_visit(seeded):
    """Session S, item 1c. Margaret's plan used to be seeded with no request, so no lawn size was
    on record and A10 re-priced it at the medium band, where both the fortnightly and the weekly
    guide fall below mowing's £28 minimum: the ratio was 1 and weekly came out at £32, the same as
    fortnightly. Her plan now comes from a booked request (Large band, Dave's £32 counter on the
    £31 guide), so weekly is the engine's weekly guide scaled by her counter."""
    from app.customer import plan_changes
    from app.repos import Bookings, JobRequests, Offers, SeriesRepo

    db, _ = seeded
    series = await SeriesRepo(db).get(sid("series", "margaret"))
    booking = await Bookings(db).get(series.booking_id)
    req = await JobRequests(db).get(booking.request_id)
    offer = await Offers(db).get(req.booked.offer_id)
    assert (series.price_pence, series.frequency) == (3200, "fortnightly")
    assert booking.via == "counter" and req.measure.band == "large" and req.status == "booked"
    assert (offer.price_pence, offer.guide_pence, offer.status) == (3200, 3100, "accepted")
    weekly = await plan_changes.reprice(db, make_settings(), series, booking, "weekly", booking.customer_id)
    assert (weekly.original_guide_pence, weekly.new_guide_pence) == (3100, 2900)
    assert weekly.price_pence == 3000  # 2900 x 3200 / 3100 = 2993.5, half-up to whole pounds
    every_three = await plan_changes.reprice(db, make_settings(), series, booking, "threeweekly", booking.customer_id)
    assert weekly.price_pence < series.price_pence < every_three.price_pence
