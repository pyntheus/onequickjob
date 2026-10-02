"""disputes. Owner: L3 (L1 opens them with insert)."""

from app.models.disputes import Dispute
from app.repos.base import Repo, idx


class Disputes(Repo[Dispute]):
    model = Dispute
    indexes = [idx("ref", unique=True), idx("visit_id"), idx("stage"), idx("provider_id"), idx("customer_id")]

    async def by_ref(self, ref: str) -> Dispute | None:
        return await self.find_one({"ref": ref})
