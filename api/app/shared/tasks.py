"""Foundation tasks: keep recurring plans materialised and remind before documents expire."""

import logging

from app.core.config import Settings
from app.core.db import Db
from app.core.tasks import periodic
from app.repos.bookings import Bookings
from app.repos.providers import Providers
from app.repos.series import SeriesRepo
from app.services import schedule
from app.services.documents import send_expiry_reminders

log = logging.getLogger("oqj.tasks")


@periodic("series_horizon", every_seconds=3600)
async def top_up_series(db: Db, s: Settings) -> None:
    """Make sure every active plan has visits six weeks ahead. Each plan is isolated, so one
    failure doesn't stop the rest."""
    providers = Providers(db)
    bookings = Bookings(db)
    for series in await SeriesRepo(db).find({"status": "active"}):
        try:
            provider = await providers.get(series.provider_id)
            booking = await bookings.get(series.booking_id)
            if provider is None or booking is None:
                continue
            await schedule.ensure_horizon(db, series, provider, source=booking.source)
        except Exception:
            log.exception("horizon top-up failed for series %s", series.id)


@periodic("document_expiry_reminders", every_seconds=3600)
async def document_expiry(db: Db, s: Settings) -> None:
    """30 days before any verified document expires (insurance, basic DBS...), remind once."""
    try:
        await send_expiry_reminders(db)
    except Exception:
        log.exception("document expiry reminders failed")
