"""Charging a visit (or its tip) through the PaymentGateway.

Three steps, never one transaction (CLAUDE.md, "Writing to several collections"):

1. record the intent on the visit: charge.status pending, the attempt's idempotency key and
   the amounts: the visit's stored price (the first-visit or per-visit price, A1) split by
   money.split_for_visit (the own-customer rate only for the provider who brought the
   customer or their helper; a cover provider pays the standard fee, A4);
2. call PaymentGateway.charge_visit with that key, so repeating the call can't charge twice;
3. record the result in one transaction: the charge state, the ledger entry and the messages.

Webhooks (app.payments.webhooks) settle the final state through the same step 3. L2's finish
endpoint can call charge_visit once it has saved the finished visit; the admin's "Retry
charge" calls retry_charge, which starts a new attempt with a new key after cancelling the
old one (a declined attempt's key would return the same decline for 24 hours).
"""

import logging
import re
from datetime import timedelta
from typing import Literal

from fastapi import status

from app.adapters.payments.base import PLATFORM_FAILURE, ChargeResult, PaymentGateway, VisitRef
from app.core import money
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.core.timeutil import utcnow
from app.models.common import Actor, Related
from app.models.payments import ChargeAttempt
from app.models.visits import Charge, Visit
from app.payments import notices
from app.repos.payments import ChargeAttempts
from app.repos.visits import Visits
from app.services import ledger, wording
from app.services.audit import audit

log = logging.getLogger("oqj.payments")

type Purpose = Literal["visit", "tip"]
SETTLED = ("succeeded", "refunded", "partially_refunded")
RETRYABLE = ("failed", "requires_action")
OPEN = ("pending", *RETRYABLE)
UNKNOWN = "We couldn't reach the payment provider, so this payment is waiting to be checked."
RETRY = re.compile(r":retry(\d+)$")
KEY_LIFE = timedelta(hours=23)  # Stripe keeps idempotency keys for 24 hours
IN_FLIGHT = timedelta(seconds=60)


def field_for(purpose: Purpose) -> str:
    return "charge" if purpose == "visit" else "tip_charge"


def charge_of(visit: Visit, purpose: Purpose) -> Charge | None:
    return visit.charge if purpose == "visit" else visit.tip_charge


def attempt_key(visit_id: str, purpose: Purpose, attempt: int = 1) -> str:
    """visit:<id>:visit for the first attempt (the gateway's default key), then :retry2, :retry3..."""
    base = f"visit:{visit_id}:{purpose}"
    return base if attempt <= 1 else f"{base}:retry{attempt}"


def next_attempt_key(visit_id: str, purpose: Purpose, current: str | None) -> str:
    m = RETRY.search(current or "")
    return attempt_key(visit_id, purpose, (int(m.group(1)) if m else 1) + 1)


def split_to_charge(visit: Visit, purpose: Purpose, s: Settings) -> money.Split:
    if purpose == "tip":
        return money.split(visit.tip_pence, "tip", s)
    return money.split_for_visit(visit.price_pence, visit.source, visit.performer.kind, s)


def charged_split(visit: Visit, charge: Charge, purpose: Purpose, s: Settings) -> money.Split:
    """What the attempt charged (the amounts recorded with its intent), for the ledger and refunds."""
    mode: money.FeeMode = "tip" if purpose == "tip" else money.mode_for_visit(visit.source, visit.performer.kind)
    return money.Split(
        price_pence=charge.amount_pence,
        fee_pence=charge.fee_pence,
        provider_pence=charge.provider_pence,
        mode=mode,
        rate=money.split(charge.amount_pence, mode, s).rate,
    )


async def get_visit(db: Db, visit_id: str, session: DbSession | None = None) -> Visit:
    visit = await Visits(db).get(visit_id, session=session)
    if visit is None:
        not_found("That visit")
    return visit


def _failed(reason: str, code: str, split: money.Split, key: str) -> ChargeResult:
    return ChargeResult(
        status="failed",
        amount_pence=split.price_pence,
        fee_pence=split.fee_pence,
        idempotency_key=key,
        failure_reason=reason,
        failure_code=code,
        created_at=utcnow(),
    )


def _cannot_charge(p: notices.Parties, gateway: PaymentGateway, split: money.Split, key: str) -> ChargeResult | None:
    """Reasons not to call the gateway at all, as a failed result."""
    pay = p.customer.payment if p.customer else None
    if pay is None or not pay.gateway_customer_id or pay.setup_status != "succeeded":
        return _failed("There's no saved card for this customer.", "no_saved_card", split, key)
    if pay.gateway != gateway.name:
        return _failed(
            f"The customer's card was saved with the {pay.gateway} gateway, not {gateway.name}.",
            PLATFORM_FAILURE + "gateway_mismatch",
            split,
            key,
        )
    account = p.provider.payment_account if p.provider else None
    if account is None:
        return _failed(
            "The provider's payment account isn't set up yet.", PLATFORM_FAILURE + "no_provider_account", split, key
        )
    if account.gateway != gateway.name:
        return _failed(
            f"The provider's payment account is with the {account.gateway} gateway, not {gateway.name}.",
            PLATFORM_FAILURE + "gateway_mismatch",
            split,
            key,
        )
    return None


async def apply_result(
    db: Db, s: Settings, visit_id: str, purpose: Purpose, key: str, result: ChargeResult, *, session: DbSession
) -> bool:
    """Inside a transaction: move one attempt's charge to the gateway's state, with its ledger
    entry and messages. False if that attempt was already settled or has been replaced."""
    field = field_for(purpose)
    visits = Visits(db)
    before = await visits.get(visit_id, session=session)
    charge = charge_of(before, purpose) if before else None
    if before is None or charge is None or charge.idempotency_key != key or charge.status not in OPEN:
        return False
    succeeded = result.status == "succeeded"
    new = charge.model_copy(
        update={
            "status": result.status,
            "payment_intent_id": result.payment_intent_id or charge.payment_intent_id,
            "charge_id": result.charge_id if succeeded else None,
            "charged_at": utcnow() if succeeded else None,
            "failure_reason": None if succeeded else result.failure_reason,
        }
    )
    if new == charge:
        return False
    updated = await visits.update(
        visit_id,
        {field: new.model_dump(mode="python")},
        extra_filter={f"{field}.idempotency_key": key, f"{field}.status": charge.status},
        session=session,
    )
    if updated is None:  # pragma: no cover - the transaction's snapshot makes this a write conflict
        return False
    if succeeded:
        at = new.charged_at or utcnow()
        gateway = new.gateway or "fake"
        if purpose == "visit":
            split = charged_split(updated, new, purpose, s)
            await ledger.record_charge(
                db, updated, split, at=at, gateway=gateway, charge_id=new.charge_id, session=session
            )
            await notices.charged(db, s, updated, new, session)
            if new.payment_intent_id:
                # Refund events that arrived before this success was recorded apply now.
                from app.payments.webhooks import replay_deferred

                await replay_deferred(db, s, new.payment_intent_id, session=session)
        else:
            await ledger.record_tip(
                db, updated, new.amount_pence, at=at, gateway=gateway, charge_id=new.charge_id, session=session
            )
    elif result.status in RETRYABLE and purpose == "visit":
        await notices.charge_failed(
            db,
            s,
            updated,
            new,
            attempt_key=key,
            tell_customer=not (result.failure_code or "").startswith(PLATFORM_FAILURE),
            session=session,
        )
    return True


async def record_result(db: Db, s: Settings, visit_id: str, purpose: Purpose, key: str, result: ChargeResult) -> Visit:
    async def record(session: DbSession) -> bool:
        return await apply_result(db, s, visit_id, purpose, key, result, session=session)

    await transaction(db, record)
    return await get_visit(db, visit_id)


async def _record_intent(
    db: Db,
    visit: Visit,
    purpose: Purpose,
    split: money.Split,
    gateway_name: str,
    key: str,
    *,
    expect: Charge | None,
    actor: Actor | None = None,
) -> Visit:
    """Step 1: the attempt, recorded on the visit before the gateway is called (guarded on the
    charge being as it was read, so two attempts can't start together), audit-logged when an
    admin starts it."""
    field = field_for(purpose)
    charge = Charge(
        status="pending",
        amount_pence=split.price_pence,
        fee_pence=split.fee_pence,
        provider_pence=split.provider_pence,
        gateway=gateway_name,  # type: ignore[arg-type]
        idempotency_key=key,
    )
    guard: dict = (
        {field: None}
        if expect is None
        else {f"{field}.status": expect.status, f"{field}.idempotency_key": expect.idempotency_key}
    )

    async def record(session: DbSession) -> Visit:
        updated = await Visits(db).update(
            visit.id, {field: charge.model_dump(mode="python")}, extra_filter=guard, session=session
        )
        if updated is None:
            fail(
                status.HTTP_409_CONFLICT,
                "charge_in_progress",
                "This payment changed while you were looking at it. Have another look.",
            )
        # When this key was first used: automatic repeats stop before the gateway forgets it.
        await ChargeAttempts(db).insert_once(
            ChargeAttempt(id=key, visit_id=visit.id, purpose=purpose, created_at=utcnow()),
            {"_id": key},
            session=session,
        )
        if actor is not None:
            await audit(
                db,
                actor,
                "payment.charge_retried",
                Related(visit_id=visit.id, booking_id=visit.booking_id, provider_id=visit.provider_id),
                before={"status": expect.status if expect else None, "key": expect.idempotency_key if expect else None},
                after={
                    "status": "pending",
                    "key": key,
                    "amount_pence": split.price_pence,
                    "fee_pence": split.fee_pence,
                },
                session=session,
            )
        return updated

    return await transaction(db, record)


def _visit_ref(visit: Visit, p: notices.Parties) -> VisitRef:
    pay = p.customer.payment if p.customer else None
    return VisitRef(
        visit_id=visit.id,
        booking_id=visit.booking_id,
        customer_id=visit.customer_id,
        gateway_customer_id=(pay.gateway_customer_id if pay else None) or "",
        description=f"{p.category_name}, {wording.day_text(visit.local_date)}, {visit.performer.name}",
    )


async def _attempt(
    db: Db, s: Settings, gateway: PaymentGateway, visit: Visit, purpose: Purpose, split: money.Split, key: str
) -> Visit:
    """Steps 2 and 3 for an attempt already recorded as pending."""
    p = await notices.parties(db, visit)
    result = _cannot_charge(p, gateway, split, key)
    if result is None:
        assert p.provider is not None and p.provider.payment_account is not None
        try:
            result = await gateway.charge_visit(
                _visit_ref(visit, p),
                split.price_pence,
                split.fee_pence,
                p.provider.payment_account.account_id,
                idempotency_key=key,
                purpose=purpose,
            )
        except Exception:
            # Unknown outcome: the attempt stays pending, and the webhook or settle_pending_charges
            # (same key) finds out what happened.
            log.exception("charging visit %s (%s) failed unexpectedly", visit.id, key)
            return await get_visit(db, visit.id)
    return await record_result(db, s, visit.id, purpose, key, result)


async def charge_visit(
    db: Db, s: Settings, gateway: PaymentGateway, visit_id: str, *, purpose: Purpose = "visit"
) -> Visit:
    """Charge a finished visit (or its tip) for the first time and return the visit with its
    charge state. Idempotent: a charge that has succeeded or failed is returned as it is (a
    retry is the admin's), and one left pending is settled the bounded way (settle_unknown)."""
    visit = await get_visit(db, visit_id)
    if purpose == "visit" and visit.status != "finished":
        fail(status.HTTP_409_CONFLICT, "not_finished", "A visit is charged once it's finished.")
    if purpose == "tip" and visit.tip_pence <= 0:
        fail(status.HTTP_409_CONFLICT, "no_tip", "There's no tip to charge on this visit.")
    charge = charge_of(visit, purpose)
    if charge is not None and charge.status in (*SETTLED, *RETRYABLE):
        return visit
    if charge is not None and charge.status == "pending" and charge.idempotency_key:
        return await settle_unknown(db, s, gateway, visit, purpose)  # bounded: never a blind repeat
    split = split_to_charge(visit, purpose, s)
    key = attempt_key(visit.id, purpose)
    visit = await _record_intent(db, visit, purpose, split, gateway.name, key, expect=charge)
    return await _attempt(db, s, gateway, visit, purpose, split, key)


async def settle_unknown(db: Db, s: Settings, gateway: PaymentGateway, visit: Visit, purpose: Purpose) -> Visit:
    """A pending attempt whose outcome we don't know: ask the gateway about its payment (always
    safe), or, if we never heard which payment it made, repeat the call with the same key, which
    can't charge twice, but only while the gateway still remembers the key."""
    charge = charge_of(visit, purpose)
    assert charge is not None and charge.status == "pending" and charge.idempotency_key
    if charge.payment_intent_id:
        result = await gateway.charge_status(charge.payment_intent_id)
        return await record_result(db, s, visit.id, purpose, charge.idempotency_key, result)
    attempt = await ChargeAttempts(db).get(charge.idempotency_key)
    if attempt is None or utcnow() - attempt.created_at >= KEY_LIFE:
        return visit  # too old (or not ours) to repeat safely: the overview shows it for a check by hand
    if utcnow() - attempt.created_at < IN_FLIGHT:
        return visit  # its first request is probably still going: don't race it
    return await _attempt(
        db, s, gateway, visit, purpose, charged_split(visit, charge, purpose, s), charge.idempotency_key
    )


async def retry_charge(db: Db, s: Settings, gateway: PaymentGateway, visit_id: str, actor: Actor) -> Visit:
    """Admin "Retry charge": settle a pending attempt, or start a new attempt after a failed
    one or one waiting for the customer (cancelling that first, so it can't also be paid)."""
    visit = await get_visit(db, visit_id)
    charge = visit.charge
    if charge.status in SETTLED:
        fail(status.HTTP_409_CONFLICT, "already_paid", "This visit has already been paid.")
    if charge.status == "none":
        return await charge_visit(db, s, gateway, visit_id)
    if charge.status == "pending":
        visit = await settle_unknown(db, s, gateway, visit, "visit")
        if visit.charge.status == "pending":
            fail(status.HTTP_409_CONFLICT, "still_processing", "This payment is still being processed. Try again soon.")
        return visit
    if charge.payment_intent_id:
        current = await gateway.cancel_charge(charge.payment_intent_id)
        if current.status == "succeeded":  # the customer confirmed it after all
            return await record_result(db, s, visit.id, "visit", charge.idempotency_key or "", current)
        if current.status == "pending":
            fail(status.HTTP_409_CONFLICT, "still_processing", "This payment is still being processed. Try again soon.")
    split = split_to_charge(visit, "visit", s)
    key = next_attempt_key(visit.id, "visit", charge.idempotency_key)
    visit = await _record_intent(db, visit, "visit", split, gateway.name, key, expect=charge, actor=actor)
    return await _attempt(db, s, gateway, visit, "visit", split, key)
