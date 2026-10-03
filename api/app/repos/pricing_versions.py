"""pricing_versions. Owner: L3. Exactly one live version (unique partial index)."""

from pymongo import DESCENDING

from app.core.db import DbSession
from app.models.pricing_versions import PricingVersion
from app.repos.base import Repo, idx


class PricingVersions(Repo[PricingVersion]):
    model = PricingVersion
    touch_updated_at = False
    indexes = [
        idx("version", unique=True),
        idx("status", unique=True, partialFilterExpression={"status": "live"}, name="one_live_version"),
    ]

    async def live(self, *, session: DbSession | None = None) -> PricingVersion | None:
        return await self.find_one({"status": "live"}, session=session)

    async def next_version(self, *, session: DbSession | None = None) -> int:
        latest = await self.find_one({}, sort=[("version", DESCENDING)], session=session)
        return 1 if latest is None else latest.version + 1
