"""L1 periodic tasks. Register with @periodic from app.core.tasks (imported by main.py)."""

import logging

from app.adapters.payments import make_payment_gateway
from app.core.config import Settings
from app.core.db import Db
from app.core.tasks import periodic
from app.customer import templates as _templates  # noqa: F401 (registers L1's outbox templates)
from app.customer.account import start_orphaned_tips as start_tips
from app.customer.plan_changes import lapse_stale
from app.customer.requests import expire_stale

log = logging.getLogger("oqj.tasks")


@periodic("request_expiry", every_seconds=3600)
async def expire_requests(db: Db, s: Settings) -> None:
    """Open requests nobody booked in 7 days close (state-machines.md: open -> expired)."""
    n = await expire_stale(db, s)
    if n:
        log.info("expired %d open requests", n)


@periodic("plan_change_expiry", every_seconds=900)
async def lapse_plan_changes(db: Db, s: Settings) -> None:
    """A change of frequency the provider hasn't answered in 48 hours lapses; the customer is told (A10)."""
    n = await lapse_stale(db, s)
    if n:
        log.info("lapsed %d plan changes", n)


@periodic("orphaned_tips", every_seconds=300)
async def start_orphaned_tips(db: Db, s: Settings) -> None:
    """A rating saved without its tip's charge starting (an interrupted request): start it through
    app.payments.charging. L3's settle task then covers it like any other pending tip."""
    n = await start_tips(db, s, make_payment_gateway(s, db))
    if n:
        log.info("started %d orphaned tips", n)
