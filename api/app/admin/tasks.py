"""L3 periodic tasks. Register with @periodic from app.core.tasks; main.py imports this module."""

import logging
from datetime import timedelta

from app.adapters.payments import make_payment_gateway
from app.core.config import Settings
from app.core.db import Db
from app.core.tasks import periodic
from app.core.timeutil import utcnow
from app.payments import charging, refunds
from app.repos.visits import Visits

log = logging.getLogger("oqj.payments.tasks")

# Leave the request that started a payment time to finish it. Repeats that could move money
# stop before Stripe forgets the idempotency key (24 hours), counted from when each attempt or
# refund first began (immutable), never from the record's last update.
SETTLE_AFTER = timedelta(minutes=5)
LOOK_BACK = timedelta(days=7)


@periodic("settle_pending_payments", every_seconds=300)
async def settle_pending_payments(db: Db, s: Settings) -> None:
    """Charges and refunds whose outcome we didn't hear (an interrupted call, Stripe unreachable,
    a refund still processing, our fee still to return): ask again, safely."""
    gateway = make_payment_gateway(s, db)
    now = utcnow()
    for purpose in ("visit", "tip"):
        field = charging.field_for(purpose)
        for visit in await Visits(db).find(
            {f"{field}.status": "pending", "updated_at": {"$lte": now - SETTLE_AFTER, "$gte": now - LOOK_BACK}},
            limit=50,
        ):
            try:
                # Reading a payment's state is always safe; repeating the call only within the key's life.
                await charging.settle_unknown(db, s, gateway, visit, purpose)
            except Exception:
                log.exception("couldn't settle the %s charge of visit %s", purpose, visit.id)
    await refunds.settle_open_refunds(db, s, gateway, older_than=SETTLE_AFTER)
