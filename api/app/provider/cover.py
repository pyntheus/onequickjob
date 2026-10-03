"""Local cover for one visit (decisions.md R23a, A4): the visit is offered to other eligible
providers through the normal offer flow, at the same price. Whoever accepts (the shared
accept endpoint) does that one visit and is paid for it at the standard fee; the customer
stays the regular provider's, and the plan carries on with them afterwards.

This module creates the cover request and, when nobody takes it by the day before, skips the
visit and tells the customer and the provider.
"""

from datetime import date, timedelta

from fastapi import status

from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail
from app.core.geo import approximate
from app.core.ids import next_ref
from app.core.timeutil import london_today, utcnow, weekday_key
from app.models.bookings import Booking
from app.models.categories import Category
from app.models.common import GeoPoint, Related
from app.models.job_requests import Broadcast, JobRequest, RequestEvent, When
from app.models.providers import Provider
from app.models.users import User
from app.models.visits import Visit
from app.provider.common import quiet_until
from app.repos.bookings import Bookings
from app.repos.categories import Categories
from app.repos.customers import Customers
from app.repos.job_requests import JobRequests
from app.repos.offers import Offers
from app.repos.providers import Providers
from app.repos.series import SeriesRepo
from app.repos.users import Users
from app.repos.visits import Visits
from app.services import wording
from app.services.auth import create_magic_link
from app.services.eligibility import alert_targets
from app.services.notify import link, notify, recipient_for


async def cover_allowed(db: Db, visit: Visit, *, session: DbSession | None = None) -> bool:
    """A plan's customer chooses whether cover may be offered when their provider is away
    (series.cover_when_away); a one-off can always be covered."""
    if not visit.series_id:
        return True
    series = await SeriesRepo(db).get(visit.series_id, session=session)
    return series is None or series.cover_when_away


def check_coverable(visit: Visit, provider: Provider, today: date) -> None:
    if visit.provider_id != provider.id or visit.performer.kind == "cover":
        fail(status.HTTP_409_CONFLICT, "not_your_visit", "Only your own regular visits can go out for cover.")
    if visit.status != "scheduled":
        fail(status.HTTP_409_CONFLICT, "not_scheduled", "That visit isn't coming up any more.")
    if visit.cover.state != "none":
        fail(status.HTTP_409_CONFLICT, "already_offered", "That visit has already gone out for cover.")
    if visit.local_date <= today:
        fail(
            status.HTTP_409_CONFLICT,
            "too_late_for_cover",
            "Cover needs at least a day's notice. Send a helper, or message the customer.",
        )


async def offer_cover(
    db: Db, s: Settings, provider: Provider, visit: Visit, booking: Booking, *, session: DbSession
) -> JobRequest:
    """Inside the caller's transaction: the cover request, its broadcast and alerts, and the
    visit marked as offered for cover."""
    cat = await Categories(db).get(visit.category_id, session=session)
    assert cat is not None
    now = utcnow()
    original = await JobRequests(db).get(booking.request_id, session=session) if booking.request_id else None
    lat, lng = approximate(booking.address.lat, booking.address.lng)
    req = JobRequest(
        ref=await next_ref(db, "request", session=session),
        customer_id=visit.customer_id,
        category_id=visit.category_id,
        quote_id=original.quote_id if original else "",
        pricing_version_id=visit.pricing_version_id
        or booking.pricing_version_id
        or (original.pricing_version_id if original else ""),
        answers=booking.answers,
        measure=original.measure if original else None,
        address=booking.address,
        approx=GeoPoint(lat=lat, lng=lng),
        notes=booking.notes,
        when=When(days="weekends" if visit.local_date.weekday() >= 5 else "weekdays", time=visit.window),
        recurring=False,
        frequency="oneoff",
        guide_pence=visit.price_pence,
        mins=visit.est_mins,
        unit="one-off",
        cover_for_visit_id=visit.id,
        events=[
            RequestEvent(
                at=now,
                kind="created",
                provider_id=provider.id,
                text=f"Cover for {provider.short} on {wording.day_text(visit.local_date)}",
            )
        ],
    )
    weekday = weekday_key(visit.local_date)
    targets = [
        t
        for t in await alert_targets(db, req, cat, session=session)
        if t.provider.id != provider.id and weekday in t.provider.working_days
    ]
    req.broadcast = Broadcast(at=now, provider_ids=[t.provider.id for t in targets], rule="cover_v1")
    req.events.append(RequestEvent(at=now, kind="broadcast", count=len(targets)))
    await JobRequests(db).insert(req, session=session)
    marked = await Visits(db).update(
        visit.id,
        {"cover": {"state": "offered", "request_id": req.id, "original_provider_id": provider.id}},
        extra_filter={"status": "scheduled", "provider_id": provider.id, "cover.state": "none"},
        session=session,
    )
    if marked is None:
        fail(status.HTTP_409_CONFLICT, "visit_changed", "That visit has just changed. Have another look.")
    for t in targets:
        await _cover_alert(db, s, req, cat, visit, provider, t.provider, session=session)
    return req


async def _cover_alert(
    db: Db,
    s: Settings,
    req: JobRequest,
    cat: Category,
    visit: Visit,
    regular: Provider,
    to: Provider,
    *,
    session: DbSession,
) -> None:
    user = await Users(db).get(to.user_id, session=session)
    if user is None or not user.phone:
        return
    path = f"/p/j/{req.ref}"
    token = await create_magic_link(db, s, user.id, "job_alert", path, session=session)
    data = {
        "category": cat.name,
        "area": req.address.area,
        "date": wording.day_text(visit.local_date),
        "price": wording.money(visit.price_pence),
        "provider": regular.short,
        "link": link(f"{path}?t={token}", s),
    }
    held = quiet_until(to.alert_settings, utcnow())
    for channel, on in (("sms", to.alert_settings.sms), ("whatsapp", to.alert_settings.whatsapp)):
        if on:
            await notify(
                db,
                "cover_alert",
                to=recipient_for(user),
                channel=channel,  # type: ignore[arg-type]
                data=data,
                related=Related(request_id=req.id, visit_id=visit.id, provider_id=to.id),
                not_before=held,
                settings=s,
                session=session,
            )


async def ask_for_cover(db: Db, s: Settings, provider: Provider, visit_id: str) -> Visit:
    """ "Get cover" for one visit, outside a time-off booking."""
    visit = await Visits(db).get(visit_id)
    if visit is None or visit.provider_id != provider.id:
        fail(status.HTTP_404_NOT_FOUND, "not_found", "That visit wasn't found.")
    check_coverable(visit, provider, london_today())
    if not await cover_allowed(db, visit):
        fail(
            status.HTTP_409_CONFLICT,
            "cover_not_wanted",
            "This customer would rather not have cover. Send a helper, or message them to move the visit.",
        )
    booking = await Bookings(db).get(visit.booking_id)
    assert booking is not None

    async def ask(session: DbSession) -> None:
        await offer_cover(db, s, provider, visit, booking, session=session)

    await transaction(db, ask)
    updated = await Visits(db).get(visit.id)
    assert updated is not None
    return updated


# ------------------------------------------------------------------ nobody took it


async def next_visit_text(db: Db, visit: Visit, *, session: DbSession | None = None) -> str:
    if not visit.series_id:
        return ""
    nxt = await Visits(db).find_one(
        {"series_id": visit.series_id, "status": "scheduled", "local_date": {"$gt": visit.local_date.isoformat()}},
        sort=[("local_date", 1)],
        session=session,
    )
    return f"Your next visit is {wording.day_text(nxt.local_date)}." if nxt else ""


async def tell_customer_skipped(db: Db, s: Settings, visit: Visit, cat_name: str, *, session: DbSession) -> None:
    customer = await Customers(db).get(visit.customer_id, session=session)
    user = await Users(db).get(customer.user_id, session=session) if customer else None
    if user is None or not user.phone:
        return
    await notify(
        db,
        "visit_skipped",
        to=recipient_for(user),
        data={
            "category": cat_name[0].lower() + cat_name[1:],
            "date": wording.day_text(visit.local_date),
            "next_text": await next_visit_text(db, visit, session=session),
        },
        related=Related(visit_id=visit.id, booking_id=visit.booking_id, customer_id=visit.customer_id),
        idempotency_key=f"visit:{visit.id}:skipped",
        settings=s,
        session=session,
    )


async def close_dead_covers(db: Db) -> int:
    """Cover requests whose visit isn't happening any more (the customer skipped it, or the plan
    was cancelled): close them, so nobody takes a visit that won't happen. The shared accept
    doesn't check this itself yet (contract-changes/L2.md)."""
    closed = 0
    for req in await JobRequests(db).find({"status": "open", "cover_for_visit_id": {"$type": "string"}}):
        visit = await Visits(db).get(req.cover_for_visit_id or "")
        if visit is not None and visit.status == "scheduled":
            continue

        async def close(session: DbSession, req: JobRequest = req) -> bool:
            event = RequestEvent(at=utcnow(), kind="note", text="The visit isn't happening any more")
            done = await JobRequests(db).update(
                req.id,
                {"status": "expired"},
                push={"events": event.model_dump(mode="python")},
                extra_filter={"status": "open"},
                session=session,
            )
            if done is not None:
                await Offers(db).lapse_pending(req.id, session=session)
            return done is not None

        if await transaction(db, close):
            closed += 1
    return closed


async def expire_uncovered(db: Db, s: Settings, today: date | None = None) -> int:
    """Cover requests still open the day before their visit: nobody took it, so the request
    expires, the visit is skipped, and the customer and the provider are told. Each one is its
    own transaction; a cover accepted meanwhile wins (the request is no longer open)."""
    today = today or london_today()
    done = 0
    for req in await JobRequests(db).find({"status": "open", "cover_for_visit_id": {"$type": "string"}}):
        visit = await Visits(db).get(req.cover_for_visit_id or "")
        if visit is None or visit.local_date > today + timedelta(days=1):
            continue
        cat = await Categories(db).get(req.category_id)
        name = cat.name if cat else "visit"

        async def give_up(session: DbSession, req: JobRequest = req, visit: Visit = visit, name: str = name) -> bool:
            now = utcnow()
            closed = await JobRequests(db).update(
                req.id,
                {"status": "expired"},
                push={
                    "events": RequestEvent(at=now, kind="note", text="Nobody took the cover").model_dump(mode="python")
                },
                extra_filter={"status": "open"},
                session=session,
            )
            if closed is None:
                return False
            await Offers(db).lapse_pending(req.id, session=session)
            skipped = await Visits(db).update(
                visit.id,
                {"status": "skipped", "skipped_reason": "No cover found", "cover.state": "none"},
                extra_filter={"status": "scheduled", "cover.request_id": req.id},
                session=session,
            )
            if skipped is None:
                return True
            await tell_customer_skipped(db, s, skipped, name, session=session)
            regular = await _provider_user(db, visit.cover.original_provider_id or visit.provider_id, session)
            customer = await Customers(db).get(visit.customer_id, session=session)
            if regular is not None and regular.phone:
                await notify(
                    db,
                    "cover_not_found",
                    to=recipient_for(regular),
                    data={
                        "customer": (customer.name.split(" ")[0] if customer else "Your customer"),
                        "category": name[0].lower() + name[1:],
                        "date": wording.day_text(visit.local_date),
                    },
                    related=Related(visit_id=visit.id, request_id=req.id),
                    idempotency_key=f"visit:{visit.id}:cover_not_found",
                    settings=s,
                    session=session,
                )
            return True

        if await transaction(db, give_up):
            done += 1
    return done


async def _provider_user(db: Db, provider_id: str, session: DbSession) -> User | None:
    p = await Providers(db).get(provider_id, session=session)
    return await Users(db).get(p.user_id, session=session) if p else None
