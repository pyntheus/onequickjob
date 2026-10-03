"""visits. Owner: L2 (start, photos, finish, helper, cover); L1 skips; L3 writes
charge state from gateway webhooks. Created by app.services.schedule."""

from datetime import date

from app.core.db import DbSession
from app.models.visits import Visit
from app.repos.base import Repo, idx

_STR = {"$type": "string"}


class Visits(Repo[Visit]):
    model = Visit
    indexes = [
        idx("provider_id", "local_date"),
        idx("performer.user_id", "local_date"),
        idx("customer_id", "scheduled_start"),
        idx("booking_id", "scheduled_start"),
        idx("status", "local_date"),
        idx("category_id", "status"),
        idx(
            "series_id",
            "local_date",
            unique=True,
            partialFilterExpression={"series_id": _STR},
            name="one_visit_per_series_day",
        ),
        idx("booking_id", unique=True, partialFilterExpression={"is_first": True}, name="one_first_visit_per_booking"),
    ]

    async def for_provider_day(self, provider_id: str, day: date, *, session: DbSession | None = None) -> list[Visit]:
        return await self.find(
            {"provider_id": provider_id, "local_date": day.isoformat(), "status": {"$ne": "cancelled"}},
            sort=[("scheduled_start", 1)],
            session=session,
        )

    async def for_provider_between(
        self, provider_id: str, first: date, last: date, *, session: DbSession | None = None
    ) -> list[Visit]:
        return await self.find(
            {"provider_id": provider_id, "local_date": {"$gte": first.isoformat(), "$lte": last.isoformat()}},
            sort=[("scheduled_start", 1)],
            session=session,
        )

    async def for_booking(self, booking_id: str, *, session: DbSession | None = None) -> list[Visit]:
        return await self.find({"booking_id": booking_id}, sort=[("scheduled_start", 1)], session=session)
