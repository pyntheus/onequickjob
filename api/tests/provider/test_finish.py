"""Finishing a visit: calibration data always kept; the charge outside any transaction with the
fee from money.split_for_visit; one ledger entry with gross == fee + net; the messages."""

import asyncio

import pytest

from app.adapters.payments.fake import FakeGateway
from app.core.db import transaction
from app.core.timeutil import london_today, utcnow
from app.models.visits import Performer
from app.provider import finish
from app.provider.acting import Acting
from app.repos import Bookings, LedgerEntries, MileageLogs, Visits
from tests.conftest import make_settings
from tests.factories import make_customer, make_provider
from tests.provider.conftest import MIKE_PHONE, add_tom, book, client_for, make_dave, move_to_today, with_account

FINISH = {"minutes": 52, "from_timer": True, "flags": ["Grass was longer than described"], "nothing_different": False}


async def _outbox(db, template_id: str, **flt) -> list[dict]:
    return await db["outbox"].find({"template_id": template_id, **flt}).to_list()


async def _start(client, visit_id: str) -> None:
    r = await client.post(f"/api/p/visits/{visit_id}/start")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"


async def test_finish_records_calibration_charges_and_writes_one_ledger_entry(dave_client, db, world):
    v = await move_to_today(db, world.first)
    await _start(dave_client, v.id)
    r = await dave_client.post(f"/api/p/visits/{v.id}/finish", json={**FINISH, "note": " A second lawn. "})
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["price_pence"], out["fee_pence"], out["provider_pence"]) == (3000, 450, 2550)
    assert out["charge_status"] == "succeeded" and out["overrun"] is True and out["est_mins"] == 40

    stored = await Visits(db).get(v.id)
    assert stored.status == "finished" and stored.minutes_actual == 52 and stored.minutes_from_timer
    assert stored.overrun is True and stored.over_25 is True  # 52 > 44 and 52 > 50
    assert stored.flags == ["Grass was longer than described"] and not stored.flags_none
    assert stored.finish_note == "A second lawn."
    assert stored.charge.status == "succeeded" and stored.charge.idempotency_key == f"visit:{v.id}:visit"

    entries = await LedgerEntries(db).find({"visit_id": v.id})
    assert len(entries) == 1
    e = entries[0]
    assert (e.kind, e.gross_pence, e.fee_pence, e.net_pence) == ("charge", 3000, 450, 2550)
    assert e.gross_pence == e.fee_pence + e.net_pence and e.provider_id == world.dave.id
    assert e.local_date == london_today() and e.gateway == "fake"

    done = await _outbox(db, "visit_done_customer_no_photo", **{"related.visit_id": v.id})
    assert len(done) == 1 and "We've charged £30 to your card" in done[0]["body"]
    paid = await _outbox(db, "payment_on_its_way", **{"related.visit_id": v.id})
    assert len(paid) == 1 and "£25.50 is on its way" in paid[0]["body"]
    assert await MileageLogs(db).count({"provider_id": world.dave.id, "local_date": london_today().isoformat()}) == 1


async def test_after_photo_changes_the_customers_text_and_the_receipt_names_the_agreement(dave_client, db, world):
    v = await move_to_today(db, world.first)
    await db["users"].update_one({"_id": world.customer.user_id}, {"$set": {"email": "sarah@example.com"}})
    await _start(dave_client, v.id)
    up = await dave_client.post(
        "/api/files", data={"kind": "visit_after"}, files={"file": ("after.png", b"\x89PNG\r\n\x1a\n0", "image/png")}
    )
    assert up.status_code == 201, up.text
    r = await dave_client.post(f"/api/p/visits/{v.id}/photos", json={"kind": "after", "file_id": up.json()["id"]})
    assert r.status_code == 200 and len(r.json()["after_photos"]) == 1
    await dave_client.post(f"/api/p/visits/{v.id}/finish", json=FINISH)
    done = await _outbox(db, "visit_done_customer", **{"related.visit_id": v.id})
    assert len(done) == 1 and "added an after photo" in done[0]["body"]
    receipt = (await _outbox(db, "receipt", **{"related.visit_id": v.id}))[0]
    assert receipt["channel"] == "email"
    assert "done by Dave Hughes." in receipt["body"] and "Of which OneQuickJob fee: £4.50" in receipt["body"]
    assert "Your agreement for this work is with Dave." in receipt["body"]


@pytest.mark.parametrize(
    ("source", "performer", "price", "fee"),
    [
        ("platform", "provider", 3000, 450),  # standard 15%
        ("own_customer", "provider", 1500, 100),  # 5% with the 100p minimum
        ("own_customer", "helper", 3000, 150),  # their helper keeps the own-customer rate
        ("own_customer", "cover", 3000, 450),  # a cover provider pays the standard fee (A4)
    ],
)
async def test_the_fee_follows_money_split_for_visit(db, catalogue, source, performer, price, fee):
    customer = await make_customer(db)
    dave = await make_dave(db)
    tom = await add_tom(db, dave)
    mike = await with_account(db, await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"]))
    _, v = await book(db, customer, dave, source=source, price=price)
    v = await move_to_today(db, v)
    if performer == "helper":
        p = Performer(kind="helper", provider_id=dave.id, user_id=tom.id, name="Tom H.")
        await Visits(db).update(v.id, {"performer": p.model_dump()})
    if performer == "cover":
        p = Performer(kind="cover", provider_id=mike.id, user_id=mike.user_id, name="Mike R.")
        await Visits(db).update(v.id, {"provider_id": mike.id, "performer": p.model_dump(), "cover.state": "covered"})
    await Visits(db).update(v.id, {"status": "in_progress", "started_at": utcnow()})
    paid_by = mike if performer == "cover" else dave
    actor_user = {"helper": tom.id, "cover": mike.user_id}.get(performer, dave.user_id)
    from app.repos import Providers, Users

    who = await Providers(db).get(paid_by.id if performer != "helper" else dave.id)
    a = Acting(provider=who, cu=_cu(await Users(db).get(actor_user)))
    out = await finish.finish_visit(db, make_settings(), FakeGateway(db), a, v.id, _body())
    assert (out.price_pence, out.fee_pence, out.provider_pence) == (price, fee, price - fee)
    e = await LedgerEntries(db).find_one({"visit_id": v.id})
    assert (e.gross_pence, e.fee_pence, e.net_pence, e.provider_id) == (price, fee, price - fee, paid_by.id)


def _cu(user):
    from app.core.deps import CurrentUser
    from app.models.users import Session

    return CurrentUser(
        user=user,
        session=Session(
            user_id=user.id, created_at=utcnow(), expires_at=utcnow(), last_seen_at=utcnow(), via="code", user_agent=""
        ),
    )


def _body(**kw):
    from app.provider.schemas import FinishIn

    return FinishIn(**{**FINISH, **kw})


async def test_finishing_twice_charges_once(dave_client, db, world):
    v = await move_to_today(db, world.first)
    await _start(dave_client, v.id)
    a, b = await asyncio.gather(
        dave_client.post(f"/api/p/visits/{v.id}/finish", json=FINISH),
        dave_client.post(f"/api/p/visits/{v.id}/finish", json={**FINISH, "minutes": 99}),
    )
    assert a.status_code == 200 and b.status_code == 200
    assert await LedgerEntries(db).count({"visit_id": v.id}) == 1
    assert await db["fake_gateway"].count_documents({"kind": "charge", "visit_id": v.id}) == 1
    assert len(await _outbox(db, "payment_on_its_way", **{"related.visit_id": v.id})) == 1
    again = await dave_client.post(f"/api/p/visits/{v.id}/finish", json=FINISH)
    assert again.status_code == 200 and again.json()["charge_status"] == "succeeded"
    assert await LedgerEntries(db).count({"visit_id": v.id}) == 1


async def test_a_declined_card_keeps_the_calibration_data_and_writes_no_ledger_entry(dave_client, db, world):
    await db["fake_gateway"].insert_one({"_id": "cus_fake_test", "kind": "customer", "name": "Decline Test"})
    v = await move_to_today(db, world.first)
    await _start(dave_client, v.id)
    r = await dave_client.post(f"/api/p/visits/{v.id}/finish", json=FINISH)
    assert r.status_code == 200 and r.json()["charge_status"] == "failed"
    assert "card didn't go through" in r.json()["charge_message"]
    stored = await Visits(db).get(v.id)
    assert stored.status == "finished" and stored.minutes_actual == 52 and stored.charge.status == "failed"
    assert await LedgerEntries(db).count({"visit_id": v.id}) == 0
    assert len(await _outbox(db, "charge_failed_customer")) == 1
    assert len(await _outbox(db, "charge_failed_provider")) == 1
    assert await _outbox(db, "payment_on_its_way") == []


async def test_a_charge_that_never_reached_the_gateway_is_resumed_once(db, world, monkeypatch):
    """A crash between saving the finished visit and charging: the visit is finished with a
    pending charge; after the grace period the resume task charges it, exactly once."""
    v = await move_to_today(db, world.first)
    await Visits(db).update(v.id, {"status": "in_progress", "started_at": utcnow()})
    s = make_settings()
    from app.repos import Users

    a = Acting(provider=world.dave, cu=_cu(await Users(db).get(world.dave.user_id)))

    async def crash(*_a, **_k):
        raise RuntimeError("the process died")

    monkeypatch.setattr(finish, "charge_and_record", crash)
    with pytest.raises(RuntimeError):
        await finish.finish_visit(db, s, FakeGateway(db), a, v.id, _body())
    monkeypatch.undo()
    stored = await Visits(db).get(v.id)
    assert stored.status == "finished" and stored.minutes_actual == 52, "calibration data was kept"
    assert stored.charge.status == "pending" and stored.charge.payment_intent_id is None

    assert await finish.resume_pending_charges(db, s, FakeGateway(db)) == 0, "too soon: it may still be in flight"
    old = utcnow().replace(year=2000)
    await Visits(db).update(v.id, {"finished_at": old, "charge.attempted_at": old})
    results = await asyncio.gather(*(finish.resume_pending_charges(db, s, FakeGateway(db)) for _ in range(3)))
    assert sum(results) == 1
    assert await db["fake_gateway"].count_documents({"kind": "charge", "visit_id": v.id}) == 1
    assert await LedgerEntries(db).count({"visit_id": v.id}) == 1
    assert (await Visits(db).get(v.id)).charge.status == "succeeded"


async def test_a_one_off_booking_completes_when_its_visit_is_charged(dave_client, db, dave):
    customer = await make_customer(db)
    booking, v = await book(db, customer, dave, frequency="oneoff", price=6100, category="hedges")
    v = await move_to_today(db, v)
    await _start(dave_client, v.id)
    await dave_client.post(f"/api/p/visits/{v.id}/finish", json={**FINISH, "flags": [], "nothing_different": True})
    assert (await Bookings(db).get(booking.id)).status == "completed"
    stored = await Visits(db).get(v.id)
    assert stored.flags_none and stored.flags == [] and stored.overrun is True


async def test_flags_and_nothing_different_are_exclusive(dave_client, db, world):
    v = await move_to_today(db, world.first)
    await _start(dave_client, v.id)
    r = await dave_client.post(f"/api/p/visits/{v.id}/finish", json={**FINISH, "nothing_different": True})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "flags_conflict"
    assert (await Visits(db).get(v.id)).status == "in_progress"


async def test_a_visit_must_be_started_before_it_is_finished(dave_client, db, world):
    r = await dave_client.post(f"/api/p/visits/{world.first.id}/finish", json=FINISH)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_started"


async def test_reaching_the_limit_sends_one_text(dave_client, db, world):
    await db["providers"].update_one(
        {"_id": world.dave.id}, {"$set": {"earnings_limit": {"on": True, "period": "week", "amount_pence": 2500}}}
    )
    v = await move_to_today(db, world.first)
    await _start(dave_client, v.id)
    await dave_client.post(f"/api/p/visits/{v.id}/finish", json=FINISH)
    msgs = await _outbox(db, "limit_reached")
    assert len(msgs) == 1 and "weekly earnings limit of £25" in msgs[0]["body"]


async def test_someone_elses_visit_is_not_found(app, db, world):
    mike = await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"])
    async with client_for(app, db, MIKE_PHONE) as mc:
        for path in ("", "/start"):
            r = await (mc.get if not path else mc.post)(f"/api/p/visits/{world.first.id}{path}")
            assert r.status_code == 404
    assert mike


async def test_charging_happens_outside_any_transaction(db, world, monkeypatch):
    """The gateway is called with no transaction open (CLAUDE.md): a call made inside one
    would be re-run on a write conflict, and would hold its locks."""
    from app.core import db as core_db

    seen = []

    class Spy(FakeGateway):
        async def charge_visit(self, *a, **k):
            seen.append(core_db._open.get())
            return await super().charge_visit(*a, **k)

    v = await move_to_today(db, world.first)
    await Visits(db).update(v.id, {"status": "in_progress", "started_at": utcnow()})
    from app.repos import Users

    a = Acting(provider=world.dave, cu=_cu(await Users(db).get(world.dave.user_id)))
    await finish.finish_visit(db, make_settings(), Spy(db), a, v.id, _body())
    assert seen == [None]
    assert transaction  # the module under test uses app.core.db.transaction for steps 1 and 3
