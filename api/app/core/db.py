"""Mongo connection: PyMongo's native async client (AsyncMongoClient), no ODM."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings

type Db = AsyncDatabase


def make_client(settings: Settings) -> AsyncMongoClient:
    return AsyncMongoClient(settings.mongo_url, tz_aware=True, uuidRepresentation="standard", appname="oqj-api")


def check_db_name(name: str) -> str:
    """Guard against pointing tools at a database that isn't ours."""
    if not name.startswith("oqj"):
        raise ValueError(f"refusing to use database {name!r}: OneQuickJob databases start with 'oqj'")
    return name


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
