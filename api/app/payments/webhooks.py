"""Stripe webhooks: the source of truth for final payment states.

Every event is verified against STRIPE_WEBHOOK_SECRET (the Stripe-Signature header), then
applied in ONE transaction with its record in payment_events, keyed by the event id: Stripe
delivers at least once and may retry, and a second delivery finds the record and changes
nothing. Handlers only read the event and Mongo (no calls to Stripe), so the transaction
holds nothing outside the database. Events may arrive out of order: a payment event applies
only to the attempt named in its metadata (its idempotency key) and never undoes a success.

Handled: payment_intent.* (succeeded, payment_failed, requires_action, processing, canceled),
refund.created / refund.updated / refund.failed (and the older charge.refund.updated): each
refund is recorded by its id, ours when it succeeds and others (the dashboard) likewise;
charge.refunded (only the refunds it lists: its totals are snapshots); account.updated,
payout.paid and payout.failed. Anything else is logged and acknowledged. Live-mode events are
ignored while DEMO_MODE is on. A refund event that arrives before its charge is recorded is kept,
with its payload, and replayed when the charge is (replay_deferred, and the settle task).
"""

import json
import logging
from typing import Any

import stripe

from app.adapters.payments.stripe_gateway import (
    charge_result_from_intent,
    provider_account_from_stripe,
    ref_id,
    refund_state,
)
from app.core import money
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.timeutil import utcnow
from app.models.common import Related
from app.models.payments import PaymentEvent
from app.payments import charging, notices
from app.payments.refunds import apply_refund_result
from app.repos.payments import PaymentEvents, PaymentRefunds
from app.repos.providers import Providers
from app.repos.visits import Visits
from app.services import ledger, lifecycle
from app.services.audit import SYSTEM, audit

log = logging.getLogger("oqj.payments.webhooks")

TOLERANCE_SECONDS = 300
type Json = dict[str, Any]
type Outcome = tuple[str, str]  # (applied | ignored | no_match, note)


class BadEvent(ValueError):
    pass


def verify(payload: bytes, header: str | None, secret: str) -> Json:
    """The event, if the Stripe-Signature header matches; raises otherwise."""
    text = payload.decode("utf-8")
    stripe.WebhookSignature.verify_header(text, header, secret, TOLERANCE_SECONDS)
    event = json.loads(text)
    if not isinstance(event, dict) or not event.get("id") or not event.get("type"):
        raise BadEvent("not a Stripe event")
    return event


async def handle(db: Db, s: Settings, event: Json) -> bool:
    """Apply a verified event once. True if it had been received before (a duplicate)."""
    obj = (event.get("data") or {}).get("object") or {}
    record = PaymentEvent(
        id=event["id"],
        type=event["type"],
        account=event.get("account"),
        object_id=obj.get("id"),
        livemode=bool(event.get("livemode")),
        received_at=utcnow(),
    )

    async def apply(session: DbSession) -> bool:
        events = PaymentEvents(db)
        if not await events.claim(record, session=session):
            return True
        if record.livemode and s.demo_mode:
            outcome, note = "ignored", "live-mode event while DEMO_MODE is on"
        else:
            outcome, note = await dispatch(db, s, event, obj, session)
        deferred = outcome == "deferred"
        await events.set_outcome(
            record.id,
            outcome,
            note,
            payment_intent=ref_id(obj.get("payment_intent")) if deferred else None,
            payload=obj if deferred else None,
            session=session,
        )
        return False

    duplicate = await transaction(db, apply)
    log.info("stripe event %s %s%s", record.id, record.type, " (duplicate)" if duplicate else "")
    return duplicate


async def dispatch(db: Db, s: Settings, event: Json, obj: Json, session: DbSession) -> Outcome:
    kind = event["type"]
    if kind.startswith("payment_intent."):
        return await payment_intent(db, s, obj, session)
    match kind:
        case "charge.refunded":
            return await charge_refunded(db, s, obj, session)
        case "refund.created" | "refund.updated" | "refund.failed" | "charge.refund.updated":
            return await refund_updated(db, s, obj, session)
        case "account.updated":
            return await account_updated(db, s, obj, session)
        case "payout.paid":
            return await payout_paid(db, s, event.get("account"), obj, session)
        case "payout.failed":
            return await payout_failed(db, event.get("account"), obj, session)
    return "ignored", "not an event we act on"


async def payment_intent(db: Db, s: Settings, pi: Json, session: DbSession) -> Outcome:
    meta = pi.get("metadata") or {}
    visit_id, key = meta.get("visit_id"), meta.get("idempotency_key")
    purpose = meta.get("purpose", "visit")
    if not visit_id or not key or purpose not in ("visit", "tip"):
        return "ignored", "not a visit payment"
    if await Visits(db).get(visit_id, session=session) is None:
        return "no_match", f"no visit {visit_id}"
    result = charge_result_from_intent(pi, idempotency_key=key)
    applied = await charging.apply_result(db, s, visit_id, purpose, key, result, session=session)
    return ("applied", result.status) if applied else ("ignored", "already settled, or an earlier attempt")


SETTLED = ("succeeded", "partially_refunded", "refunded")


async def _visit_for(db: Db, charge_id: str | None, payment_intent: str | None, session: DbSession):
    match = ([{"charge.charge_id": charge_id}] if charge_id else []) + (
        [{"charge.payment_intent_id": payment_intent}] if payment_intent else []
    )
    return await Visits(db).find_one({"$or": match}, session=session) if match else None


async def charge_refunded(db: Db, s: Settings, ch: Json, session: DbSession) -> Outcome:
    """Stripe's charge totals are snapshots (a refund in them may still fail), so nothing is
    recorded from them. Refunds are recorded one by one, by id, from refund events; when this
    event lists its refunds, each is reconciled the same way."""
    listed = (ch.get("refunds") or {}).get("data") or []
    if not listed:
        return "ignored", "refunds are recorded from refund events"
    outcomes = []
    for re in listed:
        outcomes.append(
            await refund_updated(
                db, s, {"charge": ch.get("id"), "payment_intent": ch.get("payment_intent"), **re}, session
            )
        )
    if any(o == "deferred" for o, _ in outcomes):
        return "deferred", "the charge isn't recorded yet; replayed when it is"
    applied = [n for o, n in outcomes if o == "applied"]
    return ("applied", "; ".join(applied)) if applied else ("ignored", "refunds already recorded")


async def external_refund(db: Db, s: Settings, re: Json, session: DbSession) -> Outcome:
    """A refund not asked for here (made in the Stripe dashboard): recorded by its id once it has
    succeeded, so the ledger matches Stripe. If its charge isn't recorded yet (events arrive in
    any order), the event waits for it."""
    pi = ref_id(re.get("payment_intent"))
    visit = await _visit_for(db, ref_id(re.get("charge")), pi, session)
    if visit is None or visit.charge.status not in SETTLED:
        if not pi:
            return "no_match", "no visit charge for that refund"
        if visit is not None:
            # Write the visit, so a charge success committing at the same moment conflicts with
            # this deferral and one of them re-runs (and sees the other).
            await Visits(db).update(visit.id, {}, session=session)
        return "deferred", "the charge isn't recorded yet; replayed when it is"
    if re.get("status") != "succeeded":
        return "ignored", f"refund {re.get('status')}: recorded if it succeeds"
    charge = visit.charge
    if re.get("id") in charge.refund_ids:
        return "ignored", "already recorded"
    amount = min(int(re.get("amount") or 0), charge.amount_pence - charge.refunded_pence)
    if amount <= 0:
        return "ignored", "nothing left on the charge to refund"
    split = money.refund_split_after(charging.charged_split(visit, charge, "visit", s), charge.refunded_pence, amount)
    refunded = charge.refunded_pence + amount
    await Visits(db).update(
        visit.id,
        {
            "charge.refunded_pence": refunded,
            "charge.status": "refunded" if refunded >= charge.amount_pence else "partially_refunded",
            "charge.refund_ids": [*charge.refund_ids, re["id"]],
        },
        session=session,
    )
    await ledger.record_refund(db, visit, split, at=utcnow(), gateway="stripe", refund_id=re["id"], session=session)
    await notices.refunded(db, s, visit, amount, key=f"refund:{re['id']}", session=session)
    await audit(
        db,
        SYSTEM,
        "payment.refund_external",
        Related(visit_id=visit.id, booking_id=visit.booking_id, provider_id=visit.provider_id),
        before={"refunded_pence": charge.refunded_pence},
        after={
            "refund_id": re["id"],
            "refunded_pence": refunded,
            "fee_pence": split.fee_pence,
            "provider_pence": split.provider_pence,
        },
        note="Refunded outside the admin console. The ledger assumes our usual provider-funded split: "
        "check the transfer reversal and fee refund in Stripe.",
        session=session,
    )
    return "applied", f"external refund {re['id']} of {amount}p"


async def _replay(db: Db, s: Settings, ev: PaymentEvent, session: DbSession) -> Outcome:
    payload = ev.payload or {}
    if ev.type == "charge.refunded":
        return await charge_refunded(db, s, payload, session)
    return await refund_updated(db, s, payload, session)


async def replay_all_deferred(db: Db, s: Settings, *, limit: int = 100) -> int:
    """For the periodic task: try every deferred event again, each in its own transaction (one can
    be stranded if its charge settled at the very moment it was deferred). Returns how many were
    applied."""
    applied = 0
    for ev in await PaymentEvents(db).find({"outcome": "deferred"}, sort=[("received_at", 1)], limit=limit):

        async def replay(session: DbSession, ev=ev) -> bool:
            fresh = await PaymentEvents(db).get(ev.id, session=session)
            if fresh is None or fresh.outcome != "deferred":
                return False
            outcome, note = await _replay(db, s, fresh, session)
            if outcome == "deferred":
                return False
            await PaymentEvents(db).set_outcome(ev.id, outcome, f"replayed: {note}", session=session)
            return True

        try:
            applied += await transaction(db, replay)
        except Exception:
            log.exception("couldn't replay stripe event %s", ev.id)
    return applied


async def replay_deferred(db: Db, s: Settings, payment_intent: str, *, session: DbSession) -> None:
    """Called in the transaction that records a charge's success: apply the refund events that
    arrived before it."""
    events = PaymentEvents(db)
    for ev in await events.deferred_for(payment_intent, session=session):
        outcome, note = await _replay(db, s, ev, session)
        if outcome != "deferred":
            await events.set_outcome(ev.id, outcome, f"replayed: {note}", session=session)


async def refund_updated(db: Db, s: Settings, re: Json, session: DbSession) -> Outcome:
    """A refund moved on at Stripe. One we asked for is recorded when it succeeds (our fee goes
    back to the provider afterwards, from the settle task: no Stripe call here) or released if it
    failed; any other (the dashboard) is recorded by its id once it succeeds."""
    refunds = PaymentRefunds(db)
    intent = await refunds.by_refund_id(re.get("id", ""), session=session)
    meta_intent = (re.get("metadata") or {}).get("intent")
    if intent is None and meta_intent:
        intent = await refunds.get(meta_intent, session=session)
    if intent is None:
        return await external_refund(db, s, re, session)
    state = refund_state(re)
    if intent.status in ("succeeded", "fee_pending") and state.status == "failed":
        await audit(
            db,
            SYSTEM,
            "payment.refund_failed_after_recording",
            Related(visit_id=intent.visit_id, dispute_id=intent.dispute_id),
            after={"intent_id": intent.id, "refund_id": re.get("id"), "amount_pence": intent.amount_pence},
            note="Stripe reports this refund failed after it had succeeded. Check it in Stripe and adjust by hand.",
            session=session,
        )
        return "applied", "failed after recording: needs a look"
    before = intent.status
    after = await apply_refund_result(db, s, intent.id, state, SYSTEM, session=session)
    return ("applied", f"{before} -> {after.status}") if after and after.status != before else ("ignored", "no change")


async def _provider_for_account(db: Db, account_id: str | None, session: DbSession):
    if not account_id:
        return None
    return await Providers(db).find_one({"payment_account.account_id": account_id}, session=session)


async def account_updated(db: Db, s: Settings, acct: Json, session: DbSession) -> Outcome:
    provider = await _provider_for_account(db, acct.get("id"), session)
    if provider is None or provider.payment_account is None:
        return "no_match", "no provider with that account"
    state = provider_account_from_stripe(acct)
    before = provider.payment_account
    after = before.model_copy(
        update={
            "status": state.status,
            "payouts_enabled": state.payouts_enabled,
            "bank_last4": state.bank_last4 or before.bank_last4,
        }
    )
    if after == before:
        return "ignored", "no change"
    await Providers(db).patch(provider.id, {"payment_account": after.model_dump(mode="python")}, session=session)
    await audit(
        db,
        SYSTEM,
        "provider.payment_account_synced",
        Related(provider_id=provider.id),
        before=before.model_dump(mode="json"),
        after=after.model_dump(mode="json"),
        session=session,
    )
    await lifecycle.activate_if_ready(db, s, provider.id, actor=SYSTEM, session=session)
    return "applied", state.status


async def payout_paid(db: Db, s: Settings, account_id: str | None, po: Json, session: DbSession) -> Outcome:
    provider = await _provider_for_account(db, account_id, session)
    if provider is None:
        return "no_match", "no provider with that account"
    dest = po.get("destination")
    last4 = dest.get("last4") if isinstance(dest, dict) else None
    await notices.payout_sent(
        db,
        s,
        provider,
        payout_id=po["id"],
        amount_pence=int(po.get("amount") or 0),
        last4=last4 or (provider.payment_account.bank_last4 if provider.payment_account else None),
        session=session,
    )
    return "applied", "payout_sent"


async def payout_failed(db: Db, account_id: str | None, po: Json, session: DbSession) -> Outcome:
    provider = await _provider_for_account(db, account_id, session)
    if provider is None:
        return "no_match", "no provider with that account"
    await audit(
        db,
        SYSTEM,
        "payment.payout_failed",
        Related(provider_id=provider.id),
        after={"payout_id": po.get("id"), "amount_pence": po.get("amount")},
        note=po.get("failure_message") or po.get("failure_code") or "",
        session=session,
    )
    return "applied", "logged"
