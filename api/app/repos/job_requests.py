"""job_requests. Owner: L1 (create, cancel). Status changes to booked only through
app.services.marketplace (atomic claim). L2 records views; L3 raises guides."""

from pymongo import DESCENDING

from app.core.db import DbSession
from app.models.job_requests import JobRequest, RequestEvent
from app.repos.base import Repo, idx


class JobRequests(Repo[JobRequest]):
    model = JobRequest
    indexes = [
        idx("ref", unique=True),
        idx("status", "category_id"),
        idx("customer_id", ("created_at", DESCENDING)),
        idx("broadcast.provider_ids"),
    ]

    async def by_ref(self, ref: str, *, session: DbSession | None = None) -> JobRequest | None:
        return await self.find_one({"ref": ref}, session=session)

    async def add_event(
        self,
        request_id: str,
        event: RequestEvent,
        *,
        extra_filter: dict | None = None,
        session: DbSession | None = None,
    ) -> JobRequest | None:
        """Push an event. With extra_filter (e.g. {"status": "open"}) it's guarded: None if that
        doesn't match. Inside a transaction it also makes concurrent writers of the request conflict."""
        return await self.update(
            request_id,
            {},
            push={"events": event.model_dump(mode="python")},
            extra_filter=extra_filter,
            session=session,
        )

    async def record_view(
        self, request_id: str, provider_id: str, event: RequestEvent, *, session: DbSession | None = None
    ) -> bool:
        """Adds a viewed event the first time a provider opens the request. True if new."""
        res = await self.coll.update_one(
            {"_id": request_id, "viewed_by": {"$ne": provider_id}},
            {"$addToSet": {"viewed_by": provider_id}, "$push": {"events": event.model_dump(mode="python")}},
            session=self.s(session),
        )
        return res.modified_count == 1

    async def open_for_category(self, category_ids: list[str], *, session: DbSession | None = None) -> list[JobRequest]:
        return await self.find(
            {"status": "open", "category_id": {"$in": category_ids}},
            sort=[("created_at", DESCENDING)],
            session=session,
        )
