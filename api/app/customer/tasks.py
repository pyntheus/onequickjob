"""L1 periodic tasks. Register with @periodic from app.core.tasks (imported by main.py)."""

import logging

from app.core.config import Settings
from app.core.db import Db
from app.core.tasks import periodic
from app.customer import templates as _templates  # noqa: F401 (registers L1's outbox templates)
from app.customer.requests import expire_stale

log = logging.getLogger("oqj.tasks")


@periodic("request_expiry", every_seconds=3600)
async def expire_requests(db: Db, s: Settings) -> None:
    """Open requests nobody booked in 7 days close (state-machines.md: open -> expired)."""
    n = await expire_stale(db, s)
    if n:
        log.info("expired %d open requests", n)
