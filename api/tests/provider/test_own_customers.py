"""Your own customers: the invite-only rule, the invite text, and fees from money.py."""

from app.core.ids import token_hash
from app.repos import OwnCustomerInvites
from tests.conftest import make_settings
from tests.factories import make_customer

INVITE = {
    "name": "Mary Bishop",
    "phone": "07700 900140",
    "category_id": "mowing",
    "price_pence": 2500,
    "frequency": "fortnightly",
}


async def test_inviting_a_new_customer_sends_a_text_with_a_single_link(dave_client, db, dave):
    r = await dave_client.post("/api/p/own-customers/invites", json=INVITE)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "invited" and out["phone"] == "+447700900140"
    assert (out["price_pence"], out["fee_pence"], out["provider_pence"]) == (2500, 125, 2375)
    inv = await OwnCustomerInvites(db).get(out["invite_id"])
    msg = await db["outbox"].find_one({"template_id": "own_customer_invite"})
    assert msg["recipient"]["phone"] == "+447700900140" and inv.outbox_id == msg["_id"]
    assert msg["body"].startswith("Dave here. I'd like to arrange your lawn mowing through OneQuickJob")
    assert "£25 a visit" in msg["body"]
    token = msg["body"].rsplit("/invite/", 1)[1]
    assert inv.token_hash == token_hash(token, make_settings().pepper), "only the token's hash is stored"
    listed = (await dave_client.get("/api/p/own-customers")).json()
    assert [(c["name"], c["status"]) for c in listed["customers"]] == [("Mary Bishop", "invited")]
    again = await dave_client.post("/api/p/own-customers/invites", json=INVITE)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_invited"


async def test_a_platform_customers_number_is_blocked_and_recorded(dave_client, db, dave):
    await make_customer(db)  # Sarah, 07700 900123, found us through the platform
    r = await dave_client.post("/api/p/own-customers/invites", json={**INVITE, "phone": "07700 900123"})
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "platform_customer",
        "message": "That number already belongs to a OneQuickJob customer, so they stay on the standard fee. "
        "Any regular work you already do for them is still yours.",
    }
    blocked = await OwnCustomerInvites(db).find({"status": "blocked"})
    assert len(blocked) == 1 and blocked[0].phone == "+447700900123" and blocked[0].token_hash is None
    assert await db["outbox"].count_documents({"template_id": "own_customer_invite"}) == 0


async def test_the_fee_comparison_and_preview_come_from_money_py(dave_client, db, dave):
    view = (await dave_client.get("/api/p/own-customers")).json()
    c = view["comparison"]
    assert c["example_price_pence"] == 3000
    assert (c["own_customer"]["fee_pence"], c["own_customer"]["provider_pence"]) == (150, 2850)
    assert (c["standard"]["fee_pence"], c["standard"]["provider_pence"]) == (450, 2550)
    p = (await dave_client.get("/api/p/own-customers/preview", params={"price_pence": 1500})).json()
    assert (p["fee_pence"], p["provider_pence"], p["mode"]) == (100, 1400, "own_customer")  # the 100p minimum


async def test_invites_are_for_your_own_jobs_in_whole_pounds(dave_client, db, dave):
    for change, code in [
        ({"category_id": "windows"}, "not_your_job"),
        ({"price_pence": 2550}, "whole_pounds"),
        ({"phone": "01494 123456"}, "not_a_mobile"),
        ({"phone": "not a number"}, "invalid_phone"),
    ]:
        r = await dave_client.post("/api/p/own-customers/invites", json={**INVITE, **change})
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, change
