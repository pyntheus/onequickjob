"""The payments collections (payment_events, payment_refunds) and their indexes, created at
start-up by the payments router so no transaction ever has to create them. Integration can
fold them into app.repos.ALL (docs/spec/contract-changes/L3.md)."""

import contextlib

from pymongo.errors import CollectionInvalid, OperationFailure

from app.core.db import Db
from app.repos.payments import PaymentEvents, PaymentRefunds

REPOS = (PaymentEvents, PaymentRefunds)


async def ensure_payment_collections(db: Db) -> None:
    existing = set(await db.list_collection_names())
    for repo in REPOS:
        name = repo.model.COLLECTION
        if name not in existing:
            with contextlib.suppress(CollectionInvalid, OperationFailure):  # another process made it first
                await db.create_collection(name)
        await db[name].create_indexes(repo.indexes)
