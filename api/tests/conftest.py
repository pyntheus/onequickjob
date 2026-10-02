"""Test harness. Tests run in the api container (make test-api) against MONGO_DB, which the
Makefile sets to <worktree database>_test, so lanes running tests side by side never
touch each other's data or their dev data. Every test starts with empty collections."""

import os
import re
from collections.abc import AsyncIterator

import httpx
import pytest

from app.core.config import Settings
from app.core.db import Db
from app.main import create_app
from app.repos import ensure_indexes
from app.seed.catalogue import load_catalogue, load_pricing_v1

DB_NAME = os.environ.get("MONGO_DB", "oqj_test")
assert DB_NAME.endswith("_test") or DB_NAME == "oqj_test", "tests must use a *_test database"


def make_settings(**overrides) -> Settings:
    base = {
        "mongo_url": os.environ.get("MONGO_URL", "mongodb://oqj-mongo:27017"),
        "mongo_db": DB_NAME,
        "secret_key": "test-secret-key-0123456789",
        "tasks_enabled": False,
        "serve_files": False,
        "demo_mode": True,
        "cookie_secure": True,
        "public_base_url": "https://dev.example.test",
        "files_dir": "/tmp/oqj-test-files",  # noqa: S108 - throwaway, inside the test container
        "login_code_min_interval_seconds": 0,
    }
    return Settings(**{**base, **overrides})


@pytest.fixture(scope="session")
async def app():
    application = create_app(make_settings())
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def db(app) -> AsyncIterator[Db]:
    database: Db = app.state.db
    for name in await database.list_collection_names():
        await database[name].delete_many({})
    await ensure_indexes(database)
    yield database


@pytest.fixture
async def catalogue(db):
    cats = await load_catalogue(db)
    await load_pricing_v1(db)
    return cats


@pytest.fixture
async def client(app, db) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as c:
        yield c


async def new_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test")


async def latest_code(db: Db) -> str:
    msg = await db["outbox"].find_one({"template_id": "login_code"}, sort=[("created_at", -1), ("_id", -1)])
    assert msg, "no login code in the outbox"
    m = re.search(r"\b(\d{6})\b", msg["body"])
    assert m
    return m.group(1)


async def sign_in(client: httpx.AsyncClient, db: Db, identifier: str, name: str = "Test Person") -> dict:
    r = await client.post("/api/auth/code", json={"identifier": identifier})
    assert r.status_code == 202, r.text
    r = await client.post(
        "/api/auth/verify", json={"identifier": identifier, "code": await latest_code(db), "name": name}
    )
    assert r.status_code == 200, r.text
    return r.json()
