"""Stripe webhooks: signatures verified, every event applied once (by event id), stale or
out-of-order events never undo a settled payment."""

import asyncio

import pytest

from app.models.visits import Charge
from app.repos import LedgerEntries, Providers, Visits
from tests.conftest import make_settings
from tests.payments.helpers import card_customer, event, finished_visit, payable_provider, signed
from tests.payments.stripe_mock import payment_intent

SECRET = "whsec_test_secret"
URL = "/api/payments/stripe/webhook"


@pytest.fixture
def webhook_secret(app):
    before = app.state.settings
    app.state.settings = make_settings(stripe_webhook_secret=SECRET)
    yield SECRET
    app.state.settings = before


async def post(client, e: dict, secret: str = SECRET):
    body, headers = signed(e, secret)
    return await client.post(URL, content=body, headers=headers)


async def waiting_visit(db, status: str = "requires_action", key_suffix: str = "", pi: str = "pi_1"):
    """A Stripe-charged visit whose attempt is waiting on Stripe."""
    customer, provider = await card_customer(db), await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    key = f"visit:{v.id}:visit{key_suffix}"
    charge = Charge(
        status=status,  # type: ignore[arg-type]
        amount_pence=3000,
        fee_pence=450,
        provider_pence=2550,
        gateway="stripe",
        idempotency_key=key,
        payment_intent_id=pi,
    )
    await Visits(db).update(v.id, {"charge": charge.model_dump(mode="python")})
    return v, key


def pi_event(kind: str, visit_id: str, key: str, status: str, pid: str = "pi_1", **kw) -> dict:
    pi = payment_intent(pid, status, metadata={"visit_id": visit_id, "purpose": "visit", "idempotency_key": key}, **kw)
    return event(kind, pi)


async def test_unsigned_or_unconfigured_webhooks_are_refused(client, db, webhook_secret, app):
    e = event("payment_intent.succeeded", payment_intent())
    r = await post(client, e, secret="whsec_wrong")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_signature"
    r = await client.post(URL, content=b"{}", headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert await db["payment_events"].count_documents({}) == 0
    app.state.settings = make_settings(stripe_webhook_secret="")
    r = await post(client, e)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "webhooks_not_configured"


async def test_success_after_authentication_is_recorded_once(client, db, catalogue, webhook_secret):
    v, key = await waiting_visit(db)
    e = pi_event("payment_intent.succeeded", v.id, key, "succeeded")
    r = await post(client, e)
    assert r.status_code == 200 and r.json() == {"received": True, "duplicate": False}
    charge = (await Visits(db).get(v.id)).charge  # type: ignore[union-attr]
    assert (charge.status, charge.charge_id) == ("succeeded", "ch_1")
    [entry] = await LedgerEntries(db).find({"visit_id": v.id})
    assert (entry.gross_pence, entry.fee_pence, entry.net_pence, entry.gateway) == (3000, 450, 2550, "stripe")
    sent = {m["template_id"] async for m in db["outbox"].find({"related.visit_id": v.id})}
    assert sent == {"visit_done_customer", "receipt", "payment_on_its_way"}

    r = await post(client, e)  # Stripe retries the same event
    assert r.json() == {"received": True, "duplicate": True}
    assert len(await LedgerEntries(db).find({"visit_id": v.id})) == 1
    assert await db["outbox"].count_documents({"related.visit_id": v.id}) == 3
    rec = await db["payment_events"].find_one({"_id": e["id"]})
    assert rec and rec["outcome"] == "applied" and rec["type"] == "payment_intent.succeeded"


async def test_concurrent_deliveries_apply_once(client, db, catalogue, webhook_secret):
    v, key = await waiting_visit(db)
    e = pi_event("payment_intent.succeeded", v.id, key, "succeeded")
    results = await asyncio.gather(*(post(client, e) for _ in range(4)))
    assert sorted(r.json()["duplicate"] for r in results) == [False, True, True, True]
    assert len(await LedgerEntries(db).find({"visit_id": v.id})) == 1


async def test_a_failure_never_undoes_a_success(client, db, catalogue, webhook_secret):
    v, key = await waiting_visit(db)
    await post(client, pi_event("payment_intent.succeeded", v.id, key, "succeeded"))
    late = pi_event("payment_intent.payment_failed", v.id, key, "requires_payment_method")
    r = await post(client, late)
    assert r.status_code == 200
    assert (await Visits(db).get(v.id)).charge.status == "succeeded"  # type: ignore[union-attr]
    assert (await db["payment_events"].find_one({"_id": late["id"]}))["outcome"] == "ignored"  # type: ignore[index]


async def test_events_for_an_earlier_attempt_are_ignored(client, db, catalogue, webhook_secret):
    v, key = await waiting_visit(db, status="pending", key_suffix=":retry2", pi="pi_2")
    old = pi_event("payment_intent.canceled", v.id, f"visit:{v.id}:visit", "canceled", pid="pi_1")
    await post(client, old)
    assert (await Visits(db).get(v.id)).charge.status == "pending"  # type: ignore[union-attr]
    await post(client, pi_event("payment_intent.succeeded", v.id, key, "succeeded", pid="pi_2", latest_charge="ch_2"))
    assert (await Visits(db).get(v.id)).charge.charge_id == "ch_2"  # type: ignore[union-attr]


async def test_a_decline_tells_the_customer_and_provider(client, db, catalogue, webhook_secret):
    v, key = await waiting_visit(db, status="pending", pi=None)  # type: ignore[arg-type]
    e = pi_event(
        "payment_intent.payment_failed",
        v.id,
        key,
        "requires_payment_method",
        last_payment_error={
            "code": "card_declined",
            "decline_code": "insufficient_funds",
            "message": "Insufficient funds.",
        },
    )
    await post(client, e)
    charge = (await Visits(db).get(v.id)).charge  # type: ignore[union-attr]
    assert (charge.status, charge.payment_intent_id, charge.failure_reason) == ("failed", "pi_1", "Insufficient funds.")
    sent = sorted([m["template_id"] async for m in db["outbox"].find({"related.visit_id": v.id})])
    assert sent == ["charge_failed_customer", "charge_failed_provider"]


async def test_account_updates_sync_the_providers_payment_account(client, db, catalogue, webhook_secret):
    provider = await payable_provider(db)
    await Providers(db).patch(
        provider.id, {"payment_account.status": "pending", "payment_account.payouts_enabled": False}
    )
    acct = {
        "id": provider.payment_account.account_id,  # type: ignore[union-attr]
        "object": "account",
        "charges_enabled": True,
        "payouts_enabled": True,
        "external_accounts": {"data": [{"last4": "6789"}]},
    }
    await post(client, event("account.updated", acct))
    pa = (await Providers(db).get(provider.id)).payment_account  # type: ignore[union-attr]
    assert pa and (pa.status, pa.payouts_enabled, pa.bank_last4) == ("enabled", True, "6789")
    assert await db["audit_log"].count_documents({"action": "provider.payment_account_synced"}) == 1


async def test_a_payout_tells_the_provider_once(client, db, catalogue, webhook_secret):
    provider = await payable_provider(db)
    account = provider.payment_account.account_id  # type: ignore[union-attr]
    po = {"id": "po_1", "object": "payout", "amount": 2550, "status": "paid", "destination": "ba_1"}
    await post(client, event("payout.paid", po, account=account))
    await post(client, event("payout.paid", po, account=account))  # re-sent under a new event id
    msgs = [m async for m in db["outbox"].find({"template_id": "payout_sent"})]
    assert len(msgs) == 1 and "£25.50" in msgs[0]["body"]


async def test_live_events_are_ignored_in_demo_mode(client, db, catalogue, webhook_secret):
    v, key = await waiting_visit(db)
    e = pi_event("payment_intent.succeeded", v.id, key, "succeeded")
    e["livemode"] = True
    await post(client, e)
    assert (await Visits(db).get(v.id)).charge.status == "requires_action"  # type: ignore[union-attr]
    assert (await db["payment_events"].find_one({"_id": e["id"]}))["outcome"] == "ignored"  # type: ignore[index]


async def refund_waiting(db, *, refund_id: str = "re_1"):
    """A Stripe-charged visit with a £15 refund asked for and still processing."""
    from app.models.payments import RefundIntent
    from app.repos.payments import PaymentRefunds

    v, _ = await waiting_visit(db)
    await Visits(db).update(v.id, {"charge.status": "succeeded", "charge.charge_id": "ch_1"})
    intent = RefundIntent(
        visit_id=v.id,
        charge_id="ch_1",
        gateway="stripe",
        amount_pence=1500,
        fee_pence=225,
        provider_pence=1275,
        reason="Half",
        refund_id=refund_id,
    )
    await PaymentRefunds(db).insert(intent)
    return v, intent


async def test_a_refund_that_succeeds_later_is_recorded_then_its_fee_returned(client, db, catalogue, webhook_secret):
    from app.repos.payments import PaymentRefunds

    v, intent = await refund_waiting(db)
    re = {"id": "re_1", "object": "refund", "status": "succeeded", "amount": 1500, "metadata": {"intent": intent.id}}
    await post(client, event("refund.updated", re))
    after = await PaymentRefunds(db).get(intent.id)
    assert after and after.status == "fee_pending"  # the settle task returns our fee (a Stripe call)
    charge = (await Visits(db).get(v.id)).charge  # type: ignore[union-attr]
    assert (charge.status, charge.refunded_pence) == ("partially_refunded", 1500)
    [entry] = await LedgerEntries(db).find({"visit_id": v.id, "kind": "refund"})
    assert (entry.gross_pence, entry.fee_pence, entry.net_pence) == (-1500, -225, -1275)
    # Stripe's charge.refunded for the same refund adds nothing.
    ch = {"id": "ch_1", "object": "charge", "amount": 3000, "amount_refunded": 1500, "payment_intent": "pi_1"}
    await post(client, event("charge.refunded", ch))
    assert len(await LedgerEntries(db).find({"visit_id": v.id, "kind": "refund"})) == 1


async def test_a_refund_that_fails_releases_its_amount(client, db, catalogue, webhook_secret):
    from app.repos.payments import PaymentRefunds

    v, intent = await refund_waiting(db, refund_id="re_9")
    re = {
        "id": "re_9",
        "object": "refund",
        "status": "failed",
        "amount": 1500,
        "failure_reason": "expired_or_canceled_card",
    }
    await post(client, event("refund.failed", re))
    after = await PaymentRefunds(db).get(intent.id)
    assert after and (after.status, after.failure_reason) == ("failed", "expired_or_canceled_card")
    assert await PaymentRefunds(db).unsettled_pence(v.id) == 0
    assert not await LedgerEntries(db).find({"visit_id": v.id, "kind": "refund"})


def dashboard_refund(rid: str = "re_dash", amount: int = 1000, status: str = "succeeded") -> dict:
    """A refund made in the Stripe dashboard: no intent of ours in its metadata."""
    return {
        "id": rid,
        "object": "refund",
        "status": status,
        "amount": amount,
        "charge": "ch_1",
        "payment_intent": "pi_1",
    }


async def test_a_dashboard_refund_is_recorded_by_its_id(client, db, catalogue, webhook_secret):
    v, key = await waiting_visit(db)
    await post(client, pi_event("payment_intent.succeeded", v.id, key, "succeeded"))
    await post(client, event("refund.created", dashboard_refund(status="pending")))
    assert (await Visits(db).get(v.id)).charge.refunded_pence == 0  # type: ignore[union-attr]  # not until it succeeds
    await post(client, event("refund.updated", dashboard_refund()))
    charge = (await Visits(db).get(v.id)).charge  # type: ignore[union-attr]
    assert (charge.status, charge.refunded_pence, charge.refund_ids) == ("partially_refunded", 1000, ["re_dash"])
    [entry] = await LedgerEntries(db).find({"visit_id": v.id, "kind": "refund"})
    assert (entry.gross_pence, entry.fee_pence, entry.net_pence, entry.gateway_ref) == (-1000, -150, -850, "re_dash")
    assert await db["audit_log"].count_documents({"action": "payment.refund_external"}) == 1
    # Another event for the same refund, and Stripe's charge snapshot, add nothing.
    await post(client, event("refund.updated", dashboard_refund()))
    snapshot = {"id": "ch_1", "object": "charge", "amount": 3000, "amount_refunded": 1000, "payment_intent": "pi_1"}
    await post(client, event("charge.refunded", snapshot))
    assert len(await LedgerEntries(db).find({"visit_id": v.id, "kind": "refund"})) == 1


async def test_a_charge_event_listing_its_refunds_reconciles_each(client, db, catalogue, webhook_secret):
    v, key = await waiting_visit(db)
    await post(client, pi_event("payment_intent.succeeded", v.id, key, "succeeded"))
    listed = [{"id": "re_a", "status": "succeeded", "amount": 1000}, {"id": "re_b", "status": "failed", "amount": 500}]
    ch = {"id": "ch_1", "object": "charge", "amount": 3000, "amount_refunded": 1500, "payment_intent": "pi_1"}
    ch["refunds"] = {"data": listed}
    await post(client, event("charge.refunded", ch))
    assert (await Visits(db).get(v.id)).charge.refunded_pence == 1000  # type: ignore[union-attr]  # not the failed one


async def test_a_refund_event_before_the_charge_is_recorded_waits_for_it(client, db, catalogue, webhook_secret):
    v, key = await waiting_visit(db, status="pending", pi=None)  # type: ignore[arg-type]
    early = event("refund.updated", dashboard_refund())
    await post(client, early)
    rec = await db["payment_events"].find_one({"_id": early["id"]})
    assert (
        rec and rec["outcome"] == "deferred" and rec["payment_intent"] == "pi_1" and rec["payload"]["id"] == "re_dash"
    )
    assert (await post(client, early)).json()["duplicate"] is True
    await post(client, pi_event("payment_intent.succeeded", v.id, key, "succeeded"))
    charge = (await Visits(db).get(v.id)).charge  # type: ignore[union-attr]
    assert (charge.status, charge.refunded_pence) == ("partially_refunded", 1000)
    rec = await db["payment_events"].find_one({"_id": early["id"]})
    assert rec and rec["outcome"] == "applied" and rec["payload"] is None


async def test_a_deferred_refund_stranded_by_a_concurrent_success_is_replayed(client, db, catalogue, webhook_secret):
    from app.payments.webhooks import replay_all_deferred

    v, _ = await waiting_visit(db, status="pending", pi=None)  # type: ignore[arg-type]
    await post(client, event("refund.updated", dashboard_refund(amount=500)))
    # The success commits without seeing the deferred event (the interleaving the review found).
    await Visits(db).update(
        v.id, {"charge.status": "succeeded", "charge.charge_id": "ch_1", "charge.payment_intent_id": "pi_1"}
    )
    assert await replay_all_deferred(db, make_settings()) == 1
    assert (await Visits(db).get(v.id)).charge.refunded_pence == 500  # type: ignore[union-attr]


async def test_a_dashboard_refund_alongside_one_of_ours_that_fails(client, db, catalogue, webhook_secret):
    """The review's case: our £15 is pending when someone refunds £5 in the dashboard; ours then
    fails. Only the £5 is a refund, and the provider gets back what our failed one reversed."""
    from app.adapters.payments.fake import FakeGateway
    from app.payments.refunds import restore_provider
    from app.repos.payments import PaymentRefunds

    v, intent = await refund_waiting(db, refund_id="re_ours")
    await post(client, event("refund.updated", dashboard_refund(amount=500)))
    snapshot = {"id": "ch_1", "object": "charge", "amount": 3000, "amount_refunded": 2000, "payment_intent": "pi_1"}
    await post(client, event("charge.refunded", snapshot))  # a snapshot including ours: nothing recorded from it
    await post(
        client, event("refund.failed", {"id": "re_ours", "object": "refund", "status": "failed", "amount": 1500})
    )
    charge = (await Visits(db).get(v.id)).charge  # type: ignore[union-attr]
    assert charge.refunded_pence == 500
    failed = await PaymentRefunds(db).get(intent.id)
    assert failed and failed.status == "failed" and failed.restore == "needed"
    assert await PaymentRefunds(db).unsettled(v.id)  # new refunds wait until the provider is made whole
    restored = await restore_provider(db, FakeGateway(db), failed)
    assert restored.restore == "done" and restored.restore_transfer_id
    assert await db["audit_log"].count_documents({"action": "payment.transfer_restored"}) == 1
    assert not await PaymentRefunds(db).unsettled(v.id)
