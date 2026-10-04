"""outbox. Owner: F. Written only by app.services.notify."""

import re
from datetime import datetime

from pymongo import DESCENDING

from app.core.db import DbSession
from app.models.system import OutboxMessage
from app.repos.base import Repo, idx


class Outbox(Repo[OutboxMessage]):
    model = OutboxMessage
    touch_updated_at = False
    indexes = [
        idx(("created_at", DESCENDING), ("_id", DESCENDING)),
        idx("recipient.user_id", ("created_at", DESCENDING)),
        idx("template_id", ("created_at", DESCENDING)),
        idx("related.request_id"),
        idx("idempotency_key", unique=True, partialFilterExpression={"idempotency_key": {"$type": "string"}}),
    ]

    async def latest(self, limit: int = 30, *, session: DbSession | None = None) -> list[OutboxMessage]:
        return await self.find({}, sort=[("created_at", DESCENDING), ("_id", DESCENDING)], limit=limit, session=session)

    async def search(
        self,
        *,
        q: str | None = None,
        channel: str | None = None,
        template_id: str | None = None,
        user_id: str | None = None,
        before: tuple[datetime, str] | None = None,
        limit: int = 50,
        search_login_codes: bool = True,
        session: DbSession | None = None,
    ) -> list[OutboxMessage]:
        """Newest first by created_at (seeded messages' ids don't follow time), then _id; `before`
        is the (created_at, _id) of the last message on the previous page.
        search_login_codes=False (outside DEMO_MODE): free text never matches the body of a
        login_code message, so search results can't be used to probe a masked code."""
        flt: dict = {}
        if q:
            rx = {"$regex": re.escape(q.strip()), "$options": "i"}
            body = {"body": rx} if search_login_codes else {"body": rx, "template_id": {"$ne": "login_code"}}
            flt["$or"] = [
                body,
                {"recipient.name": rx},
                {"recipient.phone": rx},
                {"recipient.email": rx},
                {"template_id": rx},
            ]
        if channel:
            flt["channel"] = channel
        if template_id:
            flt["template_id"] = template_id
        if user_id:
            flt["recipient.user_id"] = user_id
        if before:
            at, id_ = before
            page = {"$or": [{"created_at": {"$lt": at}}, {"created_at": at, "_id": {"$lt": id_}}]}
            flt = {"$and": [flt, page]} if flt else page
        newest = [("created_at", DESCENDING), ("_id", DESCENDING)]
        return await self.find(flt, sort=newest, limit=limit, session=session)
