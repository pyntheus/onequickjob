"""message_threads and messages. Shared: L1, L2 and L3 all post through post()."""

from pymongo import DESCENDING

from app.core.db import DbSession
from app.core.timeutil import utcnow
from app.models.common import Role
from app.models.messages import Message, MessageThread
from app.repos.base import Repo, idx

_STR = {"$type": "string"}


class MessageThreads(Repo[MessageThread]):
    model = MessageThread
    indexes = [
        idx("booking_id", unique=True, partialFilterExpression={"booking_id": _STR, "kind": "booking"}),
        idx("dispute_id"),
        idx("participants.user_id", ("last_message_at", DESCENDING)),
    ]

    async def for_user(self, user_id: str, *, session: DbSession | None = None) -> list[MessageThread]:
        return await self.find(
            {"participants.user_id": user_id}, sort=[("last_message_at", DESCENDING)], session=session
        )


class Messages(Repo[Message]):
    model = Message
    indexes = [idx("thread_id", "created_at")]

    async def in_thread(self, thread_id: str, limit: int = 200, *, session: DbSession | None = None) -> list[Message]:
        return await self.find({"thread_id": thread_id}, sort=[("created_at", 1)], limit=limit, session=session)

    async def post(
        self,
        thread_id: str,
        sender_user_id: str | None,
        sender_role: Role | str,
        body: str,
        attachments: list[str] | None = None,
        *,
        session: DbSession | None = None,
    ) -> Message:
        """Add a message and update the thread's preview. Both writes are in the caller's
        transaction when it passes session."""
        msg = Message(
            thread_id=thread_id,
            sender_user_id=sender_user_id,
            sender_role=sender_role,  # type: ignore[arg-type]
            body=body,
            attachments=attachments or [],
            read_by=[sender_user_id] if sender_user_id else [],
        )
        await self.insert(msg, session=session)
        await self.db[MessageThread.COLLECTION].update_one(
            {"_id": thread_id},
            {"$set": {"last_message_at": msg.created_at, "last_message_preview": body[:140], "updated_at": utcnow()}},
            session=self.s(session),
        )
        return msg
