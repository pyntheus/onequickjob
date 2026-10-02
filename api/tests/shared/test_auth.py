"""Sign-in by code: outbox delivery, expiry, attempts, sessions and cookies."""

from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.core.timeutil import utcnow
from app.services import auth
from tests.conftest import latest_code, make_settings, new_client, sign_in

PHONE = "07700 900456"


async def test_code_goes_to_the_outbox_never_anywhere_else(client, db):
    r = await client.post("/api/auth/code", json={"identifier": PHONE})
    assert r.status_code == 202
    assert r.json() == {"channel": "sms", "sent_to": "07700 9•••56", "expires_in_seconds": 600}
    msgs = await db["outbox"].find({"template_id": "login_code"}).to_list()
    assert len(msgs) == 1
    assert msgs[0]["channel"] == "sms" and msgs[0]["recipient"]["phone"] == "+447700900456"
    assert "code" not in msgs[0]["data"], "the plain code must only be in the rendered body"
    row = await db["login_codes"].find_one({"identifier": "+447700900456"})
    code = await latest_code(db)
    assert code not in str(row), "codes are stored hashed"


async def test_verify_creates_a_customer_and_a_secure_session_cookie(client, db):
    await client.post("/api/auth/code", json={"identifier": PHONE})
    r = await client.post(
        "/api/auth/verify", json={"identifier": "+44 7700 900456", "code": await latest_code(db), "name": "Sam Example"}
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["roles"] == ["customer"] and me["name"] == "Sam Example" and me["phone"] == "07700 900456"
    cookie = r.headers["set-cookie"].lower()
    assert "oqj_session=" in cookie and "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert (await client.get("/api/auth/me")).json()["user_id"] == me["user_id"]
    session = await db["sessions"].find_one({})
    assert client.cookies["oqj_session"] != session["_id"], "only the token's hash is stored"


async def test_email_sign_in(client, db):
    r = await client.post("/api/auth/code", json={"identifier": "Sam@Example.com"})
    assert r.json()["channel"] == "email"
    msg = await db["outbox"].find_one({"template_id": "login_code"})
    assert msg["channel"] == "email" and msg["recipient"]["email"] == "sam@example.com" and msg["subject"]
    me = await sign_in(client, db, "sam@example.com")
    assert me["email"] == "sam@example.com"


async def test_wrong_code_five_attempts_then_locked(client, db):
    await client.post("/api/auth/code", json={"identifier": PHONE})
    good = await latest_code(db)
    bad = "000000" if good != "000000" else "111111"
    for left in (4, 3, 2, 1):
        r = await client.post("/api/auth/verify", json={"identifier": PHONE, "code": bad})
        assert r.status_code == 400 and r.json()["detail"]["extra"]["attempts_left"] == left
    r = await client.post("/api/auth/verify", json={"identifier": PHONE, "code": bad})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_attempts"
    r = await client.post("/api/auth/verify", json={"identifier": PHONE, "code": good})
    assert r.status_code == 429, "after five wrong tries even the right code is refused"


async def test_expired_code_is_refused(client, db):
    await client.post("/api/auth/code", json={"identifier": PHONE})
    code = await latest_code(db)
    await db["login_codes"].update_many({}, {"$set": {"expires_at": utcnow() - timedelta(seconds=1)}})
    r = await client.post("/api/auth/verify", json={"identifier": PHONE, "code": code})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "code_expired"


async def test_a_code_works_once_and_only_the_latest_counts(client, db):
    await client.post("/api/auth/code", json={"identifier": PHONE})
    first = await latest_code(db)
    await client.post("/api/auth/code", json={"identifier": PHONE})
    second = await latest_code(db)
    if first != second:
        r = await client.post("/api/auth/verify", json={"identifier": PHONE, "code": first})
        assert r.status_code == 400
    assert (await client.post("/api/auth/verify", json={"identifier": PHONE, "code": second})).status_code == 200
    assert (await client.post("/api/auth/verify", json={"identifier": PHONE, "code": second})).status_code == 400


async def test_issuing_codes_is_rate_limited(db):
    s = make_settings(login_code_min_interval_seconds=30)
    await auth.issue_code(db, s, PHONE)
    with pytest.raises(HTTPException) as e:
        await auth.issue_code(db, s, PHONE)
    assert e.value.status_code == 429


async def test_at_most_six_codes_an_hour(db):
    s = make_settings()
    for _ in range(6):
        await auth.issue_code(db, s, PHONE)
    with pytest.raises(HTTPException) as e:
        await auth.issue_code(db, s, PHONE)
    assert e.value.detail["code"] == "too_many_codes"


async def test_bad_identifiers(client):
    assert (await client.post("/api/auth/code", json={"identifier": "12345"})).status_code == 422
    assert (await client.post("/api/auth/code", json={"identifier": "+1 202 555 0100"})).status_code == 422
    assert (await client.post("/api/auth/code", json={"identifier": "not-an-email@"})).status_code == 422


async def test_logout_ends_the_session(client, db):
    await sign_in(client, db, PHONE)
    assert (await client.get("/api/auth/me")).status_code == 200
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert await db["sessions"].count_documents({}) == 0
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_expired_session_is_not_accepted(client, db):
    await sign_in(client, db, PHONE)
    await db["sessions"].update_many({}, {"$set": {"expires_at": utcnow() - timedelta(seconds=1)}})
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_suspended_user_cannot_sign_in(client, db):
    await sign_in(client, db, PHONE)
    await db["users"].update_many({}, {"$set": {"status": "suspended"}})
    assert (await client.get("/api/auth/me")).status_code == 401
    await client.post("/api/auth/code", json={"identifier": PHONE})
    r = await client.post("/api/auth/verify", json={"identifier": PHONE, "code": await latest_code(db)})
    assert r.status_code == 403


async def test_magic_link_signs_in_once(app, client, db):
    me = await sign_in(client, db, PHONE)
    token = await auth.create_magic_link(db, make_settings(), me["user_id"], "job_alert", "/p/j/R-2301")
    async with await new_client(app) as fresh:
        r = await fresh.post("/api/auth/magic", json={"token": token})
        assert r.status_code == 200 and r.json()["next"] == "/p/j/R-2301"
        assert (await fresh.get("/api/auth/me")).status_code == 200
        assert (await fresh.post("/api/auth/magic", json={"token": token})).status_code == 400


async def test_demo_sessions_end_when_demo_mode_is_turned_off(client, db):
    """Codex F-3: a Switch-user session must not outlive DEMO_MODE."""
    import httpx

    from app.main import create_app
    from tests.factories import make_user

    admin = await make_user(db, "Jo Morgan", "+447700900901", ["admin"])
    await db["users"].update_one({"_id": admin.id}, {"$set": {"demo_key": "admin_jo"}})
    assert (await client.post("/api/demo/switch", json={"user_id": admin.id})).status_code == 200
    demo_cookie = client.cookies["oqj_session"]
    code_user = await new_client_signed_in(db)

    off = create_app(make_settings(demo_mode=False))
    async with (
        off.router.lifespan_context(off),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=off), base_url="https://test") as c,
    ):
        c.cookies.set("oqj_session", demo_cookie)
        assert (await c.get("/api/auth/me")).status_code == 401
        assert (await c.get("/api/admin/outbox")).status_code == 401
        c.cookies.set("oqj_session", code_user)
        assert (await c.get("/api/auth/me")).status_code == 200, "ordinary sessions are unaffected"
    assert await db["sessions"].count_documents({"via": "demo"}) == 0


async def new_client_signed_in(db) -> str:
    from app.main import create_app

    app = create_app(make_settings())
    async with app.router.lifespan_context(app), await new_client(app) as c:
        await sign_in(c, db, "07700 900777")
        return c.cookies["oqj_session"]
