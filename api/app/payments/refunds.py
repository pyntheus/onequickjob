"""Refunding a visit's charge: provider-funded, through the gateway (decisions.md R16).

Like charging, three steps and no gateway call inside a transaction:

1. record the refund intent (payment_refunds), checking in the same transaction that it fits
   in what's left to refund (concurrent refunds of one visit conflict, so one re-checks);
2. call PaymentGateway.refund with the intent's id as the idempotency key;
3. record the result in one transaction: the visit's charge, the ledger refund entry (negative
   amounts, gross == fee + net), the customer's message and the audit entry.

The split comes from money.refund_split, used cumulatively: a refund returns the fee for
everything refunded so far less the fee already returned. One refund is exactly
money.refund_split; several partial ones add up to what a single refund of their total would
return, so a full refund always returns exactly the fee and the provider's share.
"""

import logging
from typing import Literal

from fastapi import status

from app.adapters.payments.base import PaymentGateway, RefundResult
from app.admin.schemas import RefundOut
from app.core import money
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail
from app.core.timeutil import utcnow
from app.models.common import Actor, Related
from app.models.payments import RefundIntent
from app.models.visits import Visit
from app.payments import notices
from app.payments.charging import charged_split, get_visit
from app.repos.payments import PaymentRefunds
from app.repos.visits import Visits
from app.services import ledger, wording
from app.services.audit import audit

log = logging.getLogger("oqj.payments")

REFUNDABLE = ("succeeded", "partially_refunded")


def refund_split_for(original: money.Split, already_pence: int, amount_pence: int) -> money.Split:
    """The split of a refund of amount_pence when already_pence has been refunded before."""
    before = money.refund_split(original, already_pence)
    after = money.refund_split(original, already_pence + amount_pence)
    fee = after.fee_pence - before.fee_pence
    return money.Split(amount_pence, fee, amount_pence - fee, original.mode, original.rate)


def intent_split(visit: Visit, intent: RefundIntent, s: Settings) -> money.Split:
    original = charged_split(visit, visit.charge, "visit", s)
    return money.Split(intent.amount_pence, intent.fee_pence, intent.provider_pence, original.mode, original.rate)


def _target(visit: Visit, dispute_id: str | None) -> Related:
    return Related(
        visit_id=visit.id,
        booking_id=visit.booking_id,
        customer_id=visit.customer_id,
        provider_id=visit.provider_id,
        dispute_id=dispute_id,
    )


def _out(intent: RefundIntent, status_: Literal["succeeded", "pending", "failed"]) -> RefundOut:
    return RefundOut(
        visit_id=intent.visit_id,
        status=status_,
        refund_id=intent.refund_id,
        amount_pence=intent.amount_pence,
        fee_refunded_pence=intent.fee_pence,
        provider_refunded_pence=intent.provider_pence,
    )


def refundable_left(visit: Visit, unsettled_pence: int) -> int:
    return max(visit.charge.amount_pence - visit.charge.refunded_pence - unsettled_pence, 0)


async def refund_visit(
    db: Db,
    s: Settings,
    gateway: PaymentGateway,
    visit_id: str,
    amount_pence: int,
    reason: str,
    actor: Actor,
    *,
    dispute_id: str | None = None,
) -> RefundOut:
    visit = await get_visit(db, visit_id)
    if visit.charge.status not in REFUNDABLE or not visit.charge.charge_id:
        fail(status.HTTP_409_CONFLICT, "not_paid", "Only a visit that's been paid can be refunded.")
    if (visit.charge.gateway or "fake") != gateway.name:
        fail(
            status.HTTP_409_CONFLICT,
            "other_gateway",
            f"This visit was paid through the {visit.charge.gateway} gateway, so it can't be refunded through "
            f"{gateway.name}.",
        )
    original = charged_split(visit, visit.charge, "visit", s)

    async def record_intent(session: DbSession) -> RefundIntent:
        v = await get_visit(db, visit_id, session)
        if v.charge.status not in REFUNDABLE or v.charge.charge_id != visit.charge.charge_id:
            fail(status.HTTP_409_CONFLICT, "charge_changed", "This payment has just changed. Have another look.")
        unsettled = await PaymentRefunds(db).unsettled_pence(visit_id, session=session)
        left = refundable_left(v, unsettled)
        if amount_pence > left:
            fail(
                status.HTTP_409_CONFLICT,
                "more_than_paid",
                f"That's more than is left to refund ({wording.money(left)}).",
                left_pence=left,
            )
        split = refund_split_for(original, v.charge.refunded_pence + unsettled, amount_pence)
        intent = RefundIntent(
            visit_id=visit_id,
            charge_id=v.charge.charge_id or "",
            dispute_id=dispute_id,
            gateway=gateway.name,
            amount_pence=split.price_pence,
            fee_pence=split.fee_pence,
            provider_pence=split.provider_pence,
            reason=reason,
            requested_by=actor.user_id,
        )
        await PaymentRefunds(db).insert(intent, session=session)
        # Writing the visit makes two refunds of it at once conflict: the driver re-runs one,
        # which then sees the other's intent in what's left.
        await Visits(db).update(visit_id, {}, session=session)
        return intent

    intent = await transaction(db, record_intent)
    return await send_refund(db, s, gateway, intent, actor)


async def send_refund(db: Db, s: Settings, gateway: PaymentGateway, intent: RefundIntent, actor: Actor) -> RefundOut:
    """Steps 2 and 3. Safe to repeat for an unsettled intent: the gateway sees the same key."""
    try:
        result = await gateway.refund(
            intent.charge_id, intent.amount_pence, intent.fee_pence, reason=intent.reason, idempotency_key=intent.id
        )
    except Exception:
        log.exception("refund %s for visit %s failed unexpectedly", intent.id, intent.visit_id)
        return _out(intent, "pending")
    return await record_refund_result(db, s, intent, result, actor)


async def record_refund_result(
    db: Db, s: Settings, intent: RefundIntent, result: RefundResult, actor: Actor
) -> RefundOut:
    refunds = PaymentRefunds(db)

    async def record(session: DbSession) -> RefundIntent:
        current = await refunds.get(intent.id, session=session)
        assert current is not None
        if current.status in ("succeeded", "failed"):
            return current
        visit = await get_visit(db, intent.visit_id, session)
        target = _target(visit, intent.dispute_id)
        if result.status == "failed":
            settled = await refunds.settle(
                intent.id, "failed", refund_id=result.refund_id, failure_reason=result.failure_reason, session=session
            )
            await audit(
                db,
                actor,
                "payment.refund_failed",
                target,
                after={"amount_pence": intent.amount_pence, "intent_id": intent.id},
                note=result.failure_reason or "",
                session=session,
            )
            return settled or current
        fee_done = intent.fee_pence == 0 or result.fee_refunded_pence >= intent.fee_pence
        settled = await refunds.settle(
            intent.id,
            "succeeded" if fee_done else "fee_pending",
            refund_id=result.refund_id,
            failure_reason=None if fee_done else result.failure_reason,
            session=session,
        )
        if current.status == "pending":  # the customer's money moved: record it once
            charge = visit.charge
            refunded = charge.refunded_pence + intent.amount_pence
            await Visits(db).update(
                visit.id,
                {
                    "charge.refunded_pence": refunded,
                    "charge.status": "refunded" if refunded >= charge.amount_pence else "partially_refunded",
                    "charge.refund_ids": [*charge.refund_ids, result.refund_id or intent.id],
                },
                session=session,
            )
            await ledger.record_refund(
                db,
                visit,
                intent_split(visit, intent, s),
                at=utcnow(),
                gateway=intent.gateway,
                refund_id=result.refund_id,
                session=session,
            )
            await notices.refunded(
                db,
                s,
                visit,
                intent.amount_pence,
                key=f"refund:{intent.id}",
                session=session,
                dispute_id=intent.dispute_id,
            )
            await audit(
                db,
                actor,
                "payment.refunded",
                target,
                before={"refunded_pence": charge.refunded_pence, "status": charge.status},
                after={
                    "refunded_pence": refunded,
                    "amount_pence": intent.amount_pence,
                    "fee_pence": intent.fee_pence,
                    "provider_pence": intent.provider_pence,
                    "refund_id": result.refund_id,
                    "funded_by": "provider",
                },
                note=intent.reason,
                session=session,
            )
        return settled or current

    final = await transaction(db, record)
    if final.status == "failed":
        fail(
            status.HTTP_502_BAD_GATEWAY,
            "refund_failed",
            f"The refund didn't go through: {final.failure_reason or 'the payment provider refused it.'}",
        )
    return _out(final, "succeeded" if final.status == "succeeded" else "pending")
