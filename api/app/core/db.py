"""Mongo connection: PyMongo's native async client (AsyncMongoClient), no ODM.

Mongo runs as a single-node replica set (rs0), so a write that spans collections runs in one
multi-document transaction, `await transaction(db, fn)`: it commits as a whole or not at all.
CLAUDE.md ("Writing to several collections") shows the one pattern to use.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import Request
from pymongo import AsyncMongoClient
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from app.core.config import Settings

type Db = AsyncDatabase
type DbSession = AsyncClientSession

_open: ContextVar[DbSession | None] = ContextVar("oqj_open_transaction", default=None)


def make_client(settings: Settings) -> AsyncMongoClient:
    return AsyncMongoClient(settings.mongo_url, tz_aware=True, uuidRepresentation="standard", appname="oqj-api")


def check_db_name(name: str) -> str:
    """Guard against pointing tools at a database that isn't ours."""
    if not name.startswith("oqj"):
        raise ValueError(f"refusing to use database {name!r}: OneQuickJob databases start with 'oqj'")
    return name


async def transaction[T](db: Db, fn: Callable[[DbSession], Awaitable[T]]) -> T:
    """Run fn(session) as one transaction and return what it returns.

    The driver re-runs the whole of fn on a transient error (a write conflict with a concurrent
    transaction, an election) and retries an uncertain commit, so fn must only touch the
    database: never call the payment gateway, the file store or anything else outside Mongo
    inside it. Every database call in fn passes session=. An exception raised in fn (fail(409)
    included) aborts the transaction, so nothing fn wrote is kept, and propagates."""
    if _open.get() is not None:
        raise RuntimeError("transactions don't nest: pass the open session down instead")
    async with db.client.start_session() as session:

        async def run(s: DbSession) -> T:
            token = _open.set(s)
            try:
                return await fn(s)
            finally:
                _open.reset(token)

        return await session.with_transaction(
            run, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority")
        )


def check_session(session: DbSession | None) -> DbSession | None:
    """Every repository call goes through this. Inside a transaction a call without the
    session would run outside it: not rolled back with it, and blocked by its locks until the
    transaction times out. That's always a bug, so it fails loudly instead."""
    if (open_ := _open.get()) is not None and session is not open_:
        raise RuntimeError("inside a transaction: pass session= to every database call")
    return session


@asynccontextmanager
async def connect(settings: Settings, db_name: str | None = None) -> AsyncIterator[tuple[AsyncMongoClient, Db]]:
    client = make_client(settings)
    try:
        yield client, client[check_db_name(db_name or settings.mongo_db)]
    finally:
        await client.close()


def get_db(request: Request) -> Db:
    """FastAPI dependency: the database for this worktree."""
    return request.app.state.db
