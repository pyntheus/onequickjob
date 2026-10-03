"""plan_changes (A10). Owner: L1.

Not yet in app.repos.ALL (F's registry): the customer router creates the collection and its
indexes at start-up (app.customer.store.ensure_customer_collections) until integration adds it.
"""

from app.core.db import DbSession
from app.models.plan_changes import PlanChange
from app.repos.base import Repo, idx


class PlanChanges(Repo[PlanChange]):
    model = PlanChange
    indexes = [
        idx(
            "series_id", unique=True, partialFilterExpression={"status": "pending"}, name="one_pending_change_per_plan"
        ),
        idx("token_hash", unique=True),
        idx("status", "expires_at"),
    ]

    async def pending_for(self, series_id: str, *, session: DbSession | None = None) -> PlanChange | None:
        return await self.find_one({"series_id": series_id, "status": "pending"}, session=session)

    async def by_token_hash(self, token_hash: str, *, session: DbSession | None = None) -> PlanChange | None:
        return await self.find_one({"token_hash": token_hash}, session=session)
