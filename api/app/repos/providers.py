"""providers and tax_identities. Owner: L2. L3 verifies documents and suspends
providers through set_document and set_status; L1 updates ratings via apply_rating."""

from typing import Any

from app.core.timeutil import utcnow
from app.models.providers import Provider, ProviderDocument, ProviderStatus, TaxIdentity
from app.repos.base import Repo, idx


class Providers(Repo[Provider]):
    model = Provider
    indexes = [idx("user_id", unique=True), idx("skills"), idx("status"), idx("home.district")]

    async def by_user(self, user_id: str) -> Provider | None:
        return await self.find_one({"user_id": user_id})

    async def with_skill(
        self, category_id: str, statuses: tuple[ProviderStatus, ...] = ("active", "payouts_paused")
    ) -> list[Provider]:
        return await self.find({"skills": category_id, "status": {"$in": list(statuses)}})

    async def set_document(self, provider_id: str, doc: ProviderDocument) -> Provider | None:
        """Insert or replace the provider's document of doc.type."""
        p = await self.get(provider_id)
        if p is None:
            return None
        docs = [d for d in p.documents if d.type != doc.type] + [doc]
        return await self.update(provider_id, {"documents": [d.model_dump(mode="python") for d in docs]})

    async def set_status(self, provider_id: str, status: ProviderStatus, reason: str | None = None) -> Provider | None:
        return await self.update(provider_id, {"status": status, "status_reason": reason})

    async def apply_rating(self, provider_id: str, stars: int) -> Provider | None:
        """Fold one new rating into the running average."""
        p = await self.get(provider_id)
        if p is None:
            return None
        n = p.stats.rating_count
        avg = ((p.stats.rating_avg or 0) * n + stars) / (n + 1)
        return await self.update(provider_id, {"stats.rating_avg": round(avg, 2), "stats.rating_count": n + 1})

    async def patch(self, provider_id: str, fields: dict[str, Any]) -> Provider | None:
        return await self.update(provider_id, fields)


class TaxIdentities(Repo[TaxIdentity]):
    model = TaxIdentity
    touch_updated_at = False
    indexes = [idx("provider_id", unique=True)]

    async def upsert(self, provider_id: str, ni_sealed: str, dob_sealed: str) -> None:
        await self.coll.update_one(
            {"provider_id": provider_id},
            {
                "$set": {"ni_number_sealed": ni_sealed, "dob_sealed": dob_sealed, "updated_at": utcnow()},
                "$setOnInsert": {"_id": provider_id},
            },
            upsert=True,
        )
