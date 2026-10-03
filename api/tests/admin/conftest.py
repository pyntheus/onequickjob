"""Signed-in admin clients for the L3 admin tests: two admins, so drafting and approving can
be done by different people."""

from collections.abc import AsyncIterator

import httpx
import pytest

from tests.conftest import new_client, sign_in
from tests.factories import make_user


@pytest.fixture
async def jo(app, db) -> AsyncIterator[httpx.AsyncClient]:
    await make_user(db, "Jo Morgan", "+447700900901", ["admin"])
    async with await new_client(app) as c:
        await sign_in(c, db, "07700 900901")
        yield c


@pytest.fixture
async def sam(app, db) -> AsyncIterator[httpx.AsyncClient]:
    await make_user(db, "Sam Patel", "+447700900902", ["admin"])
    async with await new_client(app) as c:
        await sign_in(c, db, "07700 900902")
        yield c


def ok(r: httpx.Response, code: int = 200) -> dict:
    assert r.status_code == code, r.text
    return r.json()
