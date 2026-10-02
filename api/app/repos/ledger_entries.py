"""ledger_entries. Owner: L2 (charge and tip entries on finish); L3 (refunds).
Written only through app.services.ledger so gross == fee + net always holds."""

from datetime import date

from pymongo import DESCENDING

from app.models.records import LedgerEntry
from app.repos.base import Repo, idx


class LedgerEntries(Repo[LedgerEntry]):
    model = LedgerEntry
    indexes = [
        idx("visit_id", "kind", unique=True, partialFilterExpression={"kind": "charge"}, name="one_charge_per_visit"),
        idx("provider_id", ("occurred_at", DESCENDING)),
        idx("provider_id", "local_date"),
        idx("tax_year", "provider_id"),
    ]

    async def net_between(self, provider_id: str, first: date, last: date) -> int:
        """Sum of net pence (what the provider receives) for London dates first..last inclusive."""
        rows = self.coll.aggregate(
            [
                {
                    "$match": {
                        "provider_id": provider_id,
                        "local_date": {"$gte": first.isoformat(), "$lte": last.isoformat()},
                    }
                },
                {"$group": {"_id": None, "net": {"$sum": "$net_pence"}}},
            ]
        )
        async for row in await rows:
            return int(row["net"])
        return 0
