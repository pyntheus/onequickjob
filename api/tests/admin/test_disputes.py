"""Disputes: message both parties, propose a fix, close with a provider-funded refund through
the gateway, exactly once."""

import pytest
from fastapi import HTTPException

from app.adapters.payments.fake import FakeGateway
from app.core.ids import next_ref
from app.core.timeutil import utcnow
from app.models.disputes import Dispute, DisputeEvent
from app.payments import charging, refunds
from app.repos import Disputes, LedgerEntries, Messages, Visits
from app.services.audit import SYSTEM
from tests.admin.conftest import ok
from tests.conftest import make_settings
from tests.payments.helpers import card_customer, finished_visit, payable_provider


async def a_dispute(db, price: int = 3400) -> Dispute:
    customer = await card_customer(db, "Helen Mitchell", "+447700900134")
    provider = await payable_provider(db, "Alan Pryce", "+447700900210")
    v = await finished_visit(db, customer, provider, price_pence=price)
    await charging.charge_visit(db, make_settings(), FakeGateway(db), v.id)
    now = utcnow()
    d = Dispute(
        ref=await next_ref(db, "dispute"),
        visit_id=v.id,
        booking_id=v.booking_id,
        customer_id=customer.id,
        provider_id=provider.id,
        category_id="mowing",
        title="Clippings left on the patio",
        amount_pence=price,
        status_text="Waiting for Alan's reply",
        events=[DisputeEvent(at=now, by_user_id=customer.user_id, kind="opened", text="Clippings everywhere")],
    )
    await Disputes(db).insert(d)
    await Visits(db).update(v.id, {"dispute_id": d.id})
    return d


async def test_message_propose_and_close_with_a_partial_refund(jo, db, catalogue):
    d = await a_dispute(db)
    [listed] = ok(await jo.get("/api/admin/disputes"))
    assert (listed["ref"], listed["customer_name"], listed["provider_short"], listed["refundable_pence"]) == (
        d.ref,
        "Helen M.",
        "Alan P.",
        3400,
    )
    v = ok(await jo.post(f"/api/admin/disputes/{d.ref}/message", json={"body": "Alan, can you sweep up on Friday?"}))
    assert v["thread_id"] and v["events"][-1]["kind"] == "message"
    [msg] = await Messages(db).in_thread(v["thread_id"])
    assert msg.sender_role == "admin" and msg.body == "Alan, can you sweep up on Friday?"
    told = sorted([m["recipient"]["name"] async for m in db["outbox"].find({"template_id": "dispute_message"})])
    assert told == ["Alan Pryce", "Helen Mitchell"]

    r = await jo.post(f"/api/admin/disputes/{d.ref}/propose", json={"kind": "partial_refund", "amount_pence": 5000})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "more_than_paid"
    v = ok(await jo.post(f"/api/admin/disputes/{d.ref}/propose", json={"kind": "partial_refund", "amount_pence": 1000}))
    assert v["stage"] == 2 and v["status_text"] == "Fix proposed: a £10 refund, paid by Alan"
    assert v["proposed"] == {
        "kind": "partial_refund",
        "amount_pence": 1000,
        "refund_id": None,
        "funded_by": "provider",
        "note": "",
    }
    assert await db["outbox"].count_documents({"template_id": "dispute_proposal"}) == 2

    v = ok(
        await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "partial_refund", "amount_pence": 1000})
    )
    assert v["stage"] == 3 and v["status_text"] == "Closed: £10 refunded by Alan"
    assert v["resolution"]["refund_id"] and v["resolution"]["funded_by"] == "provider"
    assert (v["refunded_pence"], v["refundable_pence"]) == (1000, 2400)
    [refund] = await LedgerEntries(db).find({"visit_id": d.visit_id, "kind": "refund"})
    assert (refund.gross_pence, refund.fee_pence, refund.net_pence) == (-1000, -150, -850)  # provider-funded
    closed = [m["body"] async for m in db["outbox"].find({"template_id": "dispute_closed"})]
    assert len(closed) == 2 and closed[0].endswith("is now closed. We've refunded £10, paid by Alan.")
    assert await db["outbox"].count_documents({"template_id": "refund_issued"}) == 1
    r = await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "none"})
    assert r.status_code == 409


async def test_a_full_refund_refunds_whats_left(jo, db, catalogue):
    d = await a_dispute(db, 3000)
    ok(await jo.post(f"/api/admin/visits/{d.visit_id}/refund", json={"amount_pence": 500, "reason": "Goodwill"}))
    v = ok(await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "full_refund"}))
    assert v["resolution"]["amount_pence"] == 2500 and v["charge_status"] == "refunded"
    entries = await LedgerEntries(db).find({"visit_id": d.visit_id})
    assert sum(e.gross_pence for e in entries) == 0 and sum(e.fee_pence for e in entries) == 0


async def test_closing_after_a_return_visit_moves_no_money(jo, db, catalogue):
    d = await a_dispute(db)
    ok(await jo.post(f"/api/admin/disputes/{d.ref}/propose", json={"kind": "return_visit", "note": "Friday"}))
    v = ok(await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "return_visit"}))
    assert v["status_text"] == "Closed: Alan put it right" and v["refunded_pence"] == 0
    assert not await LedgerEntries(db).find({"visit_id": d.visit_id, "kind": "refund"})


async def test_a_repeated_close_never_refunds_twice(jo, db, catalogue):
    d = await a_dispute(db)
    body = {"outcome": "partial_refund", "amount_pence": 1000}
    first = await jo.post(f"/api/admin/disputes/{d.ref}/close", json=body)
    second = await jo.post(f"/api/admin/disputes/{d.ref}/close", json=body)
    assert first.status_code == 200 and second.status_code == 409
    assert len(await LedgerEntries(db).find({"visit_id": d.visit_id, "kind": "refund"})) == 1


async def test_concurrent_closes_refund_once(jo, sam, db, catalogue):
    import asyncio

    d = await a_dispute(db, 3000)
    body = {"outcome": "partial_refund", "amount_pence": 1000}
    results = await asyncio.gather(
        jo.post(f"/api/admin/disputes/{d.ref}/close", json=body),
        sam.post(f"/api/admin/disputes/{d.ref}/close", json=body),
        jo.post(f"/api/admin/disputes/{d.ref}/close", json=body),
    )
    assert sorted(r.status_code for r in results)[0] == 200
    assert len(await LedgerEntries(db).find({"visit_id": d.visit_id, "kind": "refund"})) == 1
    assert await db["fake_gateway"].count_documents({"kind": "refund"}) == 1
    closed = await Disputes(db).by_ref(d.ref)
    assert closed and closed.stage == 3 and closed.closing is None


async def test_a_close_another_way_waits_for_the_first(jo, db, catalogue):
    d = await a_dispute(db)
    await Disputes(db).update(
        d.id,
        {
            "closing": {"outcome": "partial_refund", "amount_pence": 500, "attempt": 1, "at": utcnow()},
            "close_attempts": 1,
        },
    )
    r = await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "none"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "closing"
    # The same close resumes (its refund key is the attempt's), and finishes.
    v = ok(await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "partial_refund", "amount_pence": 500}))
    assert v["stage"] == 3 and v["refunded_pence"] == 500


async def test_a_dispute_closes_only_once_its_refund_is_confirmed(jo, db, catalogue, monkeypatch):
    from app.repos.payments import PaymentRefunds
    from tests.payments.test_refunds import ProcessingGateway

    d = await a_dispute(db, 3000)
    gw = ProcessingGateway(db)
    monkeypatch.setattr("app.adapters.payments.FakeGateway", lambda *a, **k: gw)
    v = ok(
        await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "partial_refund", "amount_pence": 1000})
    )
    assert v["stage"] < 3 and (v["closing_outcome"], v["closing_amount_pence"]) == ("partial_refund", 1000)
    assert await db["outbox"].count_documents({"template_id": "dispute_closed"}) == 0  # nothing promised yet
    r = await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "none"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "closing"
    # Stripe confirms it: recording the refund closes the dispute in the same transaction.
    [intent] = await PaymentRefunds(db).for_visit(d.visit_id)
    assert intent.id == f"dispute-{d.id}-close-1"
    await refunds.resume(db, make_settings(), gw, intent, SYSTEM)
    closed = await Disputes(db).by_ref(d.ref)
    assert closed and closed.stage == 3 and closed.closing is None and closed.resolution
    assert closed.resolution.refund_id == "re_processing"
    assert await db["outbox"].count_documents({"template_id": "dispute_closed"}) == 2
    assert len(await LedgerEntries(db).find({"visit_id": d.visit_id, "kind": "refund"})) == 1


async def test_a_refund_that_fails_lets_the_dispute_be_closed_again(jo, db, catalogue, monkeypatch):
    from app.repos.payments import PaymentRefunds
    from tests.payments.test_refunds import ProcessingGateway

    d = await a_dispute(db, 3000)
    gw = ProcessingGateway(db, outcome="failed")
    monkeypatch.setattr("app.adapters.payments.FakeGateway", lambda *a, **k: gw)
    ok(await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "full_refund"}))
    [intent] = await PaymentRefunds(db).for_visit(d.visit_id)
    with pytest.raises(HTTPException):  # a failed refund answers 502
        await refunds.resume(db, make_settings(), gw, intent, SYSTEM)
    released = await Disputes(db).by_ref(d.ref)
    assert released and released.stage < 3 and released.closing is None
    monkeypatch.undo()
    v = ok(await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "none"}))
    assert v["stage"] == 3


async def test_a_full_refund_close_resumes_even_when_nothing_is_left_to_refund(jo, db, catalogue, monkeypatch):
    from tests.payments.test_refunds import ProcessingGateway

    d = await a_dispute(db, 3000)
    gw = ProcessingGateway(db, outcome="pending")  # Stripe keeps processing it
    monkeypatch.setattr("app.adapters.payments.FakeGateway", lambda *a, **k: gw)
    ok(await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "full_refund"}))
    # The whole balance is reserved by the pending refund; a retry resumes the same close.
    v = ok(await jo.post(f"/api/admin/disputes/{d.ref}/close", json={"outcome": "full_refund"}))
    assert v["refundable_pence"] == 0 and v["closing_outcome"] == "full_refund" and v["closing_amount_pence"] == 3000
    assert gw.created == [f"dispute-{d.id}-close-1"]  # still one refund
