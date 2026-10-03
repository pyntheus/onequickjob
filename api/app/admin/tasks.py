"""L3 periodic tasks. Register with @periodic from app.core.tasks; main.py imports this module."""

import logging
from datetime import timedelta

from app.adapters.payments import make_payment_gateway
from app.core.config import Settings
from app.core.db import Db
from app.core.tasks import periodic
from app.core.timeutil import utcnow
from app.payments import charging, refunds
from app.repos.payments import PaymentRefunds
from app.repos.visits import Visits
from app.services.audit import SYSTEM

log = logging.getLogger("oqj.payments.tasks")

# Leave the request that started an attempt time to finish it, and stop before Stripe forgets
# the idempotency key (24 hours), after which repeating a call could charge again.
SETTLE_AFTER = timedelta(minutes=5)
SETTLE_UNTIL = timedelta(hours=23)


@periodic("settle_pending_payments", every_seconds=300)
async def settle_pending_payments(db: Db, s: Settings) -> None:
    """Charges and refunds whose outcome we didn't hear (an interrupted call, Stripe unreachable):
    ask again with the same idempotency key, which can't move money twice."""
    gateway = make_payment_gateway(s, db)
    now = utcnow()
    window = {"$lte": now - SETTLE_AFTER, "$gte": now - SETTLE_UNTIL}
    for purpose in ("visit", "tip"):
        field = charging.field_for(purpose)
        for visit in await Visits(db).find({f"{field}.status": "pending", "updated_at": window}, limit=50):
            try:
                await charging.settle_unknown(db, s, gateway, visit, purpose)
            except Exception:
                log.exception("couldn't settle the %s charge of visit %s", purpose, visit.id)
    for intent in await PaymentRefunds(db).find(
        {"status": {"$in": ["pending", "fee_pending"]}, "updated_at": window}, limit=50
    ):
        try:
            await refunds.send_refund(db, s, gateway, intent, SYSTEM)
        except Exception:
            log.exception("couldn't settle refund %s", intent.id)
