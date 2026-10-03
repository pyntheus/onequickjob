"""L1's own collection (plan_changes) and its indexes, created at start-up by the customer
router so no transaction ever has to create it. Integration can fold it into app.repos.ALL
(docs/spec/contract-changes/L1.md), as for L3's payments collections."""

import contextlib

from pymongo.errors import CollectionInvalid, OperationFailure

from app.core.db import Db
from app.repos.plan_changes import PlanChanges

REPOS = (PlanChanges,)


async def ensure_customer_collections(db: Db) -> None:
    existing = set(await db.list_collection_names())
    for repo in REPOS:
        name = repo.model.COLLECTION
        if name not in existing:
            with contextlib.suppress(CollectionInvalid, OperationFailure):  # another process made it first
                await db.create_collection(name)
        await db[name].create_indexes(repo.indexes)
