"""Time off: a date range, and for each visit it touches, local cover, a helper, or skip.

Booking it is one transaction: the time off, every visit's change, the cover requests with
their alerts, and every message, all or nothing. Cover goes through the normal offer flow
(app.provider.cover); a cover that nobody takes by the day before is skipped and the
customer told. After the dates, the plan carries on with the provider as before.
"""

from datetime import date, timedelta

from fastapi import status

from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.core.timeutil import london_today, utcnow
from app.models.common import Related
from app.models.job_requests import RequestEvent
from app.models.provider_ops import Arrangement, TimeOff
from app.models.providers import Provider
from app.models.visits import Performer, Visit
from app.provider.common import categories, short_name
from app.provider.cover import check_coverable, cover_allowed, offer_cover, tell_customer_skipped
from app.provider.helpers import ready_helper
from app.provider.round import tell_helper_coming
from app.provider.schemas import AffectedVisit, ArrangementOut, TimeOffIn, TimeOffOut, TimeOffRange
from app.repos.bookings import Bookings
from app.repos.customers import Customers
from app.repos.job_requests import JobRequests
from app.repos.offers import Offers
from app.repos.time_off import TimeOffRepo
from app.repos.users import Users
from app.repos.visits import Visits
from app.services import wording
from app.services.notify import notify, recipient_for

MAX_DAYS = 62


def _check_range(r: TimeOffRange, today: date) -> None:
    if r.to_date < r.from_date:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_range", "The day you're back must be after the day you go.")
    if r.from_date <= today:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_soon", "Time off has to start tomorrow or later.")
    if (r.to_date - r.from_date).days >= MAX_DAYS:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_long", "Book up to two months at a time.")


async def _affected(db: Db, provider: Provider, r: TimeOffRange, *, session: DbSession | None = None) -> list[Visit]:
    """The provider's own scheduled visits in the range that aren't already out for cover."""
    return await Visits(db).find(
        {
            "provider_id": provider.id,
            "status": "scheduled",
            "performer.kind": {"$ne": "cover"},
            "cover.state": "none",
            "local_date": {"$gte": r.from_date.isoformat(), "$lte": r.to_date.isoformat()},
        },
        sort=[("scheduled_start", 1)],
        session=session,
    )


async def preview(db: Db, provider: Provider, r: TimeOffRange) -> list[AffectedVisit]:
    _check_range(r, london_today())
    visits = await _affected(db, provider, r)
    cats = await categories(db)
    out = []
    for v in visits:
        b = await Bookings(db).get(v.booking_id)
        c = await Customers(db).get(v.customer_id)
        out.append(
            AffectedVisit(
                visit_id=v.id,
                customer_name=short_name(c.name if c else ""),
                category_name=cats[v.category_id].name,
                local_date=v.local_date,
                area=b.address.area if b else "",
                cover_allowed=await cover_allowed(db, v),
                start_time=wording.time_text(v.scheduled_start),
                with_helper=v.performer.name if v.performer.kind == "helper" else None,
            )
        )
    return out


async def _overlaps(db: Db, provider_id: str, r: TimeOffRange, *, session: DbSession | None = None) -> bool:
    return (
        await TimeOffRepo(db).count(
            {
                "provider_id": provider_id,
                "status": {"$in": ["planned", "active"]},
                "from_date": {"$lte": r.to_date.isoformat()},
                "to_date": {"$gte": r.from_date.isoformat()},
            },
            session=session,
        )
        > 0
    )


def _summary(lines: list[str]) -> str:
    return " ".join(lines) if lines else "Nothing was booked in for those days."


async def book(db: Db, s: Settings, provider: Provider, body: TimeOffIn) -> TimeOffOut:
    today = london_today()
    r = TimeOffRange(from_date=body.from_date, to_date=body.to_date)
    _check_range(r, today)
    if await _overlaps(db, provider.id, r):
        fail(status.HTTP_409_CONFLICT, "overlaps", "You've already got time off booked over some of those days.")
    affected = {v.id: v for v in await _affected(db, provider, r)}
    chosen = {a.visit_id: a for a in body.arrangements}
    if set(chosen) - set(affected):
        fail(status.HTTP_409_CONFLICT, "visits_changed", "Your visits have changed. Have another look.")
    if set(affected) - set(chosen):
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "choose_each", "Choose what happens to each visit.")
    for a in chosen.values():
        v = affected[a.visit_id]
        if a.action == "cover":
            check_coverable(v, provider, today)
            if not await cover_allowed(db, v):
                fail(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "cover_not_wanted",
                    "One of these customers would rather not have cover. Send a helper or skip that visit.",
                )
        elif a.action == "helper":
            ready_helper(provider, a.helper_user_id or "")
    cats = await categories(db)
    pu = await Users(db).get(provider.user_id)

    async def arrange(session: DbSession) -> TimeOff:
        if await _overlaps(db, provider.id, r, session=session):
            fail(status.HTTP_409_CONFLICT, "overlaps", "You've already got time off booked over some of those days.")
        off = TimeOff(provider_id=provider.id, from_date=r.from_date, to_date=r.to_date, status="planned")
        lines: list[str] = []
        for visit_id, a in chosen.items():
            v = affected[visit_id]
            customer = await Customers(db).get(v.customer_id, session=session)
            cu = await Users(db).get(customer.user_id, session=session) if customer else None
            who = short_name(customer.name) if customer else "A customer"
            day = f"{v.local_date:%a} {v.local_date.day} {v.local_date:%b}"
            if a.action == "skip":
                done = await Visits(db).update(
                    v.id,
                    {"status": "skipped", "skipped_reason": "Provider's time off"},
                    extra_filter={"status": "scheduled", "provider_id": provider.id, "cover.state": "none"},
                    session=session,
                )
                if done is None:
                    fail(status.HTTP_409_CONFLICT, "visits_changed", "Your visits have changed. Have another look.")
                await tell_customer_skipped(db, s, done, cats[v.category_id].name, session=session)
                off.arrangements.append(Arrangement(visit_id=v.id, action="skip", state="arranged"))
                lines.append(f"{who}'s visit on {day} is skipped.")
            elif a.action == "helper":
                helper = ready_helper(provider, a.helper_user_id or "")
                performer = Performer(
                    kind="helper", provider_id=provider.id, user_id=helper.user_id, name=short_name(helper.name)
                )
                done = await Visits(db).update(
                    v.id,
                    {"performer": performer.model_dump()},
                    extra_filter={"status": "scheduled", "provider_id": provider.id, "cover.state": "none"},
                    session=session,
                )
                if done is None:
                    fail(status.HTTP_409_CONFLICT, "visits_changed", "Your visits have changed. Have another look.")
                await tell_helper_coming(db, s, provider.short, done, helper.name, cu, session=session)
                off.arrangements.append(
                    Arrangement(visit_id=v.id, action="helper", helper_user_id=helper.user_id, state="arranged")
                )
                lines.append(f"{helper.name.split(' ')[0]} is doing {who}'s on {day}.")
            else:
                booking = await Bookings(db).get(v.booking_id, session=session)
                assert booking is not None
                req = await offer_cover(db, s, provider, v, booking, session=session)
                off.arrangements.append(
                    Arrangement(visit_id=v.id, action="cover", cover_request_id=req.id, state="planned")
                )
                lines.append(f"{who}'s on {day} has gone out for local cover.")
        await TimeOffRepo(db).insert(off, session=session)
        if pu and pu.phone:
            await notify(
                db,
                "time_off_arranged",
                to=recipient_for(pu),
                data={
                    "from_date": wording.day_text(r.from_date),
                    "to_date": wording.day_text(r.to_date),
                    "summary": _summary(lines),
                },
                related=Related(provider_id=provider.id, time_off_id=off.id),
                settings=s,
                session=session,
            )
        return off

    off = await transaction(db, arrange)
    return await time_off_out(db, off)


async def _arrangement_detail(db: Db, a: Arrangement) -> tuple[str, str]:
    """(state, what it says) for one arrangement, read from the visit as it is now."""
    v = await Visits(db).get(a.visit_id)
    if v is None:
        return a.state, "This visit no longer exists."
    day = wording.day_text(v.local_date)
    if a.action == "skip":
        return a.state, f"Skipped on {day}. The customer's been told."
    if a.action == "helper":
        return (
            a.state,
            f"{v.performer.name} is doing it on {day}." if v.performer.kind == "helper" else f"Back with you on {day}.",
        )
    if v.cover.state == "covered" and v.performer.kind == "cover":
        return "arranged", f"{v.performer.name} is covering it on {day}."
    if v.status == "skipped":
        return "failed", f"Nobody was free on {day}, so it's skipped. The customer's been told."
    if v.cover.state == "offered":
        return "planned", f"Out for local cover on {day}."
    return a.state, f"Back with you on {day}."


async def time_off_out(db: Db, off: TimeOff) -> TimeOffOut:
    rows = []
    for a in off.arrangements:
        state, detail = await _arrangement_detail(db, a)
        rows.append(ArrangementOut(visit_id=a.visit_id, action=a.action, state=state, detail=detail))  # type: ignore[arg-type]
    return TimeOffOut(
        id=off.id, from_date=off.from_date, to_date=off.to_date, status=_status_now(off), arrangements=rows
    )


def _status_now(off: TimeOff, today: date | None = None) -> str:
    if off.status == "cancelled":
        return "cancelled"
    today = today or london_today()
    if today > off.to_date:
        return "done"
    if today >= off.from_date:
        return "active"
    return "planned"


async def list_time_off(db: Db, provider: Provider) -> list[TimeOffOut]:
    since = (london_today() - timedelta(days=30)).isoformat()
    rows = await TimeOffRepo(db).find({"provider_id": provider.id, "to_date": {"$gte": since}}, sort=[("from_date", 1)])
    return [await time_off_out(db, off) for off in rows]


async def cancel(db: Db, s: Settings, provider: Provider, time_off_id: str) -> None:
    """Cancel time off that hasn't started: cover still being offered is withdrawn and the
    visit comes back to the provider. Skipped visits and helpers stay as arranged (the
    customers have been told)."""
    off = await TimeOffRepo(db).get(time_off_id)
    if off is None or off.provider_id != provider.id:
        not_found("That time off")
    if _status_now(off) != "planned" or off.status != "planned":
        fail(
            status.HTTP_409_CONFLICT,
            "already_started",
            "That time off has started or finished, so it can't be cancelled.",
        )

    async def undo(session: DbSession) -> None:
        done = await TimeOffRepo(db).update(
            off.id, {"status": "cancelled"}, extra_filter={"status": "planned"}, session=session
        )
        if done is None:
            fail(status.HTTP_409_CONFLICT, "already_changed", "That time off has just changed.")
        for a in off.arrangements:
            if a.action != "cover" or not a.cover_request_id:
                continue
            req = await JobRequests(db).update(
                a.cover_request_id,
                {"status": "cancelled"},
                push={
                    "events": RequestEvent(at=utcnow(), kind="cancelled", text="Time off cancelled").model_dump(
                        mode="python"
                    )
                },
                extra_filter={"status": "open"},
                session=session,
            )
            if req is None:
                continue  # someone took it: that visit stays covered
            await Offers(db).lapse_pending(req.id, session=session)
            await Visits(db).update(
                a.visit_id,
                {"cover": {"state": "none", "request_id": None, "original_provider_id": None}},
                extra_filter={"cover.request_id": req.id, "cover.state": "offered"},
                session=session,
            )

    await transaction(db, undo)


async def housekeeping(db: Db, s: Settings, today: date | None = None) -> None:
    """Keep time off's statuses and cover arrangements in step with what happened."""
    today = today or london_today()
    for off in await TimeOffRepo(db).find({"status": {"$in": ["planned", "active"]}}):
        changes: dict = {}
        now_status = _status_now(off, today)
        if now_status != off.status:
            changes["status"] = now_status
        arrangements = []
        for a in off.arrangements:
            state, _ = await _arrangement_detail(db, a)
            arrangements.append(a.model_copy(update={"state": state}))
        if [x.state for x in arrangements] != [x.state for x in off.arrangements]:
            changes["arrangements"] = [x.model_dump(mode="python") for x in arrangements]
        if changes:
            await TimeOffRepo(db).update(off.id, changes, extra_filter={"status": off.status})
