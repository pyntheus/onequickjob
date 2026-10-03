"""Finishing a visit: the calibration data, the charge, the ledger entry and the messages.

Never the charge inside a transaction (CLAUDE.md; decisions.md A7). Three steps:

1. One transaction: the visit becomes finished with the minutes, flags and overrun (the
   calibration data, always kept, whatever happens to the payment), its charge is marked
   pending with the amounts from money.split_for_visit and the per-visit idempotency key, and
   the day's mileage is worked out again.
2. No transaction: PaymentGateway.charge_visit with that key. Only the request that claimed
   the pending charge (charge.attempted_at) calls the gateway.
3. One transaction: the result on the visit (guarded on it still being pending and unsent),
   the ledger entry if it succeeded, a one-off booking completed, and the messages.

If anything stops after step 1, the visit is finished with a pending charge that never reached
the gateway: after a short grace, finishing again or the resume task (app.provider.tasks)
claims it and repeats steps 2 and 3. The idempotency key means a customer is never charged
twice for a visit.
"""

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from fastapi import status

from app.adapters.payments.base import ChargeResult, PaymentGateway, VisitRef
from app.core import money
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail
from app.core.timeutil import to_london, utcnow
from app.models.common import Related
from app.models.providers import Provider
from app.models.users import User
from app.models.visits import Charge, Visit
from app.provider.acting import Acting
from app.provider.records import record_mileage_day
from app.provider.round import acting_filter, still_acting, visit_for
from app.provider.schemas import FinishIn, FinishOut
from app.repos.bookings import Bookings
from app.repos.categories import Categories
from app.repos.customers import Customers
from app.repos.providers import Providers
from app.repos.users import Users
from app.repos.visits import Visits
from app.services import ledger, wording
from app.services.eligibility import limit_status
from app.services.notify import link, notify, recipient_for

log = logging.getLogger("oqj.provider.finish")

RESUME_AFTER = timedelta(minutes=2)  # a charge in flight is left alone this long


def charge_key(visit_id: str) -> str:
    return f"visit:{visit_id}:visit"


def overran(est_mins: int, minutes: int) -> tuple[bool, bool]:
    """(more than 10% over the estimate, more than 25% over), in exact integer maths."""
    return minutes * 10 > est_mins * 11, minutes * 4 > est_mins * 5


async def finish_visit(
    db: Db, s: Settings, gateway: PaymentGateway, a: Acting, visit_id: str, body: FinishIn
) -> FinishOut:
    v = await visit_for(db, a, visit_id)
    if v.status == "finished":
        return await _resume_or_report(db, s, gateway, a, v)
    if v.status != "in_progress":
        fail(status.HTTP_409_CONFLICT, "not_started", "Start the job first, then finish it here.")
    if body.nothing_different and body.flags:
        fail(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "flags_conflict",
            'Choose what was different, or "Nothing, it was as described", not both.',
        )
    over, over_25 = overran(v.est_mins, body.minutes)
    split = money.split_for_visit(v.price_pence, v.source, v.performer.kind, s)
    now = utcnow()
    charge = Charge(
        status="pending",
        amount_pence=split.price_pence,
        fee_pence=split.fee_pence,
        provider_pence=split.provider_pence,
        gateway=gateway.name,
        idempotency_key=charge_key(v.id),
        attempted_at=now,
    )

    async def finish(session: DbSession) -> Visit | None:
        await still_acting(db, s, a, v.category_id, session=session)
        done = await Visits(db).update(
            v.id,
            {
                "status": "finished",
                "finished_at": now,
                "minutes_actual": body.minutes,
                "minutes_from_timer": body.from_timer,
                "flags": [f.strip() for f in body.flags],
                "flags_none": body.nothing_different,
                "overrun": over,
                "over_25": over_25,
                "finish_note": body.note.strip(),
                "charge": charge.model_dump(mode="python"),
            },
            extra_filter={"status": "in_progress", **acting_filter(a)},
            session=session,
        )
        if done is None:
            return None
        if done.performer.kind != "helper":
            await record_mileage_day(db, done.provider_id, to_london(now).date(), session=session)
        return done

    finished = await transaction(db, finish)
    if finished is None:  # finished by another request just now (a double tap), or taken away
        current = await Visits(db).find_one({"_id": v.id, **acting_filter(a)})
        if current is None or current.status != "finished":
            fail(status.HTTP_409_CONFLICT, "visit_changed", "That visit has just changed. Have another look.")
        return await _resume_or_report(db, s, gateway, a, current)
    return await charge_and_record(db, s, gateway, finished, a)


async def _resume_or_report(db: Db, s: Settings, gateway: PaymentGateway, a: Acting, v: Visit) -> FinishOut:
    """Finishing an already-finished visit: report it, or resume a charge that never reached the
    gateway (claimed, so only one request ever sends it)."""
    if v.charge.status == "pending" and not v.charge.payment_intent_id:
        claimed = await claim_charge(db, v)
        if claimed is not None:
            return await charge_and_record(db, s, gateway, claimed, a)
    return await finish_out(db, s, gateway, v, a)


async def claim_charge(db: Db, v: Visit, now: datetime | None = None) -> Visit | None:
    now = now or utcnow()
    return await Visits(db).update(
        v.id,
        {"charge.attempted_at": now},
        extra_filter={
            "status": "finished",
            "charge.status": "pending",
            "charge.payment_intent_id": None,
            "$or": [{"charge.attempted_at": None}, {"charge.attempted_at": {"$lt": now - RESUME_AFTER}}],
        },
    )


def _description(cat_name: str, v: Visit) -> str:
    return f"{cat_name}, {wording.day_text(v.local_date)}, {v.performer.name}"


async def charge_and_record(
    db: Db, s: Settings, gateway: PaymentGateway, v: Visit, a: Acting | None = None
) -> FinishOut:
    """Steps 2 and 3, for a finished visit whose pending charge this request has claimed."""
    provider = await Providers(db).get(v.provider_id)
    customer = await Customers(db).get(v.customer_id)
    cat = await Categories(db).get(v.category_id)
    assert provider is not None and customer is not None and cat is not None
    account = provider.payment_account.account_id if provider.payment_account else None
    card = customer.payment.gateway_customer_id if customer.payment else None
    key = v.charge.idempotency_key or charge_key(v.id)

    if account is None or card is None:
        reason = "No saved card for this customer." if card is None else "The provider has no payout account yet."
        result = ChargeResult(
            status="failed",
            amount_pence=v.charge.amount_pence,
            fee_pence=v.charge.fee_pence,
            idempotency_key=key,
            failure_reason=reason,
            created_at=utcnow(),
        )
    else:
        try:
            result = await gateway.charge_visit(
                VisitRef(
                    visit_id=v.id,
                    booking_id=v.booking_id,
                    customer_id=v.customer_id,
                    gateway_customer_id=card,
                    description=_description(cat.name, v),
                ),
                v.charge.amount_pence,
                v.charge.fee_pence,
                account,
                idempotency_key=key,
                purpose="visit",
            )
        except Exception:  # the gateway is outside us: leave it pending for the resume task
            log.exception("charging visit %s failed; it stays pending and will be retried", v.id)
            return await finish_out(db, s, gateway, v, a)

    async def record(session: DbSession) -> Visit:
        updated = await Visits(db).update(
            v.id,
            {
                "charge.status": result.status,
                "charge.charge_id": result.charge_id,
                "charge.payment_intent_id": result.payment_intent_id,
                "charge.charged_at": result.created_at if result.status == "succeeded" else None,
                "charge.failure_reason": result.failure_reason,
            },
            extra_filter={"charge.status": "pending", "charge.payment_intent_id": None},
            session=session,
        )
        if updated is None:  # already recorded (or a webhook got there first)
            current = await Visits(db).get(v.id, session=session)
            assert current is not None
            return current
        await _after_charge(db, s, updated, result, session=session)
        return updated

    recorded = await transaction(db, record)
    return await finish_out(db, s, gateway, recorded, a)


async def _after_charge(db: Db, s: Settings, v: Visit, result: ChargeResult, *, session: DbSession) -> None:
    """Inside step 3's transaction: the ledger entry, the booking and the messages."""
    provider = await Providers(db).get(v.provider_id, session=session)
    customer = await Customers(db).get(v.customer_id, session=session)
    cat = await Categories(db).get(v.category_id, session=session)
    booking = await Bookings(db).get(v.booking_id, session=session)
    assert provider is not None and customer is not None and cat is not None and booking is not None
    users = Users(db)
    cu = await users.get(customer.user_id, session=session)
    pu = await users.get(provider.user_id, session=session)
    category = wording.lower_name(cat)
    # The day the work was done (a visit can be finished on another day than it was booked for).
    day = wording.day_text(to_london(v.finished_at).date() if v.finished_at else v.local_date)
    price = wording.money(v.charge.amount_pence)
    customer_first = wording.first_name(customer.name) or "Your customer"
    related = Related(visit_id=v.id, booking_id=v.booking_id, customer_id=v.customer_id, provider_id=v.provider_id)

    if result.status == "succeeded":
        # The ledger records exactly what was charged: the amounts money.split_for_visit gave in
        # step 1, sent to the gateway with this visit's key.
        split = replace(
            money.split_for_visit(v.price_pence, v.source, v.performer.kind, s),
            price_pence=v.charge.amount_pence,
            fee_pence=v.charge.fee_pence,
            provider_pence=v.charge.provider_pence,
        )
        await ledger.record_charge(
            db,
            v,
            split,
            at=result.created_at,
            gateway=v.charge.gateway or "fake",
            charge_id=result.charge_id,
            session=session,
        )
        if not booking.recurring:
            await Bookings(db).update(
                booking.id, {"status": "completed"}, extra_filter={"status": "active"}, session=session
            )
        if cu and cu.phone:
            photo = bool(v.photos.after)
            await notify(
                db,
                "visit_done_customer" if photo else "visit_done_customer_no_photo",
                to=recipient_for(cu),
                data={
                    "provider": v.performer.name,
                    "category": category,
                    "price": price,
                    "link": link(f"/account/visits/{v.id}/rate", s),
                },
                related=related,
                idempotency_key=f"visit:{v.id}:done",
                settings=s,
                session=session,
            )
        if cu and cu.email:
            last4 = customer.payment.card.last4 if customer.payment and customer.payment.card else "••••"
            await notify(
                db,
                "receipt",
                to=recipient_for(cu),
                channel="email",
                data={
                    "category": cat.name,
                    "date": day,
                    "provider": await _performer_full_name(db, v, session=session),
                    "price": price,
                    "fee": wording.money(v.charge.fee_pence),
                    "provider_first": wording.first_name(provider.name),
                    "net": wording.money(v.charge.provider_pence),
                    "last4": last4,
                },
                related=related,
                idempotency_key=f"visit:{v.id}:receipt",
                settings=s,
                session=session,
            )
        if pu and pu.phone:
            await notify(
                db,
                "payment_on_its_way",
                to=recipient_for(pu),
                data={
                    "customer": customer_first,
                    "price": price,
                    "category": category,
                    "net": wording.money(v.charge.provider_pence),
                },
                related=related,
                idempotency_key=f"visit:{v.id}:payment_on_its_way",
                settings=s,
                session=session,
            )
            await _limit_reached(db, s, provider, pu, v.charge.provider_pence, session=session)
    elif result.status in ("failed", "requires_action"):
        if cu and cu.phone:
            await notify(
                db,
                "charge_failed_customer",
                to=recipient_for(cu),
                data={"price": price, "category": category, "date": day, "link": link("/account", s)},
                related=related,
                idempotency_key=f"visit:{v.id}:charge_failed_customer",
                settings=s,
                session=session,
            )
        if pu and pu.phone:
            await notify(
                db,
                "charge_failed_provider",
                to=recipient_for(pu),
                data={"customer": customer_first, "category": category, "date": day},
                related=related,
                idempotency_key=f"visit:{v.id}:charge_failed_provider",
                settings=s,
                session=session,
            )


async def _performer_full_name(db: Db, v: Visit, *, session: DbSession) -> str:
    """Dave Hughes, for the receipt (the short form ends in a full stop: "Dave H.")."""
    if v.performer.kind == "helper":
        user = await Users(db).get(v.performer.user_id, session=session)
        return user.name if user else v.performer.name
    p = await Providers(db).get(v.performer.provider_id, session=session)
    return p.name if p else v.performer.name


async def _limit_reached(
    db: Db, s: Settings, provider: Provider, user: User, just_earned: int, *, session: DbSession
) -> None:
    """The text when this payment takes the provider to their limit (once per period)."""
    lim = await limit_status(db, provider, session=session)
    if not (lim.on and lim.reached) or lim.earned_pence - just_earned >= lim.amount_pence:
        return
    await notify(
        db,
        "limit_reached",
        to=recipient_for(user),
        data={
            "period_word": "weekly" if lim.period == "week" else "monthly",
            "amount": wording.money(lim.amount_pence),
            "resume": wording.day_text(lim.resumes_on),
        },
        related=Related(provider_id=provider.id),
        idempotency_key=f"limit:{provider.id}:{lim.period}:{lim.period_start}:{lim.amount_pence}",
        settings=s,
        session=session,
    )


CHARGE_MESSAGES = {
    "succeeded": "It'll reach {bank} bank with the next payout.",
    "pending": "We're taking the payment now, and we'll text {who} when it's through.",
    "requires_action": "{customer}'s bank wants them to confirm the payment. We've texted them, and {paid} "
    "paid once they do.",
    "failed": "{customer}'s card didn't go through. We're sorting it out with them, and {paid} paid once it does.",
}


async def finish_out(db: Db, s: Settings, gateway: PaymentGateway, v: Visit, a: Acting | None) -> FinishOut:
    customer = await Customers(db).get(v.customer_id)
    provider = await Providers(db).get(v.provider_id)
    first = wording.first_name(customer.name) if customer else "The customer"
    helper = a is not None and a.helper
    boss = wording.first_name(provider.name) if provider else "your provider"
    charge_status = (
        v.charge.status if v.charge.status in ("succeeded", "pending", "requires_action", "failed") else "pending"
    )
    payout = None
    if charge_status == "succeeded" and provider and provider.payment_account:
        try:
            payout = (await gateway.payout_summary(provider.payment_account.account_id, limit=1)).next_payout_date
        except Exception:
            payout = None
    msg = CHARGE_MESSAGES[charge_status].format(
        bank=f"{boss}'s" if helper else "your",
        who=boss if helper else "you",
        customer=first,
        paid=f"{boss} will be" if helper else "you'll be",
    )
    return FinishOut(
        visit_id=v.id,
        minutes_actual=v.minutes_actual or 0,
        est_mins=v.est_mins,
        overrun=bool(v.overrun),
        charge_status=charge_status,  # type: ignore[arg-type]
        price_pence=v.charge.amount_pence,
        fee_pence=v.charge.fee_pence,
        provider_pence=v.charge.provider_pence,
        payout_date=payout,
        charge_message=msg,
        customer_first=first,
    )


async def resume_pending_charges(db: Db, s: Settings, gateway: PaymentGateway) -> int:
    """For the resume task: finished visits whose charge never reached the gateway."""
    cutoff = utcnow() - RESUME_AFTER
    resumed = 0
    for v in await Visits(db).find(
        {
            "status": "finished",
            "charge.status": "pending",
            "charge.payment_intent_id": None,
            "finished_at": {"$lt": cutoff},
        }
    ):
        claimed = await claim_charge(db, v)
        if claimed is not None:
            await charge_and_record(db, s, gateway, claimed)
            resumed += 1
    return resumed
