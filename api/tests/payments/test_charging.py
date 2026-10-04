"""Charging visits through the gateway (fake): intent, call, result; fees by money.py (A1, A4);
ledger entries and messages exactly once; failures and the admin retry."""

import pytest
from fastapi import HTTPException

from app.adapters.payments.fake import FakeGateway
from app.models.common import Actor
from app.payments import charging
from app.repos import Customers, LedgerEntries, Visits
from tests.conftest import make_settings
from tests.payments.helpers import card_customer, finished_visit, payable_provider, rename_card_holder

S = make_settings()
ADMIN = Actor(kind="user", user_id="admin1", role="admin", name="Jo Morgan")


def fake(db) -> FakeGateway:
    return FakeGateway(db, S.public_base_url)


async def outbox(db, visit_id: str) -> list[str]:
    return [m["template_id"] async for m in db["outbox"].find({"related.visit_id": visit_id}).sort("created_at", 1)]


async def test_a_visit_is_charged_once_with_the_standard_fee(db, catalogue):
    customer, provider = await card_customer(db), await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    done = await charging.charge_visit(db, S, fake(db), v.id)
    c = done.charge
    assert (c.status, c.amount_pence, c.fee_pence, c.provider_pence, c.gateway) == (
        "succeeded",
        3000,
        450,
        2550,
        "fake",
    )
    assert c.idempotency_key == f"visit:{v.id}:visit" and c.charge_id and c.charged_at
    [entry] = await LedgerEntries(db).find({"visit_id": v.id})
    assert (entry.kind, entry.gross_pence, entry.fee_pence, entry.net_pence) == ("charge", 3000, 450, 2550)
    assert sorted(await outbox(db, v.id)) == ["payment_on_its_way", "receipt", "visit_done_customer_no_photo"]

    again = await charging.charge_visit(db, S, fake(db), v.id)  # a repeated finish
    assert again.charge == c
    assert await db["fake_gateway"].count_documents({"kind": "charge", "visit_id": v.id}) == 1
    assert len(await LedgerEntries(db).find({"visit_id": v.id})) == 1
    assert len(await outbox(db, v.id)) == 3


@pytest.mark.parametrize(
    ("price", "source", "kind", "fee"),
    [
        (3000, "platform", "provider", 450),
        (3000, "own_customer", "provider", 150),
        (1500, "own_customer", "provider", 100),  # the £1 minimum
        (1500, "own_customer", "helper", 100),  # their registered helper: still their customer
        (3000, "own_customer", "cover", 450),  # a cover provider didn't bring them (A4)
        (3300, "platform", "provider", 495),  # a dearer first visit: its own stored price (A1)
    ],
)
async def test_the_fee_follows_who_did_the_visit(db, catalogue, price, source, kind, fee):
    customer, provider = await card_customer(db), await payable_provider(db)
    v = await finished_visit(db, customer, provider, price_pence=price, source=source, performer_kind=kind)
    c = (await charging.charge_visit(db, S, fake(db), v.id)).charge
    assert (c.amount_pence, c.fee_pence, c.provider_pence) == (price, fee, price - fee)
    [entry] = await LedgerEntries(db).find({"visit_id": v.id})
    assert entry.gross_pence == entry.fee_pence + entry.net_pence == price and entry.fee_pence == fee


async def test_a_visit_isnt_charged_before_its_finished(db, catalogue):
    customer, provider = await card_customer(db), await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    await Visits(db).update(v.id, {"status": "in_progress"})
    with pytest.raises(HTTPException) as e:
        await charging.charge_visit(db, S, fake(db), v.id)
    assert e.value.status_code == 409


async def test_a_declined_card_tells_both_and_the_admin_can_retry(db, catalogue):
    customer = await card_customer(db, "Dee Decline", "+447700900301")
    provider = await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    failed = (await charging.charge_visit(db, S, fake(db), v.id)).charge
    assert failed.status == "failed" and failed.failure_reason == "Your card was declined."
    assert sorted(await outbox(db, v.id)) == ["charge_failed_customer", "charge_failed_provider"]
    assert not await LedgerEntries(db).find({"visit_id": v.id})

    # Still declining: a new attempt with a new key (a reused key would replay the decline).
    again = (await charging.retry_charge(db, S, fake(db), v.id, ADMIN)).charge
    assert again.status == "failed" and again.idempotency_key == f"visit:{v.id}:visit:retry2"
    assert len(await outbox(db, v.id)) == 4  # one pair per attempt

    await rename_card_holder(db, customer, "Dee New Card")
    paid = (await charging.retry_charge(db, S, fake(db), v.id, ADMIN)).charge
    assert paid.status == "succeeded" and paid.idempotency_key == f"visit:{v.id}:visit:retry3"
    assert [e.kind for e in await LedgerEntries(db).find({"visit_id": v.id})] == ["charge"]
    retries = await db["audit_log"].count_documents({"action": "payment.charge_retried", "target.visit_id": v.id})
    assert retries == 2

    with pytest.raises(HTTPException) as e:
        await charging.retry_charge(db, S, fake(db), v.id, ADMIN)
    assert e.value.detail["code"] == "already_paid"


async def test_a_retry_after_authentication_cancels_the_old_attempt(db, catalogue):
    customer = await card_customer(db, "Tess 3DS", "+447700900302")
    provider = await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    first = (await charging.charge_visit(db, S, fake(db), v.id)).charge
    assert first.status == "requires_action" and first.payment_intent_id
    await rename_card_holder(db, customer, "Tess")
    await charging.retry_charge(db, S, fake(db), v.id, ADMIN)
    old = await fake(db).charge_status(first.payment_intent_id)
    assert old.status == "failed" and old.failure_reason == "The payment was cancelled."
    assert (await Visits(db).get(v.id)).charge.status == "succeeded"  # type: ignore[union-attr]


async def test_a_provider_without_a_payment_account_isnt_the_customers_problem(db, catalogue):
    from tests.factories import make_provider

    customer = await card_customer(db)
    provider = await make_provider(db, "Ken Ashworth", "+447700900212", ["mowing"])
    v = await finished_visit(db, customer, provider)
    c = (await charging.charge_visit(db, S, fake(db), v.id)).charge
    assert c.status == "failed" and c.failure_reason == "The provider's payment account isn't set up yet."
    assert await outbox(db, v.id) == []  # nobody is told to check a card
    assert await db["fake_gateway"].count_documents({"kind": "charge"}) == 0


async def test_a_tip_is_charged_without_a_fee(db, catalogue):
    customer, provider = await card_customer(db), await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    await Visits(db).update(v.id, {"tip_pence": 500})
    tipped = await charging.charge_visit(db, S, fake(db), v.id, purpose="tip")
    assert tipped.tip_charge and (tipped.tip_charge.status, tipped.tip_charge.fee_pence) == ("succeeded", 0)
    [entry] = await LedgerEntries(db).find({"visit_id": v.id, "kind": "tip"})
    assert (entry.gross_pence, entry.fee_pence, entry.net_pence) == (500, 0, 500)


async def started_long_ago(db, key: str, minutes: int = 6) -> None:
    from datetime import timedelta

    from app.core.timeutil import utcnow

    await db["payment_attempts"].update_one(
        {"_id": key}, {"$set": {"created_at": utcnow() - timedelta(minutes=minutes)}}
    )


class LostAnswer(FakeGateway):
    """The gateway charges, but the answer never comes back (or, with charge=False, the request
    never arrives)."""

    def __init__(self, db, charge: bool = True):
        super().__init__(db)
        self.charge = charge
        self.calls = 0

    async def charge_visit(self, *a, **kw):
        self.calls += 1
        if self.charge:
            await super().charge_visit(*a, **kw)
        raise ConnectionError("the answer is lost")


async def test_a_lost_answer_is_found_not_repeated(db, catalogue):
    customer, provider = await card_customer(db), await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    gw = LostAnswer(db)
    pending = await charging.charge_visit(db, S, gw, v.id)
    assert pending.charge.status == "pending" and gw.calls == 1
    # A repeated finish straight away doesn't race the first request.
    assert (await charging.charge_visit(db, S, gw, v.id)).charge.status == "pending" and gw.calls == 1
    await started_long_ago(db, f"visit:{v.id}:visit")
    # Even if the card has changed meanwhile, the payment is looked up by its key, never made again.
    await Customers(db).update(customer.id, {"payment.card.last4": "0005"})
    done = await charging.charge_visit(db, S, gw, v.id)
    assert done.charge.status == "succeeded" and gw.calls == 1
    assert await db["fake_gateway"].count_documents({"kind": "charge", "visit_id": v.id}) == 1
    assert len(await LedgerEntries(db).find({"visit_id": v.id})) == 1


async def test_a_request_that_never_arrived_fails_so_it_can_be_retried(db, catalogue):
    customer, provider = await card_customer(db), await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    gw = LostAnswer(db, charge=False)
    await charging.charge_visit(db, S, gw, v.id)
    await started_long_ago(db, f"visit:{v.id}:visit", minutes=3)
    assert (await charging.settle_unknown(db, S, gw, await Visits(db).get(v.id), "visit")).charge.status == "pending"  # type: ignore[arg-type]
    await started_long_ago(db, f"visit:{v.id}:visit")
    failed = (await charging.settle_unknown(db, S, gw, await Visits(db).get(v.id), "visit")).charge  # type: ignore[arg-type]
    assert failed.status == "failed" and failed.failure_reason == "The payment never reached the payment provider."
    assert await outbox(db, v.id) == []  # not the customer's card
    paid = (await charging.retry_charge(db, S, fake(db), v.id, ADMIN)).charge
    assert paid.status == "succeeded" and paid.idempotency_key == f"visit:{v.id}:visit:retry2"


async def test_without_a_way_to_look_it_up_an_unknown_charge_stays_pending(db, catalogue):
    customer, provider = await card_customer(db), await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    gw = LostAnswer(db)
    await charging.charge_visit(db, S, gw, v.id)
    await started_long_ago(db, f"visit:{v.id}:visit", minutes=60)
    await Customers(db).update(customer.id, {"payment.gateway_customer_id": None})
    still = await charging.settle_unknown(db, S, gw, await Visits(db).get(v.id), "visit")  # type: ignore[arg-type]
    assert still.charge.status == "pending"  # never concluded "not sent": a check by hand


async def test_a_known_payment_is_read(db, catalogue):
    customer, provider = await card_customer(db), await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    paid = await charging.charge_visit(db, S, fake(db), v.id)
    await Visits(db).update(v.id, {"charge.status": "pending", "charge.charge_id": None})
    gw = LostAnswer(db)
    again = await charging.charge_visit(db, S, gw, v.id)
    assert again.charge.status == "succeeded" and gw.calls == 0
    assert again.charge.payment_intent_id == paid.charge.payment_intent_id
