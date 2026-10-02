"""Foundation tasks: keep recurring plans materialised and finish interrupted bookings."""

import logging
from datetime import timedelta

from fastapi import HTTPException

from app.core.config import Settings
from app.core.db import Db
from app.core.tasks import periodic
from app.core.timeutil import utcnow
from app.repos.bookings import Bookings
from app.repos.job_requests import JobRequests
from app.repos.offers import Offers
from app.repos.providers import Providers
from app.repos.series import SeriesRepo
from app.repos.visits import Visits
from app.services import schedule
from app.services.documents import send_expiry_reminders
from app.services.marketplace import complete_claimed, finish_counter_acceptance

log = logging.getLogger("oqj.tasks")


@periodic("series_horizon", every_seconds=3600)
async def top_up_series(db: Db, s: Settings) -> None:
    """Make sure every active plan has visits six weeks ahead. Plans whose booking setup isn't
    complete are left to the repair task: only finish_setup creates a plan's first visit."""
    providers = Providers(db)
    bookings = Bookings(db)
    for series in await SeriesRepo(db).find({"status": "active"}):
        try:
            provider = await providers.get(series.provider_id)
            booking = await bookings.get(series.booking_id)
            if provider is None or booking is None or not booking.setup_complete:
                continue
            await schedule.ensure_horizon(db, series, provider, source=booking.source)
        except Exception:
            log.exception("horizon top-up failed for series %s", series.id)


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
            done = visit is None or (visit.cover.state == "covered" and visit.cover.confirmations_sent_at is not None)
        else:
            booking = await bookings.by_request(req.id)
            done = booking is not None and booking.setup_complete and booking.confirmations_sent_at is not None
        if not done:
            try:
                await complete_claimed(db, s, req)
            except Exception:
                log.exception("repairing request %s failed", req.ref)


@periodic("repair_counter_acceptances", every_seconds=300)
async def repair_acceptances(db: Db, s: Settings) -> None:
    """Finish counter acceptances interrupted between reserving the offer and claiming the
    request (offers left "accepting" for over two minutes)."""
    stale = utcnow() - timedelta(minutes=2)
    for offer in await Offers(db).find({"status": "accepting", "accepting_at": {"$lt": stale}}):
        try:
            await finish_counter_acceptance(db, s, offer)
        except HTTPException:
            pass  # lapsed: someone else booked the request first
        except Exception:
            log.exception("finishing the acceptance of offer %s failed", offer.id)


@periodic("document_expiry_reminders", every_seconds=3600)
async def document_expiry(db: Db, s: Settings) -> None:
    """30 days before any verified document expires (insurance, basic DBS...), remind once."""
    try:
        await send_expiry_reminders(db)
    except Exception:
        log.exception("document expiry reminders failed")
