"""A raised guide price needs the customer's approval (ruling A12).

The admin's "Raise guide" (L3, app.admin.overview.raise_guide) calls
app.services.guide_raises.propose inside its own transaction: the open request gets a pending
price change (the first visit scaled by the same ratio, marketplace.scaled_first_price) and the
customer is texted. The guide itself doesn't move; a booking made meanwhile withdraws it (A16).
On "Finding someone local" the customer approves it, and only then does the guide change and
the job alerts go out again to the providers eligible now, at the new price; or they decline it
and the original guide stands.
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
from app.repos.job_requests import JobRequests
from app.services.audit import audit


def _pending(req: JobRequest, change_id: str) -> PriceChange:
    """The proposal the customer saw (by its id), still waiting on the still-open request."""
    if req.status != "open":
        fail(status.HTTP_409_CONFLICT, "not_open", "This request isn't open any more.")
    if req.price_change is None or req.price_change.status != "pending":
        fail(status.HTTP_409_CONFLICT, "no_price_change", "There's no new price waiting for you on this request.")
    if req.price_change.id != change_id:
        fail(status.HTTP_409_CONFLICT, "price_change_changed", "The suggested price has changed. Have another look.")
    return req.price_change


def _changed() -> None:
    fail(status.HTTP_409_CONFLICT, "request_changed", "This request has just changed. Have another look.")


async def approve(db: Db, s: Settings, req: JobRequest, user: User, change_id: str) -> JobRequest:
    """The customer approves the raise: the guide (and first visit) change, and the request is
    sent again, at the new price, to the providers eligible now. One transaction."""
    change = _pending(req, change_id)
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
                "price_change.id": change.id,
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


async def decline(db: Db, s: Settings, req: JobRequest, user: User, change_id: str) -> JobRequest:
    """The customer keeps the original guide."""
    change = _pending(req, change_id)

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
                "price_change.id": change.id,
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
