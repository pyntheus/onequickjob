"""Refunding a visit's charge: provider-funded, through the gateway (decisions.md R16).

Like charging, no gateway call inside a transaction:

1. record the refund intent (payment_refunds). One refund of a visit at a time: a new one waits
   until the last is confirmed, and it must fit in what's left. The intent writes the visit too,
   so two refunds asked for at once conflict and the second sees the first.
2. call PaymentGateway.refund with the intent's id as the idempotency key.
3. record the result in one transaction. Only once the customer's refund has SUCCEEDED does
   anything move: the visit's charge, the ledger refund entry (negative amounts,
   gross == fee + net), the customer's message and the audit entry. A refund the gateway is
   still processing, or whose outcome we couldn't learn, stays pending and reserved; the
   refund webhook, a repeat (same key, only while the refund id is unknown) or the settle task
   finishes it. Our fee goes back to the provider after the customer's refund succeeds (status
   fee_pending until it has).

The split comes from money.refund_split, used cumulatively over CONFIRMED refunds: a refund
returns the fee for everything refunded so far less the fee already returned. One refund is
exactly money.refund_split; several add up to what a single refund of their total would
return, so a full refund always returns exactly the fee and the provider's share.
"""

import logging
from datetime import timedelta
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
from app.services.audit import SYSTEM, audit

log = logging.getLogger("oqj.payments")

REFUNDABLE = ("succeeded", "partially_refunded")
# Stripe keeps idempotency keys for 24 hours; repeats that could move money stop before then.
RETRY_WINDOW = timedelta(hours=23)
IN_FLIGHT = timedelta(seconds=60)
BY_HAND = (
    "This refund was asked for over a day ago and isn't finished. Check it in the Stripe dashboard before trying again."
)


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


def _out(intent: RefundIntent) -> RefundOut:
    status_: Literal["succeeded", "pending", "failed"] = (
        "succeeded" if intent.status == "succeeded" else "failed" if intent.status == "failed" else "pending"
    )
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


def within_retry_window(intent: RefundIntent) -> bool:
    """created_at never changes, so retries can't keep themselves alive past the key's life."""
    return utcnow() - intent.created_at < RETRY_WINDOW


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
    intent_id: str | None = None,
) -> RefundOut:
    """Refund part or all of a visit's charge. With intent_id (a dispute's close), the same id
    always means the same refund: a repeat resumes it instead of refunding again."""
    refunds = PaymentRefunds(db)
    if intent_id and (existing := await refunds.get(intent_id)) is not None:
        return await resume(db, s, gateway, existing, actor)
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

    async def record_intent(session: DbSession) -> tuple[RefundIntent, bool]:
        if intent_id and (same := await refunds.get(intent_id, session=session)) is not None:
            return same, False
        v = await get_visit(db, visit_id, session)
        if v.charge.status not in REFUNDABLE or v.charge.charge_id != visit.charge.charge_id:
            fail(status.HTTP_409_CONFLICT, "charge_changed", "This payment has just changed. Have another look.")
        if await refunds.unsettled(visit_id, session=session):
            fail(
                status.HTTP_409_CONFLICT,
                "refund_in_progress",
                "A refund of this visit is still being processed (or a failed one's money is being given back to "
                "the provider). Try again once it has.",
            )
        left = refundable_left(v, 0)
        if amount_pence > left:
            fail(
                status.HTTP_409_CONFLICT,
                "more_than_paid",
                f"That's more than is left to refund ({wording.money(left)}).",
                left_pence=left,
            )
        split = money.refund_split_after(original, v.charge.refunded_pence, amount_pence)
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
        if intent_id:
            intent.id = intent_id
        await refunds.insert(intent, session=session)
        # Writing the visit makes two refunds of it at once conflict: the driver re-runs one,
        # which then sees the other's intent.
        await Visits(db).update(visit_id, {}, session=session)
        return intent, True

    intent, new = await transaction(db, record_intent)
    if not new:
        return await resume(db, s, gateway, intent, actor)
    return await send_refund(db, s, gateway, intent, actor)


async def send_refund(db: Db, s: Settings, gateway: PaymentGateway, intent: RefundIntent, actor: Actor) -> RefundOut:
    """Ask the gateway to make the refund. Only for an intent whose refund id is unknown, within
    the key's life: the key makes a repeat return the refund already made."""
    try:
        result = await gateway.refund(
            intent.charge_id, intent.amount_pence, intent.fee_pence, reason=intent.reason, idempotency_key=intent.id
        )
    except Exception:
        log.exception("refund %s for visit %s: outcome unknown", intent.id, intent.visit_id)
        result = RefundResult(
            status="pending",
            amount_pence=intent.amount_pence,
            fee_refunded_pence=0,
            failure_reason="We couldn't get an answer from the payment provider.",
        )
    return await record_refund_result(db, s, intent.id, result, actor, gateway)


async def resume(db: Db, s: Settings, gateway: PaymentGateway, intent: RefundIntent, actor: Actor) -> RefundOut:
    """Carry an unfinished refund forward without ever making a second one."""
    if intent.status in ("succeeded", "failed"):
        return _finish(intent)
    can_move = within_retry_window(intent)  # repeats that could move money: only while the key lives
    if intent.status == "fee_pending":
        if not can_move:
            fail(status.HTTP_409_CONFLICT, "check_by_hand", BY_HAND)
        fee = await gateway.refund_fee(intent.charge_id, intent.fee_pence, idempotency_key=f"{intent.id}:fee")
        return await record_refund_result(db, s, intent.id, _fee_step(intent, fee), actor, gateway)
    if intent.refund_id:  # made, not yet confirmed: read it, never make it again
        result = await gateway.refund_status(intent.refund_id)
        if result.status == "succeeded" and intent.fee_pence > 0 and can_move:
            fee = await gateway.refund_fee(intent.charge_id, intent.fee_pence, idempotency_key=f"{intent.id}:fee")
            result = result.model_copy(
                update={"fee_refunded_pence": fee.fee_refunded_pence, "failure_reason": fee.failure_reason}
            )
        return await record_refund_result(db, s, intent.id, result, actor, gateway)
    if not can_move:
        fail(status.HTTP_409_CONFLICT, "check_by_hand", BY_HAND)
    if utcnow() - intent.created_at < IN_FLIGHT:
        return _out(intent)  # its first request is probably still going: don't race it
    return await send_refund(db, s, gateway, intent, actor)


def _fee_step(intent: RefundIntent, fee: RefundResult) -> RefundResult:
    """The fee step's result, as a result for an intent whose customer refund succeeded."""
    return RefundResult(
        status="succeeded",
        refund_id=intent.refund_id,
        amount_pence=intent.amount_pence,
        fee_refunded_pence=fee.fee_refunded_pence if fee.status == "succeeded" else 0,
        failure_reason=fee.failure_reason,
    )


def _finish(intent: RefundIntent) -> RefundOut:
    if intent.status == "failed":
        fail(
            status.HTTP_502_BAD_GATEWAY,
            "refund_failed",
            f"The refund didn't go through: {intent.failure_reason or 'the payment provider refused it.'}",
        )
    return _out(intent)


async def apply_refund_result(
    db: Db, s: Settings, intent_id: str, result: RefundResult, actor: Actor, *, session: DbSession
) -> RefundIntent | None:
    """Inside a transaction: move an intent to the gateway's answer. The money is recorded when,
    and only when, the customer's refund first shows as succeeded."""
    refunds = PaymentRefunds(db)
    current = await refunds.get(intent_id, session=session)
    if current is None or current.status in ("succeeded", "failed"):
        return current
    visit = await get_visit(db, current.visit_id, session)
    target = _target(visit, current.dispute_id)
    if result.status == "pending":
        if current.status == "pending":
            return await refunds.note_pending(
                intent_id, refund_id=result.refund_id, failure_reason=result.failure_reason, session=session
            )
        return current
    if result.status == "failed":
        if current.status == "fee_pending":  # the customer has their money; only our fee is stuck
            return current
        made = result.refund_id or current.refund_id
        settled = await refunds.settle(
            intent_id, "failed", refund_id=made, failure_reason=result.failure_reason, session=session
        )
        if made and settled is not None:
            # It was made with reverse_transfer: a failed refund's money returns to the platform,
            # not the provider, so their transfer is restored (outside this transaction).
            settled = await refunds.update(intent_id, {"restore": "needed"}, session=session)
        await audit(
            db,
            actor,
            "payment.refund_failed",
            target,
            after={"amount_pence": current.amount_pence, "intent_id": intent_id, "refund_id": result.refund_id},
            note=result.failure_reason or "",
            session=session,
        )
        if settled is not None:
            await _dispute_hook(db, s, settled, succeeded=False, session=session)
        return settled
    fee_done = current.fee_pence == 0 or result.fee_refunded_pence >= current.fee_pence
    settled = await refunds.settle(
        intent_id,
        "succeeded" if fee_done else "fee_pending",
        refund_id=result.refund_id or current.refund_id,
        failure_reason=None if fee_done else result.failure_reason,
        session=session,
    )
    if current.status == "pending":  # the customer's money moved: record it once
        charge = visit.charge
        refunded = charge.refunded_pence + current.amount_pence
        refund_id = result.refund_id or current.refund_id
        await Visits(db).update(
            visit.id,
            {
                "charge.refunded_pence": refunded,
                "charge.status": "refunded" if refunded >= charge.amount_pence else "partially_refunded",
                "charge.refund_ids": [*charge.refund_ids, refund_id or intent_id],
            },
            session=session,
        )
        await ledger.record_refund(
            db,
            visit,
            intent_split(visit, current, s),
            at=utcnow(),
            gateway=current.gateway,
            refund_id=refund_id,
            session=session,
        )
        await notices.refunded(
            db,
            s,
            visit,
            current.amount_pence,
            key=f"refund:{intent_id}",
            session=session,
            dispute_id=current.dispute_id,
        )
        await audit(
            db,
            actor,
            "payment.refunded",
            target,
            before={"refunded_pence": charge.refunded_pence, "status": charge.status},
            after={
                "refunded_pence": refunded,
                "amount_pence": current.amount_pence,
                "fee_pence": current.fee_pence,
                "provider_pence": current.provider_pence,
                "refund_id": refund_id,
                "funded_by": "provider",
            },
            note=current.reason,
            session=session,
        )
        if settled is not None:
            await _dispute_hook(db, s, settled, succeeded=True, session=session)
    return settled


async def _dispute_hook(db: Db, s: Settings, intent: RefundIntent, *, succeeded: bool, session: DbSession) -> None:
    """A dispute closing with this refund closes now it's confirmed (or is released if it failed)."""
    if intent.dispute_id:
        from app.admin.disputes import on_refund_settled

        await on_refund_settled(db, s, intent, succeeded=succeeded, session=session)


async def record_refund_result(
    db: Db, s: Settings, intent_id: str, result: RefundResult, actor: Actor, gateway: PaymentGateway | None = None
) -> RefundOut:
    async def record(session: DbSession) -> RefundIntent | None:
        return await apply_refund_result(db, s, intent_id, result, actor, session=session)

    final = await transaction(db, record)
    assert final is not None
    if final.restore == "needed" and gateway is not None:
        try:
            final = await restore_provider(db, gateway, final)
        except Exception:
            log.exception("couldn't restore the provider's money for refund %s (the task retries)", intent_id)
    return _finish(final)


async def restore_provider(db: Db, gateway: PaymentGateway, intent: RefundIntent) -> RefundIntent:
    """Give the provider back what a failed refund's transfer reversal took. Idempotent (its own
    key), retried by the settle task until done, within the key's life from the failure."""
    if intent.restore != "needed":
        return intent
    failed_at = intent.recorded_at or intent.updated_at
    if utcnow() - failed_at >= RETRY_WINDOW:
        return intent  # stays visible in the overview for a transfer by hand
    res = await gateway.restore_transfer(intent.charge_id, intent.amount_pence, idempotency_key=f"{intent.id}:restore")
    if res.status != "succeeded":
        log.warning("restoring the provider's money for refund %s: %s", intent.id, res.failure_reason)
        return intent

    async def done(session: DbSession) -> RefundIntent | None:
        updated = await PaymentRefunds(db).update(
            intent.id,
            {"restore": "done", "restore_transfer_id": res.transfer_id},
            extra_filter={"restore": "needed"},
            session=session,
        )
        if updated is not None:
            visit = await get_visit(db, intent.visit_id, session)
            await audit(
                db,
                SYSTEM,
                "payment.transfer_restored",
                _target(visit, intent.dispute_id),
                after={"intent_id": intent.id, "amount_pence": intent.amount_pence, "transfer_id": res.transfer_id},
                note="A failed refund's transfer reversal, given back to the provider.",
                session=session,
            )
        return updated

    return await transaction(db, done) or intent


async def settle_open_refunds(db: Db, s: Settings, gateway: PaymentGateway, *, older_than: timedelta) -> int:
    """For the periodic task: carry forward refunds left unfinished (pending at the gateway, an
    unknown outcome, our fee still to return), within the key's life. Returns how many it tried."""
    now = utcnow()
    tried = 0
    for intent in await PaymentRefunds(db).find(
        {
            "status": {"$in": ["pending", "fee_pending"]},
            "created_at": {"$lte": now - older_than, "$gte": now - RETRY_WINDOW},
        },
        limit=50,
    ):
        tried += 1
        try:
            await resume(db, s, gateway, intent, SYSTEM)
        except Exception:
            log.exception("couldn't settle refund %s", intent.id)
    for intent in await PaymentRefunds(db).find({"restore": "needed"}, limit=50):
        tried += 1
        try:
            await restore_provider(db, gateway, intent)
        except Exception:
            log.exception("couldn't restore the provider's money for refund %s", intent.id)
    return tried
