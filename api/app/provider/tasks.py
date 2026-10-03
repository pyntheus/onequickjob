"""L2 periodic tasks (visit reminders, document expiry, tax key dates). Register with
@periodic from app.core.tasks; main.py imports this module.

Every task is idempotent (outbox idempotency keys, guarded updates): it may run more than once
and late (after a restart) without sending anything twice. Document expiry reminders are F's
task (app.shared.tasks).
"""

import logging
from datetime import date, datetime, timedelta

from app.adapters.payments import make_payment_gateway
from app.core.config import Settings
from app.core.db import Db
from app.core.tasks import periodic
from app.core.timeutil import add_months, london_today, tax_year, tax_year_bounds, to_london, utcnow
from app.models.common import Related
from app.provider import templates as _templates  # noqa: F401 (registers L2's extra outbox templates)
from app.provider.cover import expire_uncovered
from app.provider.finish import resume_pending_charges
from app.provider.own_customers import expire_invites
from app.provider.time_off import housekeeping
from app.repos.bookings import Bookings
from app.repos.categories import Categories
from app.repos.customers import Customers
from app.repos.ledger_entries import LedgerEntries
from app.repos.providers import Providers
from app.repos.users import Users
from app.repos.visits import Visits
from app.services import wording
from app.services.notify import link, notify, recipient_for

log = logging.getLogger("oqj.tasks.provider")

REMINDER_HOUR = 18  # 6pm the day before
DOING = {
    "mowing": "mowing",
    "hedges": "trimming a hedge",
    "clearance": "clearing a garden",
    "jetwash": "jet washing",
    "gutters": "clearing gutters",
    "windows": "cleaning windows",
    "cleaning": "cleaning",
    "deepclean": "doing a deep clean",
    "oven": "cleaning an oven",
    "decorating": "decorating",
    "flatpack": "putting flat-pack together",
    "mounting": "putting things up",
    "repairs": "doing small repairs",
    "techhelp": "doing tech help",
    "dogwalking": "dog walking",
}


def evening(now: datetime) -> bool:
    return to_london(now).hour >= REMINDER_HOUR


async def send_visit_reminders(db: Db, s: Settings, now: datetime | None = None) -> int:
    """From 6pm, tomorrow's visits: the customer of each, and whoever does the first visit of the
    day (the provider, or their helper) once."""
    now = now or utcnow()
    if not evening(now):
        return 0
    tomorrow = to_london(now).date() + timedelta(days=1)
    visits = await Visits(db).find(
        {"local_date": tomorrow.isoformat(), "status": "scheduled"}, sort=[("scheduled_start", 1)]
    )
    cats = {c.id: c for c in await Categories(db).all()}
    users = Users(db)
    sent = 0
    first_for: set[str] = set()
    for v in visits:
        cat = cats.get(v.category_id)
        booking = await Bookings(db).get(v.booking_id)
        if cat is None or booking is None:
            continue
        customer = await Customers(db).get(v.customer_id)
        cu = await users.get(customer.user_id) if customer else None
        related = Related(visit_id=v.id, booking_id=v.booking_id, customer_id=v.customer_id)
        if cu and cu.phone:
            await notify(
                db,
                "visit_reminder_customer",
                to=recipient_for(cu),
                data={
                    "provider": v.performer.name,
                    "when_text": f"tomorrow at {wording.time_text(v.scheduled_start)}",
                    "category": wording.lower_name(cat),
                    "link": link("/account", s),
                },
                related=related,
                idempotency_key=f"visit:{v.id}:reminder:{v.local_date}",
                settings=s,
            )
            sent += 1
        if v.performer.user_id in first_for:
            continue
        first_for.add(v.performer.user_id)
        pu = await users.get(v.performer.user_id)
        if pu and pu.phone:
            await notify(
                db,
                "visit_reminder_provider",
                to=recipient_for(pu),
                data={
                    "doing": DOING.get(cat.id, f"doing {wording.lower_name(cat)}"),
                    "area": booking.address.area,
                    "day": f"{tomorrow:%A}",
                    "time": wording.time_text(v.scheduled_start),
                },
                related=related.model_copy(update={"provider_id": v.performer.provider_id}),
                idempotency_key=f"round:{v.performer.user_id}:{tomorrow}:reminder",
                settings=s,
            )
            sent += 1
    return sent


async def give_up_on_cover(db: Db, s: Settings, now: datetime | None = None) -> int:
    """Nobody took a cover by 6pm the day before: skip it and tell everyone (app.provider.cover)."""
    now = now or utcnow()
    today = to_london(now).date()
    return await expire_uncovered(db, s, today if evening(now) else today - timedelta(days=1))


TAX_DATES = (
    ("register", 10, 5, "register for Self Assessment, if this is your first year working for yourself,"),
    ("return", 1, 31, "send your tax return and pay any tax due"),
)


async def send_tax_key_dates(db: Db, s: Settings, today: date | None = None) -> int:
    """A month before 5 October and 31 January, to providers with takings in the tax year it's
    about (the registration reminder only to those whose first takings were in it)."""
    today = today or london_today()
    sent = 0
    for key, month, day, what in TAX_DATES:
        due = date(today.year, month, day)
        if due < today:  # the next one: in December, 31 January is next year's
            due = date(today.year + 1, month, day)
        if today < add_months(due, -1):  # from a month before
            continue
        year = tax_year(date(due.year if month >= 4 else due.year - 1, 4, 5))
        first, _ = tax_year_bounds(year)
        for p in await Providers(db).find({"status": {"$in": ["active", "payouts_paused", "suspended"]}}):
            entries = LedgerEntries(db)
            if not await entries.count({"provider_id": p.id, "tax_year": year}):
                continue
            if key == "register" and await entries.count(
                {"provider_id": p.id, "local_date": {"$lt": first.isoformat()}}
            ):
                continue
            user = await Users(db).get(p.user_id)
            if user is None or not user.phone:
                continue
            await notify(
                db,
                "tax_key_date",
                to=recipient_for(user),
                data={"what": what, "date": f"{due.day} {due:%B}", "link": link("/p/tax", s)},
                related=Related(provider_id=p.id),
                idempotency_key=f"tax:{p.id}:{key}:{due}",
                settings=s,
            )
            sent += 1
    return sent


@periodic("provider_visit_reminders", every_seconds=900)
async def visit_reminders(db: Db, s: Settings) -> None:
    await send_visit_reminders(db, s)


@periodic("provider_cover_deadline", every_seconds=900)
async def cover_deadline(db: Db, s: Settings) -> None:
    await give_up_on_cover(db, s)


@periodic("provider_time_off", every_seconds=3600)
async def time_off(db: Db, s: Settings) -> None:
    await housekeeping(db, s)


@periodic("provider_invite_expiry", every_seconds=3600)
async def invite_expiry(db: Db, s: Settings) -> None:
    await expire_invites(db)


@periodic("provider_tax_key_dates", every_seconds=3600)
async def tax_key_dates(db: Db, s: Settings) -> None:
    await send_tax_key_dates(db, s)


@periodic("provider_resume_charges", every_seconds=300)
async def resume_charges(db: Db, s: Settings) -> None:
    """Visits finished whose charge never reached the gateway (a crash in between)."""
    await resume_pending_charges(db, s, make_payment_gateway(s, db))
