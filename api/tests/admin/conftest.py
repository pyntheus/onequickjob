"""Signed-in admin clients for the L3 admin tests: two admins, so drafting and approving can
be done by different people."""

import re
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


VERDICT = re.compile(r"/api/admin/providers/([^/]+)(?:/helpers/([^/]+))?/documents/([^/]+)/(?:verify|reject)$")


async def verdict(client: httpx.AsyncClient, path: str, body: dict) -> httpx.Response:
    """POST a verify or reject as the admin's page does: with the file id of the upload shown on
    the provider's page (AdminDocument.file_id), which the API checks is still the one to check."""
    m = VERDICT.search(path)
    assert m, path
    provider_id, helper_id, doc_type = m.groups()
    page = await client.get(f"/api/admin/providers/{provider_id}")
    file_id = None
    if page.status_code == 200:
        d = page.json()
        rows = (
            d["documents"]
            if helper_id is None
            else next((h["documents"] for h in d["helper_checks"] if h["user_id"] == helper_id), [])
        )
        file_id = next((r["file_id"] for r in rows if r["type"] == doc_type), None)
    return await client.post(path, json={"file_id": file_id, **body})
