"""L1 periodic tasks. Register with @periodic from app.core.tasks (imported by main.py)."""

import logging

from app.adapters.payments import make_payment_gateway
from app.core.config import Settings
from app.core.db import Db
from app.core.tasks import periodic
from app.customer import templates as _templates  # noqa: F401 (registers L1's outbox templates)
from app.customer.account import reconcile_tips as settle_pending_tips
from app.customer.requests import expire_stale

log = logging.getLogger("oqj.tasks")


@periodic("request_expiry", every_seconds=3600)
async def expire_requests(db: Db, s: Settings) -> None:
    """Open requests nobody booked in 7 days close (state-machines.md: open -> expired)."""
    n = await expire_stale(db, s)
    if n:
        log.info("expired %d open requests", n)


@periodic("tip_reconcile", every_seconds=600)
async def reconcile_tips(db: Db, s: Settings) -> None:
    """Tips left pending by a crash or a gateway error between rating and charging: settle them
    with the same idempotency key, so a charge that went through is recorded, never repeated."""
    n = await settle_pending_tips(db, s, make_payment_gateway(s, db))
    if n:
        log.info("settled %d pending tips", n)
