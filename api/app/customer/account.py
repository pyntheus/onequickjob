"""The customer's account (L1): visits, plans, rating a visit, reporting a problem, booking the
same provider again. Every write that spans collections is one transaction (decisions.md A7);
the tip is charged through the PaymentGateway outside any transaction, between two of them.
"""

from datetime import timedelta

from fastapi import HTTPException, status

from app.adapters.payments.base import PaymentGateway
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.core.geo import approximate
from app.core.ids import next_ref
from app.core.timeutil import london_today, utcnow
from app.customer import requests as request_service
from app.customer.schemas import ChangeDateIn, PlanUpdate, ProblemIn, RatingIn, RebookIn
from app.customer.views import REPORT_WINDOW
from app.models.bookings import Booking, Pause, Series
from app.models.categories import Category
from app.models.common import GeoPoint, Related
from app.models.customers import Customer
from app.models.disputes import Dispute, DisputeEvent
from app.models.job_requests import Broadcast, JobRequest, RequestEvent, When
from app.models.messages import MessageThread, Participant
from app.models.providers import Provider
from app.models.ratings import Rating
from app.models.users import User
from app.models.visits import Visit
from app.payments import charging
from app.repos.bookings import Bookings
from app.repos.categories import Categories
from app.repos.customers import Customers
from app.repos.disputes import Disputes
from app.repos.files import Files
from app.repos.job_requests import JobRequests
from app.repos.messages import Messages, MessageThreads
from app.repos.plan_changes import PlanChanges
from app.repos.providers import Providers
from app.repos.ratings import Ratings
from app.repos.series import SeriesRepo
from app.repos.users import Users
from app.repos.visits import Visits
from app.services import schedule, wording
from app.services.notify import link, notify, recipient_for
from app.services.quotes import live_version

ALL_TAGS_MAX_LEN = 40
WINTER = schedule.WINTER_MONTHS
PAUSES = ("winter", "away")


# ------------------------------------------------------------------------------- lookups


async def own_visit(db: Db, visit_id: str, customer: Customer) -> Visit:
    visit = await Visits(db).get(visit_id)
    if visit is None or visit.customer_id != customer.id:
        not_found("That visit")
    return visit


async def own_booking(db: Db, booking_id: str, customer: Customer) -> Booking:
    booking = await Bookings(db).get(booking_id)
    if booking is None or booking.customer_id != customer.id:
        not_found("That booking")
    return booking


async def own_series(db: Db, series_id: str, customer: Customer) -> tuple[Series, Booking]:
    series = await SeriesRepo(db).get(series_id)
    if series is None or series.customer_id != customer.id:
        not_found("That plan")
    booking = await Bookings(db).get(series.booking_id)
    assert booking is not None, series.booking_id
    return series, booking


async def _category(db: Db, category_id: str, session: DbSession | None = None) -> Category:
    cat = await Categories(db).get(category_id, session=session)
    assert cat is not None, category_id
    return cat


async def _provider_user(db: Db, provider_id: str, session: DbSession | None = None) -> tuple[Provider, User | None]:
    provider = await Providers(db).get(provider_id, session=session)
    assert provider is not None, provider_id
    return provider, await Users(db).get(provider.user_id, session=session)


async def system_note(db: Db, thread_id: str | None, text: str, session: DbSession) -> None:
    """A line in the booking's thread, so the provider sees what the customer changed."""
    if thread_id:
        await Messages(db).post(thread_id, None, "system", text, session=session)


async def _post_and_tell(
    db: Db, s: Settings, thread_id: str, sender: User, role: str, body: str, *, session: DbSession
) -> None:
    """Post as the customer and text the other participants (message_received)."""
    from app.customer.threads import notify_others

    msg = await Messages(db).post(thread_id, sender.id, role, body, session=session)
    thread = await MessageThreads(db).get(thread_id, session=session)
    if thread:
        await notify_others(db, s, thread, sender, msg.body, session=session)


# ------------------------------------------------------------------------------- visits


async def skip_visit(db: Db, s: Settings, visit: Visit, customer: Customer, user: User) -> Visit:
    if visit.status != "scheduled" or not visit.series_id:
        fail(status.HTTP_409_CONFLICT, "cannot_skip", "Only upcoming visits in a regular plan can be skipped.")
    if visit.scheduled_start <= utcnow():
        fail(status.HTTP_409_CONFLICT, "cannot_skip", "That visit has already started.")
    cat = await _category(db, visit.category_id)
    booking = await Bookings(db).get(visit.booking_id)

    async def skip(session: DbSession) -> Visit:
        updated = await Visits(db).update(
            visit.id,
            {"status": "skipped", "skipped_reason": "customer"},
            extra_filter={"status": "scheduled"},
            session=session,
        )
        if updated is None:
            fail(status.HTTP_409_CONFLICT, "cannot_skip", "That visit can't be skipped now.")
        nxt = await Visits(db).find_one(
            {"series_id": visit.series_id, "status": "scheduled", "local_date": {"$gt": visit.local_date.isoformat()}},
            sort=[("local_date", 1)],
            session=session,
        )
        next_text = f"Your next one is {wording.day_text(nxt.local_date)}." if nxt else ""
        day = wording.day_text(visit.local_date)
        await system_note(
            db, booking.thread_id if booking else None, f"{customer.name} skipped the visit on {day}.", session
        )
        if user.phone:
            await notify(
                db,
                "visit_skipped",
                to=recipient_for(user),
                settings=s,
                related=Related(visit_id=visit.id, booking_id=visit.booking_id, customer_id=customer.id),
                idempotency_key=f"visit:{visit.id}:visit_skipped",
                data={"category": wording.lower_name(cat), "date": day, "next_text": next_text},
                session=session,
            )
        return updated

    return await transaction(db, skip)


async def change_date(db: Db, s: Settings, visit: Visit, customer: Customer, user: User, body: ChangeDateIn) -> Visit:
    """A one-off's date can't simply move (the provider's round decides it), so the preferred
    dates go to the provider in the booking's thread and they reply there."""
    if visit.status != "scheduled" or visit.scheduled_start <= utcnow():
        fail(status.HTTP_409_CONFLICT, "cannot_change", "That visit can't be moved now.")
    today = london_today()
    if any(d <= today or d > today + timedelta(days=120) for d in body.preferred):
        fail(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_date", "Pick dates from tomorrow, within the next four months."
        )
    booking = await Bookings(db).get(visit.booking_id)
    if booking is None or not booking.thread_id:
        fail(status.HTTP_409_CONFLICT, "cannot_change", "That visit can't be moved now.")
    dates = ", ".join(wording.day_text(d) for d in sorted(set(body.preferred)))
    text = f"Could we move the visit on {wording.day_text(visit.local_date)}? These dates suit me: {dates}."
    if body.note.strip():
        text += f" {body.note.strip()}"

    async def ask(session: DbSession) -> None:
        await _post_and_tell(db, s, booking.thread_id, user, "customer", text, session=session)

    await transaction(db, ask)
    return visit


# ------------------------------------------------------------------------------- rating and tips


def _tags(tags: list[str]) -> list[str]:
    out = [t.strip()[:ALL_TAGS_MAX_LEN] for t in tags if t.strip()]
    return list(dict.fromkeys(out))


async def _rated_message(db: Db, s: Settings, visit: Visit, stars: int, *, session: DbSession) -> None:
    """rating_received to the provider, once per visit. A tip is announced separately when it's
    charged (tip_received, from app.payments.charging), so this never claims one in advance."""
    customer = await Customers(db).get(visit.customer_id, session=session)
    provider, pu = await _provider_user(db, visit.provider_id, session)
    cat = await _category(db, visit.category_id, session)
    if pu and pu.phone:
        await notify(
            db,
            "rating_received",
            to=recipient_for(pu),
            settings=s,
            related=Related(visit_id=visit.id, booking_id=visit.booking_id, provider_id=provider.id),
            idempotency_key=f"visit:{visit.id}:rating_received",
            data={
                "customer": wording.first_name(customer.name if customer else "") or "Your customer",
                "category": wording.lower_name(cat),
                "stars": stars,
                "tip_text": "",
            },
            session=session,
        )


def tip_status(visit: Visit) -> str:
    """none, charged, failed, or pending (the outcome isn't known yet; L3's settle task finishes it)."""
    charge = visit.tip_charge
    if not visit.tip_pence:
        return "none"
    if charge is None or charge.status == "pending":
        return "pending"
    return "charged" if charge.status == "succeeded" else "failed"


async def rate_visit(
    db: Db, s: Settings, gateway: PaymentGateway, visit: Visit, customer: Customer, user: User, body: RatingIn
) -> tuple[Rating, Visit]:
    """Stars and tags, then any tip. The rating and the tip amount commit first; the tip is then
    charged through the one charging path (app.payments.charging.charge_visit, purpose "tip": the
    intent recorded, the gateway called outside any transaction with the attempt's idempotency
    key, the result recorded with its ledger entry and the provider's message). The tip has no
    fee (money.split(tip, "tip")): all of it goes to the provider."""
    if visit.status != "finished":
        fail(status.HTTP_409_CONFLICT, "not_finished", "You can rate a visit once it's done.")
    if visit.rating_id:
        if visit.tip_pence and visit.tip_charge is None:
            # The rating was saved but its tip never started (interrupted): finish it now.
            rating = await Ratings(db).get(visit.rating_id)
            assert rating is not None, visit.rating_id
            return rating, await charging.charge_visit(db, s, gateway, visit.id, purpose="tip")
        fail(status.HTTP_409_CONFLICT, "already_rated", "You've already rated this visit.")
    if body.tip_pence % 100:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "whole_pounds", "Tips are in whole pounds.")
    tip = body.tip_pence
    if tip and not (customer.payment and customer.payment.gateway_customer_id):
        fail(status.HTTP_409_CONFLICT, "card_needed", "Add a card to send a tip.")
    rating = Rating(
        visit_id=visit.id,
        booking_id=visit.booking_id,
        customer_id=customer.id,
        provider_id=visit.provider_id,
        stars=body.stars,
        tags=_tags(body.tags),
        tip_pence=tip,
        comment=body.comment.strip(),
    )

    async def save(session: DbSession) -> Rating:
        fields: dict = {"rating_id": rating.id}
        if tip:
            fields["tip_pence"] = tip
        if await Visits(db).update(visit.id, fields, extra_filter={"rating_id": None}, session=session) is None:
            fail(status.HTTP_409_CONFLICT, "already_rated", "You've already rated this visit.")
        await Ratings(db).insert(rating, session=session)
        await Providers(db).apply_rating(visit.provider_id, body.stars, session=session)
        await _rated_message(db, s, visit, body.stars, session=session)
        return rating

    saved = await transaction(db, save)
    if not tip:
        return saved, await charging.get_visit(db, visit.id)
    return saved, await charging.charge_visit(db, s, gateway, visit.id, purpose="tip")


TIP_START_AFTER = timedelta(minutes=2)


async def start_orphaned_tips(db: Db, s: Settings, gateway: PaymentGateway) -> int:
    """Tips whose rating was saved but whose charge never started (the request stopped between
    the two): start them through the charging path. Safe: the gateway is only ever called after
    the intent is recorded, so a tip with no intent was never charged. Returns how many started."""
    n = 0
    stale = await Visits(db).find(
        {
            "tip_pence": {"$gt": 0},
            "tip_charge": None,
            "rating_id": {"$ne": None},
            "updated_at": {"$lt": utcnow() - TIP_START_AFTER},
        },
        limit=50,
    )
    for v in stale:
        try:
            await charging.charge_visit(db, s, gateway, v.id, purpose="tip")
            n += 1
        except HTTPException:  # e.g. charge_in_progress: the original request got there first
            continue
    return n


# ------------------------------------------------------------------------------- problems


def _title(description: str) -> str:
    first = description.strip().split("\n")[0]
    for stop in (". ", "! ", "? "):
        if stop in first:
            first = first.split(stop)[0]
    first = first.rstrip(".!? ")
    return first if len(first) <= 60 else first[:57].rstrip() + "…"


async def report_problem(db: Db, s: Settings, visit: Visit, customer: Customer, user: User, body: ProblemIn) -> Dispute:
    if visit.status != "finished" or visit.finished_at is None:
        fail(status.HTTP_409_CONFLICT, "not_finished", "You can report a problem once the visit is done.")
    if utcnow() - visit.finished_at > REPORT_WINDOW:
        fail(
            status.HTTP_409_CONFLICT,
            "too_late",
            "Problems need reporting within 48 hours of the visit. Message your provider about it instead.",
        )
    if visit.dispute_id:
        fail(status.HTTP_409_CONFLICT, "already_reported", "You've already told us about this visit.")
    photos = list(dict.fromkeys(body.photos))
    if photos and len(await Files(db).find({"_id": {"$in": photos}, "owner_user_id": user.id})) != len(photos):
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_photo", "One of those photos didn't upload. Try again.")
    cat = await _category(db, visit.category_id)
    provider, pu = await _provider_user(db, visit.provider_id)
    who = wording.first_name(provider.name)
    description = body.description.strip()
    day = wording.day_text(visit.local_date)

    async def open_dispute(session: DbSession) -> Dispute:
        now = utcnow()
        dispute = Dispute(
            ref=await next_ref(db, "dispute", session=session),
            visit_id=visit.id,
            booking_id=visit.booking_id,
            customer_id=customer.id,
            provider_id=provider.id,
            category_id=cat.id,
            title=_title(description),
            description=description,
            photos=photos,
            amount_pence=visit.price_pence,
            stage=0,
            status_text=f"Waiting for {who}'s reply",
            events=[DisputeEvent(at=now, by_user_id=user.id, kind="opened", text=description)],
        )
        if (
            await Visits(db).update(
                visit.id, {"dispute_id": dispute.id}, extra_filter={"dispute_id": None}, session=session
            )
            is None
        ):
            fail(status.HTTP_409_CONFLICT, "already_reported", "You've already told us about this visit.")
        thread = MessageThread(
            kind="dispute",
            dispute_id=dispute.id,
            participants=[
                Participant(user_id=user.id, role="customer", name=customer.name),
                Participant(user_id=provider.user_id, role="provider", name=pu.name if pu else provider.name),
            ],
        )
        await MessageThreads(db).insert(thread, session=session)
        dispute.thread_id = thread.id
        await Disputes(db).insert(dispute, session=session)
        await Messages(db).post(thread.id, user.id, "customer", description, photos, session=session)
        related = Related(
            dispute_id=dispute.id,
            visit_id=visit.id,
            booking_id=visit.booking_id,
            customer_id=customer.id,
            provider_id=provider.id,
            thread_id=thread.id,
        )
        if user.phone:
            await notify(
                db,
                "problem_reported",
                to=recipient_for(user),
                settings=s,
                related=related,
                idempotency_key=f"dispute:{dispute.id}:problem_reported",
                data={"provider": provider.short},
                session=session,
            )
        if pu and pu.phone:
            await notify(
                db,
                "dispute_opened",
                to=recipient_for(pu),
                settings=s,
                related=related,
                idempotency_key=f"dispute:{dispute.id}:dispute_opened",
                data={
                    "customer": wording.first_name(customer.name) or "Your customer",
                    "category": wording.lower_name(cat),
                    "date": day,
                    "summary": dispute.title,
                    "link": link("/p", s),
                },
                session=session,
            )
        return dispute

    return await transaction(db, open_dispute)


# ------------------------------------------------------------------------------- plans


def _summary(parts: list[str]) -> str:
    return "; ".join(parts)


async def update_plan(
    db: Db, s: Settings, series: Series, booking: Booking, customer: Customer, user: User, body: PlanUpdate
) -> Series:
    """Pauses and cover apply at once. A change of frequency is a request the provider accepts
    (A10: app.customer.plan_changes), applied by apply_frequency_change."""
    if series.status == "cancelled":
        fail(status.HTTP_409_CONFLICT, "plan_cancelled", "This plan is cancelled.")
    cat = await _category(db, series.category_id)
    provider, _ = await _provider_user(db, series.provider_id)
    fields = body.model_dump(exclude_unset=True)
    today = london_today()
    changes: list[str] = []
    set_: dict = {}

    if "pause_winter" in fields and fields["pause_winter"] is not None:
        if cat.group != "outside" and fields["pause_winter"]:
            fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_outside", "The winter pause is for outside jobs.")
        if fields["pause_winter"] != series.pause.winter:
            set_["pause.winter"] = fields["pause_winter"]
            changes.append(
                "paused over winter (no visits November to February)"
                if fields["pause_winter"]
                else "visits carry on over winter"
            )
    if "away_from" in fields or "away_to" in fields:
        a, b = fields.get("away_from"), fields.get("away_to")
        if (a is None) != (b is None):
            fail(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "away_dates", "Choose the day you leave and the day you're back."
            )
        if a and b:
            if a > b or b < today or b > today + timedelta(days=365):
                fail(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "away_dates",
                    "Choose dates from today, within the next year.",
                )
            changes.append(f"paused while you're away, {wording.day_text(a)} to {wording.day_text(b)}")
        elif series.pause.away_from:
            changes.append("away dates cleared")
        set_["pause.away_from"] = a.isoformat() if a else None
        set_["pause.away_to"] = b.isoformat() if b else None
    if (
        "cover_when_away" in fields
        and fields["cover_when_away"] is not None
        and fields["cover_when_away"] != series.cover_when_away
    ):
        set_["cover_when_away"] = fields["cover_when_away"]
        who = wording.first_name(provider.name)
        changes.append(f"cover when {who}'s away {'on' if fields['cover_when_away'] else 'off'}")
    if not set_:
        return series

    async def apply(session: DbSession) -> Series:
        now = utcnow()  # visits still to come, including later today; ones under way are left alone
        updated = await SeriesRepo(db).update(
            series.id, set_, extra_filter={"status": {"$ne": "cancelled"}}, session=session
        )
        if updated is None:
            fail(status.HTTP_409_CONFLICT, "plan_cancelled", "This plan is cancelled.")
        future = await Visits(db).find(
            {
                "series_id": series.id,
                "scheduled_start": {"$gt": now},
                "status": {"$in": ["scheduled", "skipped", "cancelled"]},
            },
            sort=[("local_date", 1)],
            session=session,
        )
        nxt = next((v for v in future if v.status == "scheduled"), None)
        # Pauses: skip the visits that now fall in one; bring back those a removed pause skipped.
        for v in future:
            if v.status == "scheduled" and schedule.paused_on(updated, v.local_date) and v.cover.state == "none":
                reason = "winter" if updated.pause.winter and v.local_date.month in WINTER else "away"
                await Visits(db).update(
                    v.id,
                    {"status": "skipped", "skipped_reason": reason},
                    extra_filter={"status": "scheduled"},
                    session=session,
                )
            elif v.status == "skipped" and v.skipped_reason in PAUSES and not schedule.paused_on(updated, v.local_date):
                await Visits(db).update(
                    v.id,
                    {"status": "scheduled", "skipped_reason": None},
                    extra_filter={"status": "skipped"},
                    session=session,
                )
        await schedule.ensure_horizon(
            db, updated, provider, from_day=nxt.local_date if nxt else today, source=booking.source, session=session
        )
        summary = _summary(changes)
        await system_note(db, booking.thread_id, f"{customer.name} changed the plan: {summary}.", session)
        if user.phone:
            await notify(
                db,
                "plan_changed",
                to=recipient_for(user),
                settings=s,
                related=Related(series_id=series.id, booking_id=booking.id, customer_id=customer.id),
                data={"category": wording.lower_name(cat), "provider": provider.short, "summary": summary},
                session=session,
            )
        return updated

    return await transaction(db, apply)


async def apply_frequency_change(
    db: Db,
    series: Series,
    booking: Booking,
    provider: Provider,
    frequency: str,
    price_pence: int,
    *,
    session: DbSession,
) -> tuple[Series, Visit | None]:
    """An accepted change of frequency (A10), inside the caller's transaction: the plan and booking
    take the new frequency and price; the next visit stays (at the new price unless it's the first
    visit, whose price was agreed separately) and later visits that aren't on the new dates are
    cancelled, including ones a pause skipped, so ending the pause can't bring the old dates back;
    then the new dates are filled in. Visits under way, done or covered are left alone. Returns the
    plan and its next visit."""
    now = utcnow()
    today = london_today()
    future = await Visits(db).find(
        {
            "series_id": series.id,
            "scheduled_start": {"$gt": now},
            "status": {"$in": ["scheduled", "skipped", "cancelled"]},
        },
        sort=[("local_date", 1)],
        session=session,
    )
    nxt = next((v for v in future if v.status == "scheduled"), None)
    paused = next((v for v in future if v.status == "skipped" and v.skipped_reason in PAUSES), None)
    first = nxt or paused
    anchor = first.local_date if first else today + timedelta(days=1)
    updated = await SeriesRepo(db).update(
        series.id,
        {
            "frequency": frequency,
            "anchor_date": anchor.isoformat(),
            "days": schedule.series_days(frequency, anchor),
            "price_pence": price_pence,
        },
        extra_filter={"status": {"$ne": "cancelled"}, "frequency": series.frequency, "price_pence": series.price_pence},
        session=session,
    )
    if updated is None:
        fail(status.HTTP_409_CONFLICT, "plan_cancelled", "This plan is cancelled.")
    # The new dates mustn't run into the provider's other visits or plans. Writing the provider
    # makes a booking or another change for them committing meanwhile conflict with this one, so
    # the re-run sees it.
    await Providers(db).update(provider.id, {}, session=session)
    if (clash := await schedule.first_clash(db, updated, anchor, session=session)) is not None:
        fail(
            status.HTTP_409_CONFLICT,
            "time_taken",
            f"That would clash with another visit at {series.start_time} on {wording.day_text(clash)}, so the plan "
            f"can't change to {wording.FREQUENCY_WORDS.get(frequency, frequency)} at that time. Message each other to "
            "find another time.",
        )
    await Bookings(db).update(booking.id, {"frequency": frequency, "price_pence": price_pence}, session=session)
    on_dates = set(
        schedule.occurrences(updated.model_copy(update={"pause": Pause()}), anchor, today + timedelta(days=500))
    )
    on_dates.add(anchor)
    for v in future:
        if v.cover.state != "none":
            continue
        if v.local_date not in on_dates:
            if v.status == "scheduled" or (v.status == "skipped" and v.skipped_reason in PAUSES):
                await Visits(db).update(
                    v.id,
                    {"status": "cancelled", "skipped_reason": "plan_change"},
                    extra_filter={"status": v.status},
                    session=session,
                )
        elif not v.is_first and v.price_pence != price_pence:
            await Visits(db).update(v.id, {"price_pence": price_pence}, session=session)
    await schedule.ensure_horizon(
        db, updated, provider, from_day=nxt.local_date if nxt else today, source=booking.source, session=session
    )
    nxt = await Visits(db).find_one(
        {"series_id": series.id, "status": "scheduled", "scheduled_start": {"$gt": now}},
        sort=[("scheduled_start", 1)],
        session=session,
    )
    return updated, nxt


async def cancel_plan(db: Db, s: Settings, series: Series, booking: Booking, customer: Customer, user: User) -> Series:
    if series.status == "cancelled":
        return series
    cat = await _category(db, series.category_id)
    provider, _ = await _provider_user(db, series.provider_id)

    async def cancel(session: DbSession) -> Series:
        now = utcnow()
        updated = await SeriesRepo(db).update(
            series.id, {"status": "cancelled"}, extra_filter={"status": {"$ne": "cancelled"}}, session=session
        )
        if updated is None:
            fail(status.HTTP_409_CONFLICT, "plan_cancelled", "This plan is already cancelled.")
        await Bookings(db).update(booking.id, {"status": "cancelled", "cancelled_at": now}, session=session)
        await PlanChanges(db).coll.update_many(  # a change still waiting can't be accepted now (A10)
            {"series_id": series.id, "status": "pending"},
            {"$set": {"status": "withdrawn", "decided_at": now, "updated_at": now}},
            session=PlanChanges.s(session),
        )
        await Visits(db).coll.update_many(
            {"series_id": series.id, "status": "scheduled", "scheduled_start": {"$gt": now}},
            {"$set": {"status": "cancelled", "skipped_reason": "plan_cancelled", "updated_at": now}},
            session=Visits.s(session),
        )
        await system_note(
            db, booking.thread_id, f"{customer.name} cancelled the plan. There are no more visits.", session
        )
        if user.phone:
            await notify(
                db,
                "plan_cancelled",
                to=recipient_for(user),
                settings=s,
                related=Related(series_id=series.id, booking_id=booking.id, customer_id=customer.id),
                idempotency_key=f"series:{series.id}:plan_cancelled",
                data={"category": wording.lower_name(cat), "provider": provider.short},
                session=session,
            )
        return updated

    return await transaction(db, cancel)


# ------------------------------------------------------------------------------- book again


async def rebook(db: Db, s: Settings, booking: Booking, customer: Customer, user: User, body: RebookIn) -> JobRequest:
    """ "Book Dave again": a request offered to that provider only, at the price agreed last time."""
    if booking.recurring and booking.status == "active":
        fail(status.HTTP_409_CONFLICT, "has_plan", "You already have a regular plan with them.")
    cat = await Categories(db).get(booking.category_id)
    if cat is None or cat.status != "live":
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_bookable", "That job isn't something we book any more.")
    if customer.payment is None or customer.payment.card is None:
        fail(status.HTTP_409_CONFLICT, "card_needed", "Add a card first. Nothing is charged until the work is done.")
    original = await JobRequests(db).get(booking.request_id) if booking.request_id else None
    version = booking.pricing_version_id or (await live_version(db)).id
    now = utcnow()
    lat, lng = approximate(booking.address.lat, booking.address.lng)
    when = body.when or When(days=booking.days, time=booking.when)
    draft = JobRequest(
        ref="pending",
        customer_id=customer.id,
        category_id=cat.id,
        quote_id=original.quote_id if original else "",
        pricing_version_id=version,
        answers={**booking.answers, **({"frequency": "oneoff"} if "frequency" in booking.answers else {})},
        measure=original.measure if original else None,
        address=booking.address,
        approx=GeoPoint(lat=lat, lng=lng),
        notes=body.note.strip() or booking.notes,
        when=when,
        recurring=False,
        frequency="oneoff" if "frequency" in booking.answers else None,
        guide_pence=booking.price_pence,
        first_pence=None,
        mins=booking.est_mins,
        unit="one-off" if booking.recurring else booking.unit,
        direct_provider_id=booking.provider_id,
        created_at=now,
        updated_at=now,
    )
    targets, hints = await request_service.targets_for(db, draft, cat)

    async def create(session: DbSession) -> JobRequest:
        req = draft.model_copy(update={"ref": await next_ref(db, "request", session=session)})
        req.broadcast = Broadcast(at=now, provider_ids=[t.provider.id for t in targets])
        req.events = [
            RequestEvent(at=now, kind="created", by_user_id=user.id, text=f"Book again: {booking.ref}"),
            RequestEvent(at=now, kind="broadcast", count=len(targets)),
        ]
        await JobRequests(db).insert(req, session=session)
        await request_service.send_job_alerts(db, s, req, cat, targets, hints, session=session)
        if user.phone:
            template = "request_sent" if targets else "request_no_providers"
            await notify(
                db,
                template,
                to=recipient_for(user),
                settings=s,
                related=Related(request_id=req.id, customer_id=customer.id),
                idempotency_key=f"request:{req.id}:{template}",
                data={"category": wording.lower_name(cat), "district": req.address.district},
                session=session,
            )
        return req

    return await transaction(db, create)
