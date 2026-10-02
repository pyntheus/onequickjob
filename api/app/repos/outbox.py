"""outbox. Owner: F. Written only by app.services.notify."""

import re

from pymongo import DESCENDING

from app.models.system import OutboxMessage
from app.repos.base import Repo, idx


class Outbox(Repo[OutboxMessage]):
    model = OutboxMessage
    touch_updated_at = False
    indexes = [
        idx(("created_at", DESCENDING)),
        idx("recipient.user_id", ("created_at", DESCENDING)),
        idx("template_id", ("created_at", DESCENDING)),
        idx("related.request_id"),
    ]

    async def latest(self, limit: int = 30) -> list[OutboxMessage]:
        return await self.find({}, sort=[("created_at", DESCENDING), ("_id", DESCENDING)], limit=limit)

    async def search(
        self,
        *,
        q: str | None = None,
        channel: str | None = None,
        template_id: str | None = None,
        user_id: str | None = None,
        before_id: str | None = None,
        limit: int = 50,
    ) -> list[OutboxMessage]:
        flt: dict = {}
        if q:
            rx = {"$regex": re.escape(q.strip()), "$options": "i"}
            flt["$or"] = [
                {"body": rx},
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
        if before_id:
            flt["_id"] = {"$lt": before_id}
        return await self.find(flt, sort=[("_id", DESCENDING)], limit=limit)
