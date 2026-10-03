"""Job requests from the customer's side (L1): create and broadcast, cancel, expire.

Creating a request is one transaction (decisions.md A7): the customer's details, the request,
the quote's link to it, every job alert with its magic link, and the customer's confirmation
commit together or not at all. Who gets an alert is worked out before it, on plain reads
(app.services.eligibility.alert_targets): alerts are advisory, and every acceptance checks
eligibility again inside its own transaction.
"""

from datetime import date, datetime, time, timedelta

from fastapi import status
from pymongo.errors import DuplicateKeyError

from app.core import money
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail
from app.core.geo import approximate, miles_between
from app.core.ids import next_ref
from app.core.timeutil import london_datetime, to_london, utcnow
from app.customer import templates as _templates  # noqa: F401 (registers L1's templates)
from app.customer.schemas import NewRequest
from app.models.categories import Category
from app.models.common import Channel, GeoPoint, Related
from app.models.customers import Customer
from app.models.job_requests import Broadcast, JobRequest, RequestEvent
from app.models.providers import AlertSettings, Provider
from app.models.quotes import Quote
from app.models.users import User
from app.repos.bookings import Bookings
from app.repos.categories import Categories
from app.repos.customers import Customers
from app.repos.files import Files
from app.repos.job_requests import JobRequests
from app.repos.offers import Offers
from app.repos.providers import Providers
from app.repos.quotes import Quotes
from app.repos.users import Users
from app.repos.visits import Visits
from app.services import schedule, wording
from app.services.auth import create_magic_link
from app.services.eligibility import AlertTarget, alert_targets
from app.services.notify import link, notify, recipient_for
from app.services.quotes import bookable_category

EXPIRE_AFTER = timedelta(days=7)
ROUTE_MILES = 1.0  # "fits your round": another of their visits within a mile
ROUTE_DAYS = 14


# ------------------------------------------------------------------------------- helpers


def quiet_until(alerts: AlertSettings, now: datetime) -> datetime | None:
    """When a text sent now would go out, if now is inside the provider's quiet hours."""
    if not alerts.quiet_hours:
        return None
    local = to_london(now)
    start, end = time.fromisoformat(alerts.quiet_from), time.fromisoformat(alerts.quiet_to)
    t = local.time().replace(tzinfo=None)
    quiet = (t >= start or t < end) if start > end else (start <= t < end)
    if not quiet:
        return None
    day = local.date() if t < end else local.date() + timedelta(days=1)
    return london_datetime(day, end)


async def route_hint(db: Db, provider: Provider, req: JobRequest, today: date) -> str:
    """ " It's 0.4 miles from your Tuesday 9:00." when another of their visits is near."""
    upcoming = await Visits(db).find(
        {
            "provider_id": provider.id,
            "status": "scheduled",
            "local_date": {"$gt": today.isoformat(), "$lte": (today + timedelta(days=ROUTE_DAYS)).isoformat()},
        },
        sort=[("scheduled_start", 1)],
        limit=60,
    )
    best: tuple[float, datetime] | None = None
    addresses: dict[str, tuple[float, float] | None] = {}
    for v in upcoming:
        if not schedule.suits(v.local_date, req.when.days):
            continue
        if v.booking_id not in addresses:
            b = await Bookings(db).get(v.booking_id)
            addresses[v.booking_id] = (b.address.lat, b.address.lng) if b else None
        where = addresses[v.booking_id]
        if where is None:
            continue
        miles = miles_between(where[0], where[1], req.address.lat, req.address.lng)
        if miles <= ROUTE_MILES and (best is None or miles < best[0]):
            best = (miles, v.scheduled_start)
    if best is None:
        return ""
    local = to_london(best[1])
    return f" It's {best[0]:.1f} miles from your {local:%A} {wording.time_text(best[1])}."


def _channels(p: Provider) -> list[Channel]:
    return [c for c, on in (("sms", p.alert_settings.sms), ("whatsapp", p.alert_settings.whatsapp)) if on]


async def send_job_alerts(
    db: Db,
    s: Settings,
    req: JobRequest,
    cat: Category,
    targets: list[AlertTarget],
    hints: dict[str, str],
    *,
    session: DbSession,
) -> None:
    """One job_alert per target and chosen channel, each with its own single-use sign-in link,
    held for quiet hours. Inside the request's transaction."""
    split = money.split(req.guide_pence, "standard", s)
    now = utcnow()
    path = f"/p/j/{req.ref}"
    for t in targets:
        user = await Users(db).get(t.provider.user_id, session=session)
        if user is None or not user.phone:
            continue
        for ch in _channels(t.provider):
            token = await create_magic_link(db, s, user.id, "job_alert", path, session=session)
            await notify(
                db,
                "job_alert",
                to=recipient_for(user),
                channel=ch,
                settings=s,
                not_before=quiet_until(t.provider.alert_settings, now),
                related=Related(request_id=req.id, customer_id=req.customer_id, provider_id=t.provider.id),
                idempotency_key=f"request:{req.id}:job_alert:{t.provider.id}:{ch}",
                data={
                    "category": cat.name,
                    "area": req.address.area,
                    "district": req.address.district,
                    "mins": req.mins,
                    "frequency": wording.FREQUENCY_WORDS.get(req.frequency or "oneoff", "one-off"),
                    "guide": wording.money(req.guide_pence),
                    "net": wording.money(split.provider_pence),
                    "route": hints.get(t.provider.id, ""),
                    "link": link(f"{path}?t={token}", s),
                },
                session=session,
            )


async def targets_for(db: Db, req: JobRequest, cat: Category) -> tuple[list[AlertTarget], dict[str, str]]:
    today = to_london(utcnow()).date()
    targets = await alert_targets(db, req, cat, today)
    hints = {t.provider.id: await route_hint(db, t.provider, req, today) for t in targets}
    return targets, hints


# ------------------------------------------------------------------------------- create


async def _check_photos(db: Db, user: User, ids: list[str], cat: Category) -> list[str]:
    limit = max((f.max_photos or 4 for f in cat.intake if f.type == "photos"), default=4)
    if len(ids) > limit:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_many_photos", f"Add up to {limit} photos.")
    ids = list(dict.fromkeys(ids))
    found = await Files(db).find({"_id": {"$in": ids}, "owner_user_id": user.id}) if ids else []
    if len(found) != len(ids):
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_photo", "One of those photos didn't upload. Try again.")
    return ids


async def _quote(db: Db, user: User, quote_id: str) -> Quote:
    quote = await Quotes(db).get(quote_id)
    if quote is None or (quote.user_id and quote.user_id != user.id):
        fail(status.HTTP_404_NOT_FOUND, "not_found", "That price wasn't found. Please get a new one.")
    return quote


async def create_request(db: Db, s: Settings, user: User, body: NewRequest) -> JobRequest:
    quote = await _quote(db, user, body.quote_id)
    customer = await Customers(db).by_user(user.id)
    if quote.request_id:
        existing = await JobRequests(db).get(quote.request_id)
        if existing and customer and existing.customer_id == customer.id:
            return existing  # sent twice (a double tap): the same request
        fail(status.HTTP_409_CONFLICT, "quote_used", "That price has already been used. Please get a new one.")
    cat = await bookable_category(db, quote.category_id)
    if customer is None or customer.payment is None or customer.payment.card is None:
        fail(status.HTTP_409_CONFLICT, "card_needed", "Add a card first. Nothing is charged until the work is done.")
    photos = await _check_photos(db, user, body.photos, cat)
    email = (body.contact.email or "").strip().lower() or None
    if email:
        other = await Users(db).by_email(email)
        if other and other.id != user.id:
            fail(
                status.HTTP_409_CONFLICT,
                "email_in_use",
                "That email belongs to another account. Use a different one, or leave it blank.",
            )

    now = utcnow()
    lat, lng = approximate(body.address.lat, body.address.lng)
    frequency = quote.answers.get("frequency") if isinstance(quote.answers.get("frequency"), str) else None
    draft = JobRequest(
        ref="pending",
        customer_id=customer.id,
        category_id=cat.id,
        quote_id=quote.id,
        pricing_version_id=quote.pricing_version_id,
        answers=quote.answers,
        measure=quote.measure,
        address=body.address,
        approx=GeoPoint(lat=lat, lng=lng),
        notes=body.notes.strip(),
        when=body.when,
        recurring=schedule.recurring(frequency),
        frequency=frequency,
        guide_pence=quote.result.price_pence,
        first_pence=quote.result.first_pence,
        mins=quote.result.mins,
        first_mins=quote.result.first_mins,
        unit=quote.result.unit,
        photos=photos,
        created_at=now,
        updated_at=now,
    )
    targets, hints = await targets_for(db, draft, cat)
    name = body.contact.name.strip()

    async def create(session: DbSession) -> JobRequest:
        req = draft.model_copy(update={"ref": await next_ref(db, "request", session=session)})
        req.broadcast = Broadcast(at=now, provider_ids=[t.provider.id for t in targets])
        req.events = [
            RequestEvent(at=now, kind="created", by_user_id=user.id),
            RequestEvent(at=now, kind="broadcast", count=len(targets)),
        ]
        await Customers(db).update(customer.id, {"name": name, "terms_accepted_at": now}, session=session)
        await Customers(db).add_address(customer.id, body.address, session=session)
        user_fields: dict = {"name": name}
        if email:
            user_fields["email"] = email
        await Users(db).update(user.id, user_fields, session=session)
        await JobRequests(db).insert(req, session=session)
        if (
            await Quotes(db).update(
                quote.id, {"request_id": req.id}, extra_filter={"request_id": None}, session=session
            )
            is None
        ):
            fail(status.HTTP_409_CONFLICT, "quote_used", "That price has already been used. Please get a new one.")
        await send_job_alerts(db, s, req, cat, targets, hints, session=session)
        if user.phone:
            template = "request_sent" if targets else "request_no_providers"
            await notify(
                db,
                template,
                to=recipient_for(user.model_copy(update={"name": name})),
                settings=s,
                related=Related(request_id=req.id, customer_id=customer.id),
                idempotency_key=f"request:{req.id}:{template}",
                data={"category": wording.lower_name(cat), "district": req.address.district},
                session=session,
            )
        return req

    try:
        return await transaction(db, create)
    except DuplicateKeyError:
        fail(
            status.HTTP_409_CONFLICT,
            "email_in_use",
            "That email belongs to another account. Use a different one, or leave it blank.",
        )


# ------------------------------------------------------------------------------- cancel and expire


async def _close_counters(
    db: Db, s: Settings, req: JobRequest, cat: Category, new_status: str, *, session: DbSession
) -> None:
    """Pending counters on a request that closed unbooked: withdrawn (cancelled) or lapsed
    (expired), and each provider told."""
    for o in await Offers(db).find({"request_id": req.id, "status": "pending"}, session=session):
        updated = await Offers(db).update(
            o.id, {"status": new_status, "decided_at": utcnow()}, extra_filter={"status": "pending"}, session=session
        )
        if updated is None:
            continue
        provider = await Providers(db).get(o.provider_id, session=session)
        pu = await Users(db).get(provider.user_id, session=session) if provider else None
        if pu and pu.phone:
            await notify(
                db,
                "request_closed",
                to=recipient_for(pu),
                settings=s,
                related=Related(request_id=req.id, offer_id=o.id, provider_id=o.provider_id),
                idempotency_key=f"offer:{o.id}:request_closed",
                data={"category": wording.lower_name(cat), "area": req.address.area},
                session=session,
            )


async def cancel_request(db: Db, s: Settings, req: JobRequest, customer: Customer, user: User) -> JobRequest:
    if req.status == "booked":
        fail(status.HTTP_409_CONFLICT, "already_booked", "It's already booked. You can change it from your account.")
    if req.status != "open":
        fail(status.HTTP_409_CONFLICT, "not_open", "This request isn't open any more.")
    cat = await bookable_category(db, req.category_id)

    async def cancel(session: DbSession) -> JobRequest:
        now = utcnow()
        event = RequestEvent(at=now, kind="cancelled", by_user_id=user.id)
        updated = await JobRequests(db).find_one_and_update(
            {"_id": req.id, "status": "open"},
            {"$set": {"status": "cancelled", "updated_at": now}, "$push": {"events": event.model_dump(mode="python")}},
            session=session,
        )
        if updated is None:
            current = await JobRequests(db).get(req.id, session=session)
            if current and current.status == "booked":
                fail(
                    status.HTTP_409_CONFLICT,
                    "already_booked",
                    "Someone has just booked it. You can change it from your account.",
                )
            fail(status.HTTP_409_CONFLICT, "not_open", "This request isn't open any more.")
        await _close_counters(db, s, updated, cat, "withdrawn", session=session)
        return updated

    return await transaction(db, cancel)


async def expire_request(db: Db, s: Settings, req: JobRequest) -> JobRequest | None:
    """Open for 7 days with no booking: close it, lapse any counters, tell the customer."""
    cat = await Categories(db).get(req.category_id)
    if cat is None:
        return None

    async def expire(session: DbSession) -> JobRequest | None:
        now = utcnow()
        event = RequestEvent(at=now, kind="expired")
        updated = await JobRequests(db).find_one_and_update(
            {"_id": req.id, "status": "open", "created_at": {"$lte": now - EXPIRE_AFTER}},
            {"$set": {"status": "expired", "updated_at": now}, "$push": {"events": event.model_dump(mode="python")}},
            session=session,
        )
        if updated is None:
            return None
        await _close_counters(db, s, updated, cat, "lapsed", session=session)
        customer = await Customers(db).get(updated.customer_id, session=session)
        cu = await Users(db).get(customer.user_id, session=session) if customer else None
        if cu and cu.phone:
            await notify(
                db,
                "request_expired",
                to=recipient_for(cu),
                settings=s,
                related=Related(request_id=updated.id, customer_id=updated.customer_id),
                idempotency_key=f"request:{updated.id}:request_expired",
                data={"category": wording.lower_name(cat), "link": link("/", s)},
                session=session,
            )
        return updated

    return await transaction(db, expire)


async def expire_stale(db: Db, s: Settings) -> int:
    cutoff = utcnow() - EXPIRE_AFTER
    n = 0
    for req in await JobRequests(db).find(
        {"status": "open", "created_at": {"$lte": cutoff}, "cover_for_visit_id": None}
    ):
        if await expire_request(db, s, req):
            n += 1
    return n
