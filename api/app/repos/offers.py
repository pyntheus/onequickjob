"""offers (counter-offers). Owner: F (marketplace core)."""

from pymongo import DESCENDING

from app.core.db import DbSession
from app.core.timeutil import utcnow
from app.models.offers import Offer
from app.repos.base import Repo, idx


class Offers(Repo[Offer]):
    model = Offer
    indexes = [
        idx("request_id", "status"),
        idx("provider_id", ("created_at", DESCENDING)),
        idx(
            "request_id",
            "provider_id",
            unique=True,
            partialFilterExpression={"status": "pending"},
            name="one_pending_counter_per_provider",
        ),
    ]

    async def for_request(self, request_id: str, *, session: DbSession | None = None) -> list[Offer]:
        return await self.find({"request_id": request_id}, sort=[("created_at", 1)], session=session)

    async def pending_for(self, request_id: str, provider_id: str, *, session: DbSession | None = None) -> Offer | None:
        return await self.find_one(
            {"request_id": request_id, "provider_id": provider_id, "status": "pending"}, session=session
        )

    async def lapse_pending(
        self, request_id: str, except_offer_id: str | None = None, *, session: DbSession | None = None
    ) -> list[Offer]:
        """Mark every other pending counter on a request as lapsed; returns them."""
        flt = {"request_id": request_id, "status": "pending"}
        if except_offer_id:
            flt["_id"] = {"$ne": except_offer_id}
        lapsing = await self.find(flt, session=session)
        if lapsing:
            now = utcnow()
            await self.coll.update_many(
                {"_id": {"$in": [o.id for o in lapsing]}, "status": "pending"},
                {"$set": {"status": "lapsed", "decided_at": now, "updated_at": now}},
                session=self.s(session),
            )
        return lapsing
