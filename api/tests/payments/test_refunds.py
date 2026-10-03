"""Refunds: provider-funded, our fee returned in proportion (money.refund_split), exact to the
penny however a visit is refunded, recorded once with a negative ledger entry."""

import pytest
from fastapi import HTTPException

from app.adapters.payments.fake import FakeGateway
from app.core import money
from app.models.common import Actor
from app.payments import charging, refunds
from app.repos import LedgerEntries, Visits
from app.repos.payments import PaymentRefunds
from tests.conftest import make_settings
from tests.payments.helpers import card_customer, finished_visit, payable_provider

S = make_settings()
ADMIN = Actor(kind="user", user_id="admin1", role="admin", name="Jo Morgan")


async def charged(db, price: int = 3000, source: str = "platform"):
    customer, provider = await card_customer(db), await payable_provider(db)
    v = await finished_visit(db, customer, provider, price_pence=price, source=source)
    await charging.charge_visit(db, S, FakeGateway(db), v.id)
    return v


async def test_half_of_a_30_pound_visit(db, catalogue):
    v = await charged(db)
    out = await refunds.refund_visit(db, S, FakeGateway(db), v.id, 1500, "Clippings left on the patio", ADMIN)
    assert (out.status, out.amount_pence, out.fee_refunded_pence, out.provider_refunded_pence) == (
        "succeeded",
        1500,
        225,
        1275,
    )
    charge = (await Visits(db).get(v.id)).charge  # type: ignore[union-attr]
    assert (charge.status, charge.refunded_pence, charge.refund_ids) == ("partially_refunded", 1500, [out.refund_id])
    entry = (await LedgerEntries(db).find({"visit_id": v.id, "kind": "refund"}))[0]
    assert (entry.gross_pence, entry.fee_pence, entry.net_pence) == (-1500, -225, -1275)
    assert entry.gateway_ref == out.refund_id
    assert await db["outbox"].count_documents({"template_id": "refund_issued", "related.visit_id": v.id}) == 1
    log = await db["audit_log"].find_one({"action": "payment.refunded"})
    assert log and log["after"]["funded_by"] == "provider" and log["actor"]["user_id"] == "admin1"
    # The provider funds it: their charge's net at the gateway falls by their share only.
    ch = await db["fake_gateway"].find_one({"_id": charge.charge_id})
    assert ch and ch["net_pence"] == 2550 - 1275


async def test_an_own_customer_refund_returns_our_pound_in_proportion(db, catalogue):
    v = await charged(db, 1500, "own_customer")
    out = await refunds.refund_visit(db, S, FakeGateway(db), v.id, 750, "Half the job", ADMIN)
    assert (out.fee_refunded_pence, out.provider_refunded_pence) == (50, 700)


async def test_partial_refunds_add_up_to_exactly_the_fee(db, catalogue):
    v = await charged(db)
    original = money.split_for_visit(3000, "platform", "provider")
    fees = []
    for amount in (10, 10, 10):  # each on its own would round 1.5p up to 2p
        fees.append(
            (await refunds.refund_visit(db, S, FakeGateway(db), v.id, amount, "Small refund", ADMIN)).fee_refunded_pence
        )
    assert sum(fees) == money.refund_split(original, 30).fee_pence == 5
    rest = await refunds.refund_visit(db, S, FakeGateway(db), v.id, 2970, "The rest", ADMIN)
    assert sum(fees) + rest.fee_refunded_pence == 450  # a full refund returns exactly the fee
    entries = await LedgerEntries(db).find({"visit_id": v.id})
    assert sum(e.gross_pence for e in entries) == 0
    assert sum(e.fee_pence for e in entries) == 0 and sum(e.net_pence for e in entries) == 0
    assert all(e.gross_pence == e.fee_pence + e.net_pence for e in entries)
    assert (await Visits(db).get(v.id)).charge.status == "refunded"  # type: ignore[union-attr]


async def test_cant_refund_more_than_is_left(db, catalogue):
    v = await charged(db)
    await refunds.refund_visit(db, S, FakeGateway(db), v.id, 2000, "Most of it", ADMIN)
    with pytest.raises(HTTPException) as e:
        await refunds.refund_visit(db, S, FakeGateway(db), v.id, 1001, "Too much", ADMIN)
    assert e.value.status_code == 409 and e.value.detail["extra"] == {"left_pence": 1000}
    assert len(await PaymentRefunds(db).for_visit(v.id)) == 1


async def test_an_unpaid_visit_cant_be_refunded(db, catalogue):
    customer, provider = await card_customer(db), await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    with pytest.raises(HTTPException) as e:
        await refunds.refund_visit(db, S, FakeGateway(db), v.id, 100, "No", ADMIN)
    assert e.value.detail["code"] == "not_paid"


async def test_a_refund_interrupted_after_the_gateway_is_recorded_once_on_retry(db, catalogue):
    v = await charged(db)
    gw = FakeGateway(db)

    class Flaky(FakeGateway):
        async def refund(self, *a, **kw):
            await super().refund(*a, **kw)  # the money moves...
            raise ConnectionError("...but the answer is lost")

    out = await refunds.refund_visit(db, S, Flaky(db), v.id, 1500, "Lost answer", ADMIN)
    assert out.status == "pending"
    [intent] = await PaymentRefunds(db).for_visit(v.id)
    assert intent.status == "pending"
    # Nothing is left to refund twice: the pending intent counts.
    with pytest.raises(HTTPException):
        await refunds.refund_visit(db, S, gw, v.id, 1501, "Too much", ADMIN)
    settled = await refunds.send_refund(db, S, gw, intent, ADMIN)  # what the task does: same key
    assert settled.status == "succeeded"
    assert await db["fake_gateway"].count_documents({"kind": "refund"}) == 1
    assert len(await LedgerEntries(db).find({"visit_id": v.id, "kind": "refund"})) == 1
    assert (await Visits(db).get(v.id)).charge.refunded_pence == 1500  # type: ignore[union-attr]


class ProcessingGateway(FakeGateway):
    """A refund the gateway is still processing; it later succeeds or fails."""

    def __init__(self, db, outcome: str = "succeeded"):
        super().__init__(db)
        self.outcome = outcome
        self.created: list[str | None] = []
        self.fee_calls = 0

    async def refund(self, charge_id, amount_pence, fee_refund_pence, *, reason, idempotency_key=None):
        self.created.append(idempotency_key)
        from app.adapters.payments.base import RefundResult

        return RefundResult(
            status="pending", refund_id="re_processing", amount_pence=amount_pence, fee_refunded_pence=0
        )

    async def refund_status(self, refund_id):
        from app.adapters.payments.base import RefundResult

        return RefundResult(status=self.outcome, refund_id=refund_id, amount_pence=0, fee_refunded_pence=0)  # type: ignore[arg-type]

    async def refund_fee(self, charge_id, fee_refund_pence, *, idempotency_key):
        self.fee_calls += 1
        return await super().refund_fee(charge_id, fee_refund_pence, idempotency_key=idempotency_key)


async def test_a_refund_still_processing_moves_nothing_until_it_succeeds(db, catalogue):
    v = await charged(db)
    gw = ProcessingGateway(db)
    out = await refunds.refund_visit(db, S, gw, v.id, 1500, "Half", ADMIN)
    assert (out.status, out.refund_id) == ("pending", "re_processing")
    charge = (await Visits(db).get(v.id)).charge  # type: ignore[union-attr]
    assert (charge.status, charge.refunded_pence) == ("succeeded", 0)  # nothing recorded yet
    assert not await LedgerEntries(db).find({"visit_id": v.id, "kind": "refund"})
    assert await db["outbox"].count_documents({"template_id": "refund_issued"}) == 0
    # One refund of a visit at a time: the next waits for this one.
    with pytest.raises(HTTPException) as e:
        await refunds.refund_visit(db, S, FakeGateway(db), v.id, 100, "Another", ADMIN)
    assert e.value.detail["code"] == "refund_in_progress"
    # It succeeds: read by its id (never made again), the fee returned, the money recorded once.
    [intent] = await PaymentRefunds(db).for_visit(v.id)
    done = await refunds.resume(db, S, gw, intent, ADMIN)
    assert done.status == "succeeded" and gw.created == [intent.id] and gw.fee_calls == 1
    [entry] = await LedgerEntries(db).find({"visit_id": v.id, "kind": "refund"})
    assert (entry.gross_pence, entry.fee_pence, entry.net_pence) == (-1500, -225, -1275)
    assert await db["outbox"].count_documents({"template_id": "refund_issued"}) == 1


async def test_a_failed_refund_releases_its_amount_and_the_fees_still_add_up(db, catalogue):
    v = await charged(db)
    gw = ProcessingGateway(db, outcome="failed")
    await refunds.refund_visit(db, S, gw, v.id, 10, "Will fail", ADMIN)
    [intent] = await PaymentRefunds(db).for_visit(v.id)
    with pytest.raises(HTTPException) as e:
        await refunds.resume(db, S, gw, intent, ADMIN)
    assert e.value.status_code == 502 and (await PaymentRefunds(db).get(intent.id)).status == "failed"  # type: ignore[union-attr]
    first = await refunds.refund_visit(db, S, FakeGateway(db), v.id, 10, "Small", ADMIN)
    rest = await refunds.refund_visit(db, S, FakeGateway(db), v.id, 2990, "The rest", ADMIN)
    assert first.fee_refunded_pence + rest.fee_refunded_pence == 450  # exactly the fee
    assert await db["audit_log"].count_documents({"action": "payment.refund_failed"}) == 1


async def test_an_unknown_outcome_keeps_the_reservation_and_repeats_with_the_same_key(db, catalogue):
    v = await charged(db)
    keys: list[str | None] = []

    class Unreachable(FakeGateway):
        async def refund(self, charge_id, amount_pence, fee_refund_pence, *, reason, idempotency_key=None):
            from app.adapters.payments.base import RefundResult

            keys.append(idempotency_key)
            return RefundResult(status="pending", amount_pence=amount_pence, fee_refunded_pence=0, failure_reason="?")

    out = await refunds.refund_visit(db, S, Unreachable(db), v.id, 3000, "All of it", ADMIN)
    assert out.status == "pending"
    with pytest.raises(HTTPException) as e:
        await refunds.refund_visit(db, S, FakeGateway(db), v.id, 3000, "Again", ADMIN)
    assert e.value.detail["code"] == "refund_in_progress"  # not refunded twice
    [intent] = await PaymentRefunds(db).for_visit(v.id)
    assert (await refunds.resume(db, S, FakeGateway(db), intent, ADMIN)).status == "pending"  # still in flight
    from datetime import timedelta

    from app.core.timeutil import utcnow

    await db["payment_refunds"].update_one(
        {"_id": intent.id}, {"$set": {"created_at": utcnow() - timedelta(minutes=6)}}
    )
    intent = await PaymentRefunds(db).get(intent.id)
    gw = FakeGateway(db)
    done = await refunds.resume(db, S, gw, intent, ADMIN)  # type: ignore[arg-type]  # what the settle task does
    assert done.status == "succeeded" and keys == [intent.id]
    assert await db["fake_gateway"].find_one({"kind": "refund"}, {"idempotency_key": 1}) == {
        "_id": done.refund_id,
        "idempotency_key": intent.id,
    }


async def test_nothing_that_could_move_money_is_repeated_after_the_key_expires(db, catalogue):
    from datetime import timedelta

    from app.core.timeutil import utcnow

    v = await charged(db)
    gw = ProcessingGateway(db)
    await refunds.refund_visit(db, S, gw, v.id, 1500, "Half", ADMIN)
    [intent] = await PaymentRefunds(db).for_visit(v.id)
    old = utcnow() - timedelta(hours=25)
    await db["payment_refunds"].update_one({"_id": intent.id}, {"$set": {"refund_id": None, "created_at": old}})
    assert await refunds.settle_open_refunds(db, S, gw, older_than=timedelta(minutes=5)) == 0
    with pytest.raises(HTTPException) as e:
        await refunds.resume(db, S, gw, (await PaymentRefunds(db).get(intent.id)), ADMIN)  # type: ignore[arg-type]
    assert e.value.detail["code"] == "check_by_hand" and gw.created == [intent.id]
    # A fee still to return is retried only while its key lives, too.
    await db["payment_refunds"].update_one({"_id": intent.id}, {"$set": {"status": "fee_pending"}})
    with pytest.raises(HTTPException):
        await refunds.resume(db, S, gw, (await PaymentRefunds(db).get(intent.id)), ADMIN)  # type: ignore[arg-type]
    assert gw.fee_calls == 0
