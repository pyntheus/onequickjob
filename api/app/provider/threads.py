"""The provider's message threads with customers (one per booking), through Messages.post.

Unread: messages from the other side since the provider last wrote or opened the thread.
Marking a message read is a write to F's messages collection that no repo function offers
yet (docs/spec/contract-changes/L2.md), so "opened" is the provider's own last message or,
failing that, the read_by list as the poster left it.
"""

from fastapi import status

from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.models.common import Related
from app.models.messages import Message, MessageThread
from app.provider.common import categories, short_name
from app.repos.bookings import Bookings
from app.repos.messages import Messages, MessageThreads
from app.repos.users import Users
from app.services.notify import link, notify, recipient_for
from app.shared.schemas import MessageOut, ThreadSummary


def _unread(messages: list[Message], user_id: str) -> int:
    n = 0
    for m in messages:
        if m.sender_user_id == user_id:
            n = 0
        elif user_id not in m.read_by:
            n += 1
    return n


async def _thread_for(db: Db, user_id: str, thread_id: str) -> MessageThread:
    t = await MessageThreads(db).get(thread_id)
    if t is None or not any(p.user_id == user_id for p in t.participants):
        not_found("That conversation")
    return t


async def list_threads(db: Db, user_id: str) -> list[ThreadSummary]:
    cats = await categories(db)
    out = []
    for t in await MessageThreads(db).for_user(user_id):
        other = next((p for p in t.participants if p.user_id != user_id), None)
        title = "Messages"
        if t.booking_id:
            b = await Bookings(db).get(t.booking_id)
            if b and b.category_id in cats:
                title = f"{cats[b.category_id].name} with {short_name(other.name) if other else 'your customer'}"
        msgs = await Messages(db).in_thread(t.id)
        out.append(
            ThreadSummary(
                id=t.id,
                kind=t.kind,
                title=title,
                other_party=short_name(other.name) if other else "",
                last_message_at=t.last_message_at,
                preview=t.last_message_preview,
                unread=_unread(msgs, user_id),
            )
        )
    return out


async def unread_total(db: Db, user_id: str) -> int:
    return sum(t.unread for t in await list_threads(db, user_id))


async def messages(db: Db, user_id: str, thread_id: str) -> list[MessageOut]:
    t = await _thread_for(db, user_id, thread_id)
    names = {p.user_id: p.name for p in t.participants}
    return [
        MessageOut(
            id=m.id,
            sender_user_id=m.sender_user_id,
            sender_role=m.sender_role,
            sender_name=short_name(names.get(m.sender_user_id or "", "OneQuickJob")),
            body=m.body,
            created_at=m.created_at,
            mine=m.sender_user_id == user_id,
        )
        for m in await Messages(db).in_thread(t.id)
    ]


async def post(db: Db, s: Settings, user_id: str, thread_id: str, body: str) -> MessageOut:
    t = await _thread_for(db, user_id, thread_id)
    text = body.strip()
    if not text:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty", "Write a message first.")
    me = next(p for p in t.participants if p.user_id == user_id)
    others = [p for p in t.participants if p.user_id != user_id]
    recipients = [u for p in others if (u := await Users(db).get(p.user_id)) and u.phone]
    to_path = f"/bookings/{t.booking_id}" if t.booking_id else "/account"

    async def send(session: DbSession) -> Message:
        msg = await Messages(db).post(t.id, user_id, "provider", text, session=session)
        for u in recipients:
            await notify(
                db,
                "message_received",
                to=recipient_for(u),
                data={"sender": short_name(me.name), "preview": text[:80], "link": link(to_path, s)},
                related=Related(thread_id=t.id, booking_id=t.booking_id, user_id=u.id),
                settings=s,
                session=session,
            )
        return msg

    msg = await transaction(db, send)
    return MessageOut(
        id=msg.id,
        sender_user_id=user_id,
        sender_role="provider",
        sender_name=short_name(me.name),
        body=msg.body,
        created_at=msg.created_at,
        mine=True,
    )
