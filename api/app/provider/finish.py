"""Finishing a visit: the calibration data, then the charge through app.payments.charging.

Never the charge inside a transaction (CLAUDE.md; decisions.md A7). Two steps:

1. One transaction: the visit becomes finished with the minutes, flags and overrun (the
   calibration data, always kept, whatever happens to the payment), and the day's mileage is
   worked out again.
2. app.payments.charging.charge_visit (L3), the one charging path: the intent with the amounts
   from money.split_for_visit and the per-visit idempotency key, the gateway call, then the
   result with its ledger entry, the messages and a one-off booking completed, in one
   transaction. Webhooks, the admin's retry and the settle task finish what it starts.

If the request stops between the two, the visit is finished with a charge that never started:
finishing again starts it, and so does L3's settle task (charging.start_unstarted) after a few
minutes. charge_visit is idempotent, so a customer is never charged twice for a visit.
"""

import logging

from fastapi import HTTPException, status

from app.adapters.payments.base import PaymentGateway
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail
from app.core.timeutil import to_london, utcnow
from app.models.visits import Visit
from app.payments import charging
from app.provider.acting import Acting
from app.provider.records import record_mileage_day
from app.provider.round import acting_filter, still_acting, visit_for
from app.provider.schemas import FinishIn, FinishOut
from app.repos.customers import Customers
from app.repos.providers import Providers
from app.repos.visits import Visits
from app.services import wording

log = logging.getLogger("oqj.provider.finish")


def overran(est_mins: int, minutes: int) -> tuple[bool, bool]:
    """(more than 10% over the estimate, more than 25% over), in exact integer maths."""
    return minutes * 10 > est_mins * 11, minutes * 4 > est_mins * 5


async def finish_visit(
    db: Db, s: Settings, gateway: PaymentGateway, a: Acting, visit_id: str, body: FinishIn
) -> FinishOut:
    v = await visit_for(db, a, visit_id)
    if v.status == "finished":
        return await charge(db, s, gateway, a, v)
    if v.status != "in_progress":
        fail(status.HTTP_409_CONFLICT, "not_started", "Start the job first, then finish it here.")
    if body.nothing_different and body.flags:
        fail(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "flags_conflict",
            'Choose what was different, or "Nothing, it was as described", not both.',
        )
    over, over_25 = overran(v.est_mins, body.minutes)
    now = utcnow()

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
        finished = current
    return await charge(db, s, gateway, a, finished)


async def charge(db: Db, s: Settings, gateway: PaymentGateway, a: Acting, v: Visit) -> FinishOut:
    """Step 2, also for a visit finished already (a double tap, or finishing again after a
    request that stopped): charge_visit returns a charge that's settled as it is and never
    repeats one that's under way, so this only reports it then."""
    try:
        v = await charging.charge_visit(db, s, gateway, v.id)
    except HTTPException as e:
        if e.status_code != status.HTTP_409_CONFLICT:  # 409: another request started it just now
            raise
        v = await charging.get_visit(db, v.id)
    except Exception:  # the visit is saved as finished: the settle task starts or settles its charge
        log.exception("charging visit %s failed; the settle task will carry it on", v.id)
        v = await charging.get_visit(db, v.id)
    return await finish_out(db, s, gateway, v, a)


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
    # A charge that hasn't started yet shows what it will be (money.split_for_visit).
    amounts = (
        charging.split_to_charge(v, "visit", s)
        if v.charge.status == "none"
        else charging.charged_split(v, v.charge, "visit", s)
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
        price_pence=amounts.price_pence,
        fee_pence=amounts.fee_pence,
        provider_pence=amounts.provider_pence,
        payout_date=payout,
        charge_message=msg,
        customer_first=first,
    )
