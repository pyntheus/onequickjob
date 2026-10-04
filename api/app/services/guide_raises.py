"""Proposing a higher guide price for an open request (ruling A12). Shared: the admin's "Raise
guide" (L3) calls it inside its own transaction; the customer answers on "Finding someone local"
(L1, app.customer.price_changes); a booking made meanwhile withdraws it (marketplace, A16)."""

from fastapi import status

from app.core.config import Settings
from app.core.db import Db, DbSession
from app.core.errors import fail
from app.core.timeutil import utcnow
from app.models.common import Actor, Related
from app.models.job_requests import JobRequest, PriceChange, RequestEvent
from app.repos.categories import Categories
from app.repos.customers import Customers
from app.repos.job_requests import JobRequests
from app.repos.users import Users
from app.services import wording
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
