"""Stripe webhooks: the source of truth for final payment states.

Every event is verified against STRIPE_WEBHOOK_SECRET (the Stripe-Signature header), then
applied in ONE transaction with its record in payment_events, keyed by the event id: Stripe
delivers at least once and may retry, and a second delivery finds the record and changes
nothing. Handlers only read the event and Mongo (no calls to Stripe), so the transaction
holds nothing outside the database. Events may arrive out of order: a payment event applies
only to the attempt named in its metadata (its idempotency key) and never undoes a success.

Handled: payment_intent.* (succeeded, payment_failed, requires_action, processing, canceled),
charge.refunded, account.updated, payout.paid and payout.failed. Anything else is logged and
acknowledged. Live-mode events are ignored while DEMO_MODE is on.
"""

import json
import logging
from typing import Any

import stripe

from app.adapters.payments.stripe_gateway import charge_result_from_intent, provider_account_from_stripe
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.timeutil import utcnow
from app.models.common import Related
from app.models.payments import PaymentEvent
from app.payments import charging, notices
from app.payments.refunds import refund_split_for
from app.repos.payments import PaymentEvents, PaymentRefunds
from app.repos.providers import Providers
from app.repos.visits import Visits
from app.services import ledger
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
        await events.set_outcome(record.id, outcome, note, session=session)
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
        case "account.updated":
            return await account_updated(db, obj, session)
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


async def charge_refunded(db: Db, s: Settings, ch: Json, session: DbSession) -> Outcome:
    """Refunds made in the admin console are recorded as they're made; this confirms them and
    records any made elsewhere (the Stripe dashboard) so the ledger matches Stripe."""
    visits = Visits(db)
    visit = await visits.find_one({"charge.charge_id": ch.get("id")}, session=session)
    if visit is None:
        return "no_match", "no visit charge with that id"
    charge = visit.charge
    unsettled = await PaymentRefunds(db).unsettled_pence(visit.id, session=session)
    known = charge.refunded_pence + unsettled
    extra = min(int(ch.get("amount_refunded") or 0), charge.amount_pence) - known
    if extra <= 0:
        return "ignored", "refunds already recorded"
    split = refund_split_for(charging.charged_split(visit, charge, "visit", s), known, extra)
    refunded = charge.refunded_pence + extra
    ref = f"{ch['id']}:external:{ch.get('amount_refunded')}"
    await visits.update(
        visit.id,
        {
            "charge.refunded_pence": refunded,
            "charge.status": "refunded" if refunded >= charge.amount_pence else "partially_refunded",
            "charge.refund_ids": [*charge.refund_ids, ref],
        },
        session=session,
    )
    await ledger.record_refund(db, visit, split, at=utcnow(), gateway="stripe", refund_id=ref, session=session)
    await notices.refunded(db, s, visit, extra, key=f"refund:{ref}", session=session)
    await audit(
        db,
        SYSTEM,
        "payment.refund_external",
        Related(visit_id=visit.id, booking_id=visit.booking_id, provider_id=visit.provider_id),
        before={"refunded_pence": charge.refunded_pence},
        after={"refunded_pence": refunded, "fee_pence": split.fee_pence, "provider_pence": split.provider_pence},
        note="Refunded outside the admin console. The ledger assumes our usual provider-funded split: "
        "check the transfer reversal and fee refund in Stripe.",
        session=session,
    )
    return "applied", f"external refund of {extra}p"


async def _provider_for_account(db: Db, account_id: str | None, session: DbSession):
    if not account_id:
        return None
    return await Providers(db).find_one({"payment_account.account_id": account_id}, session=session)


async def account_updated(db: Db, acct: Json, session: DbSession) -> Outcome:
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
