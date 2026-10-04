"""Messages with customers, and the periodic tasks (reminders at 6pm, tax key dates, invites)."""

from datetime import UTC, date, datetime, timedelta

from app.core import money
from app.core.timeutil import london_datetime, utcnow
from app.provider import tasks
from app.provider.own_customers import expire_invites
from app.repos import OwnCustomerInvites
from app.services import ledger
from tests.conftest import make_settings, sign_in


async def test_messages_with_a_customer(app, dave_client, db, world):
    threads = (await dave_client.get("/api/p/threads")).json()
    assert len(threads) == 1 and threads[0]["title"] == "Lawn mowing with Sarah W."
    tid = threads[0]["id"]
    r = await dave_client.post(f"/api/p/threads/{tid}/messages", json={"body": "On my way."})
    assert r.status_code == 201 and r.json()["mine"]
    msg = await db["outbox"].find_one({"template_id": "message_received"})
    assert msg and msg["recipient"]["user_id"] == world.customer.user_id and "On my way." in msg["body"]
    assert [m["body"] for m in (await dave_client.get(f"/api/p/threads/{tid}/messages")).json()] == ["On my way."]


async def test_someone_elses_thread_is_not_found(client, db, world):
    await sign_in(client, db, "+447700900996")
    from app.repos import MessageThreads

    t = await MessageThreads(db).find_one({})
    assert (await client.get(f"/api/p/threads/{t.id}/messages")).status_code == 403  # not a provider at all


async def test_visit_reminders_go_from_6pm_the_day_before_once(db, world):
    day = world.first.local_date
    before_six = london_datetime(day - timedelta(days=1), datetime.min.time().replace(hour=17))
    assert await tasks.send_visit_reminders(db, make_settings(), before_six) == 0
    six = london_datetime(day - timedelta(days=1), datetime.min.time().replace(hour=18, minute=5))
    sent = await tasks.send_visit_reminders(db, make_settings(), six)
    assert sent == 2
    assert await tasks.send_visit_reminders(db, make_settings(), six + timedelta(hours=2)) == 2  # tried again...
    assert await db["outbox"].count_documents({"template_id": "visit_reminder_customer"}) == 1  # ...sent once
    provider_msg = await db["outbox"].find_one({"template_id": "visit_reminder_provider"})
    assert provider_msg["body"].startswith("OneQuickJob: Reminder, you're mowing in Hazlemere on ")
    assert "at 9:00" in provider_msg["body"]


async def test_tax_key_dates_go_a_month_before(db, world):
    v = world.first
    split = money.split_for_visit(v.price_pence, v.source, v.performer.kind)
    at = datetime(2026, 6, 1, 10, tzinfo=UTC)
    await ledger.record_charge(db, v, split, at=at, gateway="fake", charge_id="ch_1")
    await db["providers"].update_one({"_id": world.dave.id}, {"$set": {"status": "active"}})
    assert await tasks.send_tax_key_dates(db, make_settings(), date(2026, 12, 31)) == 0, "2026-27's return is 2028"
    assert await tasks.send_tax_key_dates(db, make_settings(), date(2027, 9, 6)) == 1
    assert await tasks.send_tax_key_dates(db, make_settings(), date(2027, 9, 7)) == 1
    msgs = await db["outbox"].find({"template_id": "tax_key_date"}).to_list()
    assert len(msgs) == 1 and "register for Self Assessment" in msgs[0]["body"] and "by 5 October" in msgs[0]["body"]
    assert await tasks.send_tax_key_dates(db, make_settings(), date(2027, 12, 31)) == 1
    assert await db["outbox"].count_documents({"template_id": "tax_key_date"}) == 2


async def test_unanswered_invites_expire_after_30_days(dave_client, db, dave):
    r = await dave_client.post(
        "/api/p/own-customers/invites",
        json={
            "name": "Mary Bishop",
            "phone": "07700 900140",
            "category_id": "mowing",
            "price_pence": 2500,
            "frequency": "fortnightly",
        },
    )
    assert await expire_invites(db) == 0
    await OwnCustomerInvites(db).update(r.json()["invite_id"], {}, extra_filter=None)
    await db["own_customer_invites"].update_one({}, {"$set": {"created_at": utcnow() - timedelta(days=31)}})
    assert await expire_invites(db) == 1
    assert (await OwnCustomerInvites(db).get(r.json()["invite_id"])).status == "expired"
