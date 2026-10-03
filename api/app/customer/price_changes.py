"""A raised guide price needs the customer's approval (ruling A12).

The admin's "Raise guide" (L3, app.admin.overview.raise_guide) calls propose() inside its own
transaction: the open request gets a pending price change (the first visit scaled by the same
ratio, marketplace.scaled_first_price) and the customer is texted. The guide itself doesn't
move. On "Finding someone local" the customer approves it, and only then does the guide
change and the job alerts go out again to the providers eligible now, at the new price; or
they decline it and the original guide stands.
"""

from fastapi import status

from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail
from app.core.timeutil import utcnow
from app.customer import requests as request_service
from app.models.common import Actor, Related
from app.models.job_requests import Broadcast, JobRequest, PriceChange, RequestEvent
from app.models.users import User
from app.repos.categories import Categories
from app.repos.customers import Customers
from app.repos.job_requests import JobRequests
from app.repos.users import Users
from app.services import wording
from app.services.audit import audit
from app.services.notify import link, notify, recipient_for


def _first_text(pence: int | None) -> str:
    return f" (first visit {wording.money(pence)})" if pence else ""


async def propose(
    db: Db,
    s: Settings,
    req: JobRequest,
    *,
    guide_pence: int,
    first_pence: int | None,
    percent: int | None,
    note: str,
    actor: Actor,
    session: DbSession,
) -> JobRequest:
    """Inside the caller's transaction: record the pending raise on the still-open request (as
    read: same guide, no other raise waiting) and text the customer. 409 otherwise."""
    now = utcnow()
    change = PriceChange(
        guide_pence=guide_pence,
        first_pence=first_pence,
        from_guide_pence=req.guide_pence,
        from_first_pence=req.first_pence,
        percent=percent,
        proposed_by=actor.user_id,
        proposed_at=now,
        note=note,
    )
    event = RequestEvent(
        at=now, kind="price_change_proposed", price_pence=guide_pence, by_user_id=actor.user_id, text=note or None
    )
    updated = await JobRequests(db).update(
        req.id,
        {"price_change": change.model_dump(mode="python")},
        extra_filter={"status": "open", "guide_pence": req.guide_pence, "price_change.status": {"$ne": "pending"}},
        push={"events": event.model_dump(mode="python")},
        session=session,
    )
    if updated is None:
        current = await JobRequests(db).get(req.id, session=session)
        if current and current.price_change and current.price_change.status == "pending":
            fail(
                status.HTTP_409_CONFLICT,
                "awaiting_customer",
                "The customer hasn't answered the last raise yet. Wait for them first.",
            )
        fail(status.HTTP_409_CONFLICT, "request_changed", "This request has just changed. Have another look.")
    customer = await Customers(db).get(req.customer_id, session=session)
    cu = await Users(db).get(customer.user_id, session=session) if customer else None
    cat = await Categories(db).get(req.category_id, session=session)
    if cu and cu.phone and cat:
        await notify(
            db,
            "guide_raise_proposed",
            to=recipient_for(cu),
            settings=s,
            related=Related(request_id=req.id, customer_id=req.customer_id),
            idempotency_key=f"request:{req.id}:guide_raise_proposed:{now.isoformat()}",
            data={
                "category": wording.lower_name(cat),
                "price": wording.money(guide_pence),
                "first_text": _first_text(first_pence),
                "current": wording.money(req.guide_pence),
                "link": link(f"/requests/{req.ref}", s),
            },
            session=session,
        )
    return updated


def _pending(req: JobRequest) -> PriceChange:
    if req.status != "open":
        fail(status.HTTP_409_CONFLICT, "not_open", "This request isn't open any more.")
    if req.price_change is None or req.price_change.status != "pending":
        fail(status.HTTP_409_CONFLICT, "no_price_change", "There's no new price waiting for you on this request.")
    return req.price_change


def _changed() -> None:
    fail(status.HTTP_409_CONFLICT, "request_changed", "This request has just changed. Have another look.")


async def approve(db: Db, s: Settings, req: JobRequest, user: User) -> JobRequest:
    """The customer approves the raise: the guide (and first visit) change, and the request is
    sent again, at the new price, to the providers eligible now. One transaction."""
    change = _pending(req)
    cat = await Categories(db).get(req.category_id)
    assert cat is not None, req.category_id
    raised = req.model_copy(update={"guide_pence": change.guide_pence, "first_pence": change.first_pence})
    targets, hints = await request_service.targets_for(db, raised, cat)

    async def apply(session: DbSession) -> JobRequest:
        now = utcnow()
        event = RequestEvent(
            at=now,
            kind="guide_raised",
            price_pence=change.guide_pence,
            count=len(targets),
            by_user_id=user.id,
            text="Approved by the customer",
        )
        updated = await JobRequests(db).update(
            req.id,
            {
                "guide_pence": change.guide_pence,
                "first_pence": change.first_pence,
                "price_change.status": "approved",
                "price_change.decided_at": now,
                "broadcast": Broadcast(at=now, provider_ids=[t.provider.id for t in targets]).model_dump(mode="python"),
            },
            extra_filter={
                "status": "open",
                "guide_pence": change.from_guide_pence,
                "price_change.status": "pending",
                "price_change.proposed_at": change.proposed_at,
            },
            push={"events": event.model_dump(mode="python")},
            session=session,
        )
        if updated is None:
            _changed()
        await request_service.send_job_alerts(
            db, s, updated, cat, targets, hints, session=session, round_key=f":guide{change.guide_pence}"
        )
        await audit(
            db,
            Actor(kind="user", user_id=user.id, role="customer", name=user.name),
            "request.guide_raise_approved",
            Related(request_id=req.id, customer_id=req.customer_id),
            before={"guide_pence": change.from_guide_pence, "first_pence": change.from_first_pence},
            after={"guide_pence": change.guide_pence, "first_pence": change.first_pence, "alerted": len(targets)},
            session=session,
        )
        return updated

    return await transaction(db, apply)


async def decline(db: Db, s: Settings, req: JobRequest, user: User) -> JobRequest:
    """The customer keeps the original guide."""
    change = _pending(req)

    async def apply(session: DbSession) -> JobRequest:
        now = utcnow()
        event = RequestEvent(
            at=now, kind="price_change_declined", price_pence=change.from_guide_pence, by_user_id=user.id
        )
        updated = await JobRequests(db).update(
            req.id,
            {"price_change.status": "declined", "price_change.decided_at": now},
            extra_filter={
                "status": "open",
                "price_change.status": "pending",
                "price_change.proposed_at": change.proposed_at,
            },
            push={"events": event.model_dump(mode="python")},
            session=session,
        )
        if updated is None:
            _changed()
        await audit(
            db,
            Actor(kind="user", user_id=user.id, role="customer", name=user.name),
            "request.guide_raise_declined",
            Related(request_id=req.id, customer_id=req.customer_id),
            before={"proposed_guide_pence": change.guide_pence},
            after={"guide_pence": change.from_guide_pence},
            session=session,
        )
        return updated

    return await transaction(db, apply)
