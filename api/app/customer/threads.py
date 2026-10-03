"""Message threads from the customer's side (L1): their booking threads (one per booking) and
dispute threads. Everyone posts through Messages.post; the other participants get a text
(message_received)."""

from fastapi import status

from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.models.common import Related
from app.models.messages import Message, MessageThread
from app.models.users import User
from app.repos.bookings import Bookings
from app.repos.categories import Categories
from app.repos.disputes import Disputes
from app.repos.messages import Messages, MessageThreads
from app.repos.users import Users
from app.services.notify import link, notify, recipient_for
from app.shared.schemas import MessageOut, ThreadSummary

PREVIEW = 80


async def own_thread(db: Db, thread_id: str, user: User) -> MessageThread:
    thread = await MessageThreads(db).get(thread_id)
    if thread is None or all(p.user_id != user.id for p in thread.participants):
        not_found("That conversation")
    return thread


async def _title(db: Db, thread: MessageThread, other: str) -> str:
    if thread.kind == "booking" and thread.booking_id:
        booking = await Bookings(db).get(thread.booking_id)
        cat = await Categories(db).get(booking.category_id) if booking else None
        if cat:
            return f"{cat.name} with {other}"
    if thread.kind == "dispute" and thread.dispute_id:
        dispute = await Disputes(db).get(thread.dispute_id)
        if dispute:
            return f"Problem reported: {dispute.title}"
    return f"Messages with {other}"


async def _display_names(db: Db, thread: MessageThread) -> dict[str, str]:
    """Participants as customers see them: providers by their short name (Dave H.)."""
    from app.repos.providers import Providers

    out = {}
    for p in thread.participants:
        name = p.name
        if p.role == "provider":
            provider = await Providers(db).by_user(p.user_id)
            name = provider.short if provider else name
        out[p.user_id] = name
    return out


async def summaries(db: Db, user: User) -> list[ThreadSummary]:
    out = []
    for t in await MessageThreads(db).for_user(user.id):
        names = await _display_names(db, t)
        other = ", ".join(n for uid, n in names.items() if uid != user.id) or "OneQuickJob"
        unread = await Messages(db).count({"thread_id": t.id, "read_by": {"$ne": user.id}})
        out.append(
            ThreadSummary(
                id=t.id,
                kind=t.kind,
                title=await _title(db, t, other),
                other_party=other,
                last_message_at=t.last_message_at,
                preview=t.last_message_preview,
                unread=unread,
            )
        )
    return out


def message_out(m: Message, names: dict[str, str], user: User) -> MessageOut:
    sender = "OneQuickJob" if m.sender_user_id is None else names.get(m.sender_user_id, "")
    return MessageOut(
        id=m.id,
        sender_user_id=m.sender_user_id,
        sender_role=m.sender_role,
        sender_name=sender,
        body=m.body,
        created_at=m.created_at,
        mine=m.sender_user_id == user.id,
    )


async def messages(db: Db, thread: MessageThread, user: User) -> list[MessageOut]:
    names = await _display_names(db, thread)
    found = await Messages(db).in_thread(thread.id)
    # Mark them read for this user (contract-change request L1: Messages.mark_read).
    await Messages(db).coll.update_many(
        {"thread_id": thread.id, "read_by": {"$ne": user.id}}, {"$addToSet": {"read_by": user.id}}
    )
    return [message_out(m, names, user) for m in found]


async def notify_others(
    db: Db, s: Settings, thread: MessageThread, sender: User, body: str, *, session: DbSession
) -> None:
    preview = body if len(body) <= PREVIEW else body[: PREVIEW - 1].rstrip() + "…"
    sender_name = next((p.name for p in thread.participants if p.user_id == sender.id), sender.name)
    for p in thread.participants:
        if p.user_id == sender.id:
            continue
        u = await Users(db).get(p.user_id, session=session)
        if not (u and u.phone):
            continue
        path = "/p" if p.role == "provider" else "/account?tab=messages"
        await notify(
            db,
            "message_received",
            to=recipient_for(u),
            settings=s,
            related=Related(thread_id=thread.id, booking_id=thread.booking_id, dispute_id=thread.dispute_id),
            data={"sender": sender_name.split(" ")[0] or "Someone", "preview": preview, "link": link(path, s)},
            session=session,
        )


async def post(db: Db, s: Settings, thread: MessageThread, user: User, body: str) -> MessageOut:
    text = body.strip()
    if not text:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty_message", "Write a message first.")
    role = next(p.role for p in thread.participants if p.user_id == user.id)

    async def send(session: DbSession) -> Message:
        msg = await Messages(db).post(thread.id, user.id, role, text, session=session)
        await notify_others(db, s, thread, user, text, session=session)
        return msg

    msg = await transaction(db, send)
    return message_out(msg, await _display_names(db, thread), user)
