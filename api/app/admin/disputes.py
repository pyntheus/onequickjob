"""Disputes: we mediate; we don't guarantee. The agreement is between customer and provider;
the admin messages both, proposes a fix (a free return visit, or a partial refund paid by the
provider) and closes the dispute, refunding through the gateway (app.payments.refunds) first
when the outcome is a refund, then closing in one transaction with the messages."""

from typing import Literal

from fastapi import HTTPException, status

from app.adapters.payments.base import PaymentGateway
from app.admin.schemas import CloseIn, DisputeMessageIn, DisputeView, ProposeIn
from app.admin.views import ago_text, money, short_name
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.core.timeutil import utcnow
from app.models.common import Actor, Related
from app.models.disputes import DISPUTE_STAGES, Dispute, DisputeClosing, DisputeEvent, Resolution
from app.models.messages import MessageThread, Participant
from app.models.payments import RefundIntent
from app.models.users import User
from app.payments import refunds
from app.repos import Bookings, Customers, Disputes, Messages, MessageThreads, Providers, Users, Visits
from app.repos.payments import PaymentRefunds
from app.services import wording
from app.services.audit import SYSTEM, audit
from app.services.notify import link, notify, recipient_for

type Party = Literal["customer", "provider"]


async def _get(db: Db, ref: str, session: DbSession | None = None) -> Dispute:
    d = await Disputes(db).by_ref(ref, session=session)
    if d is None:
        not_found("That dispute")
    return d


async def view(db: Db, d: Dispute) -> DisputeView:
    customer = await Customers(db).get(d.customer_id)
    provider = await Providers(db).get(d.provider_id)
    booking = await Bookings(db).get(d.booking_id)
    visit = await Visits(db).get(d.visit_id)
    charge = visit.charge if visit else None
    unsettled = await PaymentRefunds(db).unsettled_pence(d.visit_id) if visit else 0
    opened = d.events[0].at if d.events else d.created_at
    return DisputeView(
        id=d.id,
        ref=d.ref,
        title=d.title,
        category_id=d.category_id,
        area=booking.address.area if booking else "",
        customer_name=short_name(customer.name) if customer else "The customer",
        provider_short=provider.short if provider else "The provider",
        opened_at=opened,
        opened_text=ago_text(opened),
        stage=d.stage,
        stages=list(DISPUTE_STAGES),
        status_text=d.status_text,
        amount_pence=d.amount_pence,
        proposed=d.proposed,
        resolution=d.resolution,
        events=d.events,
        thread_id=d.thread_id,
        visit_id=d.visit_id,
        provider_first=wording.first_name(provider.name) if provider else "the provider",
        charge_status=charge.status if charge else "none",
        charged_pence=charge.amount_pence if charge and charge.status != "none" else 0,
        refunded_pence=charge.refunded_pence if charge else 0,
        refundable_pence=refunds.refundable_left(visit, unsettled)
        if visit and charge and charge.status in refunds.REFUNDABLE
        else 0,
        closing_outcome=d.closing.outcome if d.closing else None,
        closing_amount_pence=d.closing.amount_pence if d.closing else None,
    )


async def listing(db: Db) -> list[DisputeView]:
    ds = await Disputes(db).find({}, sort=[("created_at", -1)])
    ds.sort(key=lambda d: d.stage == 3)  # open ones first, newest first within each
    return [await view(db, d) for d in ds]


async def one(db: Db, ref: str) -> DisputeView:
    return await view(db, await _get(db, ref))


async def _parties(db: Db, d: Dispute, session: DbSession) -> dict[Party, tuple[User | None, str]]:
    customer = await Customers(db).get(d.customer_id, session=session)
    provider = await Providers(db).get(d.provider_id, session=session)
    users = Users(db)
    return {
        "customer": (await users.get(customer.user_id, session=session) if customer else None, "/account"),
        "provider": (await users.get(provider.user_id, session=session) if provider else None, "/p"),
    }


async def _thread(db: Db, d: Dispute, admin: Actor, session: DbSession) -> str:
    """The dispute's thread (L1 opens it with the dispute); made here if it's missing."""
    if d.thread_id:
        return d.thread_id
    parties = await _parties(db, d, session)
    people = [Participant(user_id=u.id, role=role, name=u.name) for role, (u, _) in parties.items() if u]
    people.append(Participant(user_id=admin.user_id or "", role="admin", name=admin.name or "OneQuickJob"))
    thread = MessageThread(kind="dispute", booking_id=d.booking_id, dispute_id=d.id, participants=people)
    await MessageThreads(db).insert(thread, session=session)
    await Disputes(db).update(d.id, {"thread_id": thread.id}, session=session)
    return thread.id


async def _tell(
    db: Db,
    s: Settings,
    d: Dispute,
    template: str,
    data: dict,
    to: list[Party],
    session: DbSession,
    key: str | None = None,
) -> None:
    for party, (user, path) in (await _parties(db, d, session)).items():
        if party in to and user and user.phone:
            await notify(
                db,
                template,
                to=recipient_for(user),
                data={"title": d.title.lower() if template != "dispute_closed" else d.title, **data}
                | ({"link": link(path, s)} if template != "dispute_closed" else {}),
                related=Related(dispute_id=d.id, visit_id=d.visit_id, booking_id=d.booking_id, user_id=user.id),
                settings=s,
                idempotency_key=f"{key}:{party}" if key else None,
                session=session,
            )


async def message(db: Db, s: Settings, ref: str, body: DisputeMessageIn, admin: Actor) -> DisputeView:
    to: list[Party] = ["customer", "provider"] if body.to == "both" else [body.to]

    async def apply(session: DbSession) -> Dispute:
        d = await _get(db, ref, session)
        if d.stage == 3:
            fail(status.HTTP_409_CONFLICT, "closed", "This dispute is closed.")
        thread_id = await _thread(db, d, admin, session)
        await Messages(db).post(thread_id, admin.user_id, "admin", body.body, session=session)
        event = DisputeEvent(at=utcnow(), by_user_id=admin.user_id, kind="message", text=body.body)
        updated = await Disputes(db).update(d.id, {}, push={"events": event.model_dump(mode="python")}, session=session)
        assert updated is not None
        preview = body.body if len(body.body) <= 80 else body.body[:79].rstrip() + "…"
        await _tell(db, s, updated, "dispute_message", {"preview": preview}, to, session)
        await audit(
            db,
            admin,
            "dispute.message",
            Related(dispute_id=d.id),
            after={"to": body.to},
            note=body.body,
            session=session,
        )
        return updated

    return await view(db, await transaction(db, apply))


def proposal_text(kind: str, amount_pence: int | None, provider_first: str) -> str:
    if kind == "return_visit":
        return f"{provider_first} comes back to put it right, free"
    return f"a {money(amount_pence or 0)} refund, paid by {provider_first}"


async def propose(db: Db, s: Settings, ref: str, body: ProposeIn, admin: Actor) -> DisputeView:
    d = await _get(db, ref)
    current = await view(db, d)
    if d.stage == 3:
        fail(status.HTTP_409_CONFLICT, "closed", "This dispute is closed.")
    if body.kind == "partial_refund":
        if not body.amount_pence:
            fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "amount_needed", "Say how much to refund.")
        if body.amount_pence > current.refundable_pence:
            fail(
                status.HTTP_409_CONFLICT,
                "more_than_paid",
                f"That's more than can be refunded ({money(current.refundable_pence)}).",
                left_pence=current.refundable_pence,
            )
    amount = body.amount_pence if body.kind == "partial_refund" else None
    text = proposal_text(body.kind, amount, current.provider_first)

    async def apply(session: DbSession) -> Dispute:
        fresh = await _get(db, ref, session)
        event = DisputeEvent(at=utcnow(), by_user_id=admin.user_id, kind="proposed", text=f"Proposed: {text}")
        updated = await Disputes(db).update(
            fresh.id,
            {
                "proposed": Resolution(kind=body.kind, amount_pence=amount, note=body.note).model_dump(mode="python"),
                "stage": 2,
                "status_text": f"Fix proposed: {text}",
            },
            extra_filter={"stage": {"$ne": 3}},
            push={"events": event.model_dump(mode="python")},
            session=session,
        )
        if updated is None:
            fail(status.HTTP_409_CONFLICT, "closed", "This dispute has just been closed.")
        await _tell(db, s, updated, "dispute_proposal", {"proposal": text}, ["customer", "provider"], session)
        await audit(
            db,
            admin,
            "dispute.proposed",
            Related(dispute_id=d.id, visit_id=d.visit_id),
            after={"kind": body.kind, "amount_pence": amount},
            note=body.note,
            session=session,
        )
        return updated

    return await view(db, await transaction(db, apply))


def outcome_text(kind: str, amount: int | None, provider_first: str) -> tuple[str, str]:
    """(the closing message's outcome, the admin card's status)."""
    match kind:
        case "return_visit":
            return f"{provider_first} came back and put it right.", f"Closed: {provider_first} put it right"
        case "partial_refund":
            return (
                f"We've refunded {money(amount or 0)}, paid by {provider_first}.",
                f"Closed: {money(amount or 0)} refunded by {provider_first}",
            )
        case "full_refund":
            return (
                f"We've refunded the full {money(amount or 0)}, paid by {provider_first}.",
                f"Closed: full refund by {provider_first}",
            )
    return "We've closed it without further action.", "Closed: no further action"


async def _claim(db: Db, ref: str, body: CloseIn, admin: Actor) -> DisputeClosing:
    """Claim the close before any money moves, in one transaction. A close already in progress
    with the same outcome (a double click, a retry, a second admin) resumes it, whatever is left
    to refund now; a different one waits. Only a new claim checks the amount."""

    async def claim(session: DbSession) -> DisputeClosing:
        d = await _get(db, ref, session)
        if d.stage == 3:
            fail(status.HTTP_409_CONFLICT, "closed", "This dispute is already closed.")
        if d.closing is not None:
            same = d.closing.outcome == body.outcome and (
                body.outcome != "partial_refund" or body.amount_pence in (None, d.closing.amount_pence)
            )
            if not same:
                fail(
                    status.HTTP_409_CONFLICT,
                    "closing",
                    "This dispute is already being closed another way. Have another look in a minute.",
                )
            return d.closing
        amount: int | None = None
        if body.outcome in ("partial_refund", "full_refund"):
            visit = await Visits(db).get(d.visit_id, session=session)
            unsettled = await PaymentRefunds(db).unsettled_pence(d.visit_id, session=session)
            left = refunds.refundable_left(visit, unsettled) if visit else 0
            amount = left if body.outcome == "full_refund" else body.amount_pence
            if not amount:
                if body.outcome == "full_refund":
                    fail(status.HTTP_409_CONFLICT, "nothing_to_refund", "There's nothing left to refund.")
                fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "amount_needed", "Say how much to refund.")
        closing = DisputeClosing(
            outcome=body.outcome,
            amount_pence=amount,
            attempt=d.close_attempts + 1,
            note=body.note,
            by_user_id=admin.user_id,
            at=utcnow(),
        )
        if (
            await Disputes(db).update(
                d.id,
                {"closing": closing.model_dump(mode="python"), "close_attempts": closing.attempt},
                extra_filter={"stage": {"$ne": 3}, "closing": None},
                session=session,
            )
            is None
        ):  # pragma: no cover - the transaction makes a concurrent claim a write conflict
            fail(status.HTTP_409_CONFLICT, "closing", "This dispute is being closed. Have another look in a minute.")
        return closing

    return await transaction(db, claim)


async def _release(db: Db, dispute_id: str, attempt: int, session: DbSession | None = None) -> None:
    """The close's refund definitely didn't happen: let the dispute be closed again."""

    async def release(sess: DbSession) -> None:
        await Disputes(db).update(
            dispute_id, {"closing": None}, extra_filter={"closing.attempt": attempt}, session=sess
        )

    if session is not None:
        await release(session)
    else:
        await transaction(db, release)


async def finish_close(
    db: Db,
    s: Settings,
    dispute_id: str,
    *,
    outcome: str,
    amount: int | None,
    refund_id: str | None,
    note: str,
    actor: Actor,
    session: DbSession,
) -> Dispute | None:
    """Inside a transaction: close the dispute (stage 3), tell both and audit it. None if it was
    already closed. For a refund outcome this runs only once the customer's refund is confirmed."""
    d = await Disputes(db).get(dispute_id, session=session)
    if d is None or d.stage == 3:
        return None
    provider = await Providers(db).get(d.provider_id, session=session)
    told, status_text = outcome_text(outcome, amount, wording.first_name(provider.name) if provider else "the provider")
    now = utcnow()
    events = []
    if amount:
        events.append(
            DisputeEvent(
                at=now,
                by_user_id=actor.user_id,
                kind="refunded",
                text=f"Refunded {money(amount)}, paid by the provider",
            )
        )
    events.append(DisputeEvent(at=now, by_user_id=actor.user_id, kind="closed", text=told))
    resolution = Resolution(kind=outcome, amount_pence=amount, refund_id=refund_id, note=note)  # type: ignore[arg-type]
    updated = await Disputes(db).update(
        d.id,
        {"stage": 3, "status_text": status_text, "resolution": resolution.model_dump(mode="python"), "closed_at": now,
         "closing": None},
        extra_filter={"stage": {"$ne": 3}},
        push={"events": {"$each": [e.model_dump(mode="python") for e in events]}},
        session=session,
    )  # fmt: skip
    if updated is None:  # pragma: no cover - read in the same transaction
        return None
    await _tell(
        db,
        s,
        updated,
        "dispute_closed",
        {"outcome": told},
        ["customer", "provider"],
        session,
        key=f"dispute:{d.id}:closed",
    )
    await audit(
        db,
        actor,
        "dispute.closed",
        Related(dispute_id=d.id, visit_id=d.visit_id),
        before={"stage": d.stage},
        after={"outcome": outcome, "amount_pence": amount, "refund_id": refund_id},
        note=note,
        session=session,
    )
    return updated


async def on_refund_settled(db: Db, s: Settings, intent: RefundIntent, *, succeeded: bool, session: DbSession) -> None:
    """Called by app.payments.refunds in the transaction that settles a dispute's refund: close the
    dispute once the customer's refund is confirmed, or release the claim if it failed."""
    if not intent.dispute_id:
        return
    d = await Disputes(db).get(intent.dispute_id, session=session)
    if d is None or d.closing is None or d.closing.refund_intent_id(d.id) != intent.id:
        return
    if not succeeded:
        await _release(db, d.id, d.closing.attempt, session=session)
        return
    by = Actor(kind="user", user_id=d.closing.by_user_id, role="admin") if d.closing.by_user_id else SYSTEM
    await finish_close(
        db,
        s,
        d.id,
        outcome=d.closing.outcome,
        amount=d.closing.amount_pence,
        refund_id=intent.refund_id or intent.id,
        note=d.closing.note,
        actor=by,
        session=session,
    )


async def close(db: Db, s: Settings, gateway: PaymentGateway, ref: str, body: CloseIn, admin: Actor) -> DisputeView:
    """Close a dispute. With a refund, the dispute closes when the customer's refund is confirmed:
    straight away usually, or later from the refund webhook or the settle task (the view shows
    the close in progress meanwhile)."""
    d = await _get(db, ref)
    if d.stage == 3:
        fail(status.HTTP_409_CONFLICT, "closed", "This dispute is already closed.")
    closing = await _claim(db, ref, body, admin)
    if not closing.amount_pence:

        async def close_now(session: DbSession) -> Dispute | None:
            return await finish_close(
                db, s, d.id, outcome=closing.outcome, amount=None, refund_id=None, note=closing.note, actor=admin,
                session=session,
            )  # fmt: skip

        if await transaction(db, close_now) is None:
            fail(status.HTTP_409_CONFLICT, "closed", "This dispute has just been closed.")
        return await one(db, ref)
    try:
        # One refund per close attempt, always under the same key, however often it's resumed.
        # Recording its success closes the dispute in the same transaction (on_refund_settled).
        await refunds.refund_visit(
            db,
            s,
            gateway,
            d.visit_id,
            closing.amount_pence,
            f"Dispute {d.ref}: {d.title}" + (f". {closing.note}" if closing.note else ""),
            admin,
            dispute_id=d.id,
            intent_id=closing.refund_intent_id(d.id),
        )
    except HTTPException as e:
        if (e.detail or {}).get("code") != "check_by_hand":  # anything else: it definitely didn't happen
            await _release(db, d.id, closing.attempt)
        raise
    return await one(db, ref)
