"""The day's round and the on-the-job card: start the timer, add photos, send a helper.

A provider sees the visits they're booked for (including ones they've sent a helper to); a
helper sees only the visits they've been sent to. Finishing a visit is app.provider.finish.
"""

from datetime import date, timedelta
from typing import Any

from fastapi import status

from app.core import money
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.core.timeutil import london_today, utcnow
from app.models.bookings import Booking
from app.models.common import Related
from app.models.users import User
from app.models.visits import Performer, Visit
from app.provider.acting import Acting
from app.provider.common import categories, miles, one_dp, own_file, short_name, summary_for
from app.provider.helpers import doc_labels, helper_out, ready_helper
from app.provider.schemas import PhotoIn, ProviderVisit, RoundItem, TodayRound
from app.repos.bookings import Bookings
from app.repos.customers import Customers
from app.repos.files import Files
from app.repos.providers import Providers
from app.repos.series import SeriesRepo
from app.repos.users import Users
from app.repos.visits import Visits
from app.services import schedule, wording
from app.services.notify import notify, recipient_for

MAX_PHOTOS = 6
UPCOMING_DAYS = 21


def _mine(a: Acting) -> dict[str, Any]:
    """The visits this person works: a helper's are the ones sent to them."""
    if a.helper:
        return {"performer.kind": "helper", "performer.user_id": a.user_id}
    return {"provider_id": a.provider.id}


async def visit_for(db: Db, a: Acting, visit_id: str) -> Visit:
    v = await Visits(db).get(visit_id)
    if v is None:
        not_found("That visit")
    if a.helper:
        allowed = v.performer.kind == "helper" and v.performer.user_id == a.user_id
    else:
        allowed = v.provider_id == a.provider.id
    if not allowed:
        not_found("That visit")
    return v


def acting_filter(a: Acting) -> dict[str, Any]:
    """Who may change a visit, as a guard on its update: the provider it's booked to, or the
    helper it's been sent to (an owner reassigning it meanwhile makes the guard fail)."""
    if a.helper:
        return {"provider_id": a.provider.id, "performer.kind": "helper", "performer.user_id": a.user_id}
    return {"provider_id": a.provider.id}


async def still_acting(db: Db, s: Settings, a: Acting, category_id: str, *, session: DbSession) -> None:
    """Inside a transaction: the person can still act on a visit of this category. It writes the
    provider first, so a concurrent change to their helpers or documents conflicts with this
    transaction and its re-run sees it; a helper must still be on the list, ready and documented."""
    provider = await Providers(db).update(a.provider.id, {}, session=session)
    if provider is None:
        not_found("That visit")
    if a.helper:
        cat = (await categories(db, session=session))[category_id]
        ready_helper(provider, a.user_id, cat, demo=s.demo_mode)


def _performs(a: Acting, v: Visit) -> bool:
    """Does the person using the app do this visit themself?"""
    return v.performer.user_id == a.user_id if a.helper else v.performer.kind != "helper"


async def _bookings(db: Db, visits: list[Visit]) -> dict[str, Booking]:
    ids = list({v.booking_id for v in visits})
    return {b.id: b for b in await Bookings(db).find({"_id": {"$in": ids}})} if ids else {}


async def _customer_names(db: Db, visits: list[Visit]) -> dict[str, str]:
    ids = list({v.customer_id for v in visits})
    return {c.id: c.name for c in await Customers(db).find({"_id": {"$in": ids}})} if ids else {}


async def _cover_ok(db: Db, visits: list[Visit]) -> dict[str, bool]:
    ids = list({v.series_id for v in visits if v.series_id})
    plans = {p.id: p.cover_when_away for p in await SeriesRepo(db).find({"_id": {"$in": ids}})} if ids else {}
    return {v.id: plans.get(v.series_id, True) if v.series_id else True for v in visits}


async def today_round(db: Db, a: Acting, day: date | None = None) -> TodayRound:
    today = london_today()
    day = day or today
    visits = await Visits(db).find(
        {**_mine(a), "local_date": day.isoformat(), "status": {"$ne": "cancelled"}}, sort=[("scheduled_start", 1)]
    )
    bookings = await _bookings(db, visits)
    names = await _customer_names(db, visits)
    cover_ok = await _cover_ok(db, visits)
    cats = await categories(db)
    home = a.provider.home.location
    here: tuple[float, float] = (home.lat, home.lng)
    now_id = next((v.id for v in visits if v.status == "in_progress" and _performs(a, v)), None) or next(
        (v.id for v in visits if v.status == "scheduled" and _performs(a, v)), None
    )
    items: list[RoundItem] = []
    for v in visits:
        b = bookings.get(v.booking_id)
        cat = cats[v.category_id]
        gap = None
        if b is not None and _performs(a, v) and v.status != "skipped":
            gap = one_dp(miles(b.address, *here))
            here = (b.address.lat, b.address.lng)
        items.append(
            RoundItem(
                visit_id=v.id,
                start_time=wording.time_text(v.scheduled_start),
                status=v.status,
                is_now=v.id == now_id,
                category_name=cat.name,
                address_line=f"{b.address.line1}, {b.address.area}" if b else "",
                area=b.address.area if b else "",
                customer_name=short_name(names.get(v.customer_id, "")),
                est_mins=v.est_mins,
                minutes_actual=v.minutes_actual,
                summary=summary_for(cat, b.answers) if b else "",
                note=b.notes if b else "",
                miles_from_previous=gap,
                performer=v.performer.kind,
                category_id=cat.id,
                performer_name=v.performer.name,
                cover_state=v.cover.state,
                cover_allowed=cover_ok[v.id],
                charge_status=v.charge.status,
                is_first=v.is_first,
            )
        )
    later = await Visits(db).find(
        {
            **_mine(a),
            "status": "scheduled",
            "local_date": {"$gt": today.isoformat(), "$lte": (today + timedelta(days=UPCOMING_DAYS)).isoformat()},
        },
        sort=[("local_date", 1)],
    )
    days = sorted({v.local_date for v in later})[:6]
    helpers = (
        [] if a.helper else [helper_out(h, await doc_labels(db)) for h in a.provider.helpers if h.status == "ready"]
    )
    return TodayRound(
        local_date=day,
        day_text=wording.day_text(day),
        items=items,
        helpers=helpers,
        is_today=day == today,
        upcoming_days=days,
    )


def _start_check(v: Visit, s: Settings, today: date) -> tuple[bool, str | None, bool]:
    """(can start now, why not, only because of DEMO_MODE)."""
    if v.status != "scheduled":
        return False, None, False
    if v.cover.state == "offered":
        return False, "You've asked for cover for this visit.", False
    if v.local_date > today:
        if s.demo_mode:
            return True, None, True
        return False, f"This visit is on {wording.day_text(v.local_date)}. You can start it on the day.", False
    return True, None, False


async def provider_visit(db: Db, s: Settings, a: Acting, v: Visit) -> ProviderVisit:
    booking = await Bookings(db).get(v.booking_id)
    assert booking is not None
    customer = await Customers(db).get(v.customer_id)
    cat = (await categories(db))[v.category_id]
    split = money.split_for_visit(v.price_pence, v.source, v.performer.kind, s)
    now = utcnow()
    elapsed = None
    if v.started_at is not None:
        elapsed = int(((v.finished_at or now) - v.started_at).total_seconds())
    can_start, note, demo = _start_check(v, s, london_today())
    a_ = booking.address
    name = customer.name if customer else ""
    return ProviderVisit(
        id=v.id,
        booking_id=v.booking_id,
        category_id=cat.id,
        category_name=cat.name,
        customer_name=short_name(name),
        address_line=a_.label or f"{a_.line1}, {a_.area}",
        directions_url=f"https://www.google.com/maps/dir/?api=1&destination={a_.lat},{a_.lng}",
        local_date=v.local_date,
        scheduled_start=v.scheduled_start,
        status=v.status,
        est_mins=v.est_mins,
        started_at=v.started_at,
        finished_at=v.finished_at,
        minutes_actual=v.minutes_actual,
        before_photos=await _urls(db, v.photos.before),
        after_photos=await _urls(db, v.photos.after),
        note=booking.notes,
        thread_id=booking.thread_id,
        price_pence=v.price_pence,
        provider_pence=split.provider_pence,
        charge_status=v.charge.status,
        performer_name=v.performer.name,
        category_name_lower=wording.lower_name(cat),
        customer_first=name.split(" ")[0] if name else "the customer",
        summary=summary_for(cat, booking.answers),
        window_text=schedule.WINDOW_COPY.get(v.window, ""),
        is_first=v.is_first,
        performer=v.performer.kind,
        elapsed_seconds=elapsed,
        can_start=can_start,
        start_note=note,
        early_start_demo=demo,
        flags=v.flags,
        flags_none=v.flags_none,
        minutes_from_timer=v.minutes_from_timer,
        overrun=v.overrun,
        fee_percent=split.rate_percent,
    )


async def _urls(db: Db, ids: list[str]) -> list[str]:
    if not ids:
        return []
    found = {f.id: f.url for f in await Files(db).find({"_id": {"$in": ids}})}
    return [found[i] for i in ids if i in found]


async def start_visit(db: Db, s: Settings, a: Acting, visit_id: str) -> Visit:
    """Start the timer. A visit starts on its day (or later, if it was missed); DEMO_MODE lets
    a future visit start now so the round can be demonstrated on any day. Re-checked inside the
    transaction: the visit is still this person's to do, and a helper is still ready for it."""
    v = await visit_for(db, a, visit_id)
    if v.status != "in_progress":
        can, why, _ = _start_check(v, s, london_today())
        if not can:
            if v.status != "scheduled":
                fail(status.HTTP_409_CONFLICT, "not_scheduled", "That visit can't be started.")
            fail(status.HTTP_409_CONFLICT, "not_yet", why or "That visit can't be started yet.")

    async def start(session: DbSession) -> Visit:
        await still_acting(db, s, a, v.category_id, session=session)
        started = await Visits(db).update(
            v.id,
            {"status": "in_progress", "started_at": utcnow()},
            extra_filter={"status": "scheduled", "cover.state": {"$ne": "offered"}, **acting_filter(a)},
            session=session,
        )
        if started is not None:
            return started
        now = await Visits(db).find_one({"_id": v.id, **acting_filter(a)}, session=session)
        if now is not None and now.status == "in_progress":
            return now  # started already (a double tap)
        fail(status.HTTP_409_CONFLICT, "visit_changed", "That visit has just changed. Have another look.")

    return await transaction(db, start)


async def add_photo(db: Db, a: Acting, visit_id: str, body: PhotoIn) -> Visit:
    v = await visit_for(db, a, visit_id)
    if v.status not in ("scheduled", "in_progress", "finished"):
        fail(status.HTTP_409_CONFLICT, "not_open", "Photos can't be added to that visit.")
    await own_file(db, body.file_id, a.user_id, (f"visit_{body.kind}",))
    field = f"photos.{body.kind}"
    updated = await Visits(db).find_one_and_update(
        {
            "_id": v.id,
            "status": {"$in": ["scheduled", "in_progress", "finished"]},
            f"{field}.{MAX_PHOTOS - 1}": {"$exists": False},
            **acting_filter(a),
        },
        {"$addToSet": {field: body.file_id}, "$set": {"updated_at": utcnow()}},
    )
    if updated is None:
        now = await Visits(db).find_one({"_id": v.id, **acting_filter(a)})
        if now is None:
            fail(status.HTTP_409_CONFLICT, "visit_changed", "That visit has just changed. Have another look.")
        fail(status.HTTP_409_CONFLICT, "too_many_photos", f"That's the most photos for one visit ({MAX_PHOTOS}).")
    return updated


async def send_helper(db: Db, s: Settings, a: Acting, visit_id: str, helper_user_id: str) -> Visit:
    """ "Send Tom": the helper does the visit, the provider is paid, the customer is told."""
    v = await visit_for(db, a, visit_id)
    if v.status != "scheduled":
        fail(status.HTTP_409_CONFLICT, "not_scheduled", "That visit isn't coming up any more.")
    if v.performer.kind == "cover" or v.cover.state != "none":
        fail(status.HTTP_409_CONFLICT, "already_offered", "That visit has gone out for cover.")
    cat = (await categories(db))[v.category_id]
    helper = ready_helper(a.provider, helper_user_id, cat, demo=s.demo_mode)
    if v.performer.user_id == helper.user_id:
        return v
    performer = Performer(
        kind="helper", provider_id=a.provider.id, user_id=helper.user_id, name=short_name(helper.name)
    )
    customer = await Customers(db).get(v.customer_id)
    cu = await Users(db).get(customer.user_id) if customer else None

    async def send(session: DbSession) -> Visit:
        # The helper as they are now, in this transaction (writing the provider makes a concurrent
        # change to their documents or status conflict with it, and the re-run sees it).
        now = await Providers(db).update(a.provider.id, {}, session=session)
        assert now is not None
        ready_helper(now, helper_user_id, cat, demo=s.demo_mode)
        updated = await Visits(db).update(
            v.id,
            {"performer": performer.model_dump()},
            extra_filter={"status": "scheduled", "provider_id": a.provider.id, "cover.state": "none"},
            session=session,
        )
        if updated is None:
            fail(status.HTTP_409_CONFLICT, "visit_changed", "That visit has just changed. Have another look.")
        await tell_helper_coming(db, s, a.provider.short, updated, helper.name, cu, session=session)
        return updated

    return await transaction(db, send)


async def tell_helper_coming(
    db: Db,
    s: Settings,
    provider_short: str,
    v: Visit,
    helper_name: str,
    customer_user: User | None,
    *,
    session: DbSession,
) -> None:
    if customer_user is None or not customer_user.phone:
        return
    await notify(
        db,
        "helper_coming",
        to=recipient_for(customer_user),
        data={
            "provider": provider_short,
            "date": wording.day_text(v.local_date),
            "helper": short_name(helper_name),
        },
        related=Related(visit_id=v.id, booking_id=v.booking_id, customer_id=v.customer_id),
        idempotency_key=f"visit:{v.id}:helper:{v.performer.user_id}",
        settings=s,
        session=session,
    )


async def visit_detail(db: Db, s: Settings, a: Acting, visit_id: str) -> ProviderVisit:
    return await provider_visit(db, s, a, await visit_for(db, a, visit_id))
