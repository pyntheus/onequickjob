"""Foundation tasks: keep recurring plans materialised and finish interrupted bookings."""

from datetime import timedelta

from app.core.config import Settings
from app.core.db import Db
from app.core.tasks import periodic
from app.core.timeutil import utcnow
from app.repos.bookings import Bookings
from app.repos.job_requests import JobRequests
from app.repos.providers import Providers
from app.repos.series import SeriesRepo
from app.repos.visits import Visits
from app.services import schedule
from app.services.marketplace import complete_claimed


@periodic("series_horizon", every_seconds=3600)
async def top_up_series(db: Db, s: Settings) -> None:
    """Make sure every active plan has visits six weeks ahead."""
    providers = Providers(db)
    bookings = Bookings(db)
    for series in await SeriesRepo(db).find({"status": "active"}):
        provider = await providers.get(series.provider_id)
        booking = await bookings.get(series.booking_id)
        if provider is None or booking is None:
            continue
        await schedule.ensure_horizon(db, series, provider, source=booking.source)


@periodic("repair_claimed_requests", every_seconds=300)
async def repair_claimed(db: Db, s: Settings) -> None:
    """A request claimed in the last day whose booking setup (booking, plan, first visit,
    thread, messages) or cover reassignment was interrupted is resumed. complete_claimed is
    idempotent: each step checks before it writes."""
    bookings, visits = Bookings(db), Visits(db)
    now = utcnow()
    # Leave fresh claims alone for two minutes: the request that won them is still finishing.
    window = {"$gt": now - timedelta(days=1), "$lt": now - timedelta(minutes=2)}
    for req in await JobRequests(db).find({"status": "booked", "booked.at": window}):
        if req.cover_for_visit_id:
            visit = await visits.get(req.cover_for_visit_id)
            done = visit is None or visit.cover.state == "covered"
        else:
            booking = await bookings.by_request(req.id)
            done = booking is not None and booking.setup_complete and booking.confirmations_sent_at is not None
        if not done:
            await complete_claimed(db, s, req)
