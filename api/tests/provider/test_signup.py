"""Sign-up: the checklist, the provider record, sealed tax details, the payment-account link."""

from app.core.crypto import unseal
from app.repos import Providers, TaxIdentities, Users
from tests.conftest import make_settings, sign_in
from tests.factories import make_user

START = {"name": "Ken Ashworth", "postcode": "HP15 7QT"}


async def test_a_new_provider_signs_up_to_the_payment_account_link(client, db, catalogue):
    await sign_in(client, db, "07700 900212", "Ken Ashworth")
    first = (await client.get("/api/p/signup")).json()
    assert first["provider_id"] is None and first["steps"][0]["state"] == "now"
    assert (await client.get("/api/p/home")).status_code == 403, "not a provider yet"

    r = await client.post("/api/p/signup/start", json=START)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "signing_up" and r.json()["steps"][0]["state"] == "done"
    user = await Users(db).by_phone("+447700900212")
    assert "provider" in user.roles
    provider = await Providers(db).by_user(user.id)
    assert provider.home.postcode == "HP15 7QT" and provider.home.district == "HP15" and provider.home.area
    again = await client.post("/api/p/signup/start", json=START)
    assert again.status_code == 201 and await Providers(db).count({"user_id": user.id}) == 1

    tax = await client.put("/api/p/signup/tax", json={"ni_number": "qq 12 34 56 c", "date_of_birth": "1958-03-14"})
    assert tax.status_code == 200, tax.text
    assert tax.json() == {"complete": True, "ni_masked": "QQ •• •• •• C", "dob_masked": "•• / •• / 1958"}
    sealed = await TaxIdentities(db).find_one({"provider_id": provider.id})
    assert "QQ123456C" not in str(sealed.model_dump()) and "1958-03-14" not in str(sealed.model_dump())
    assert unseal(sealed.ni_number_sealed, make_settings()) == "QQ123456C"
    assert unseal(sealed.dob_sealed, make_settings()) == "1958-03-14"
    raw = await db["providers"].find_one({"_id": provider.id})
    assert "QQ123456C" not in str(raw) and "1958-03-14" not in str(raw), "only masked copies on the provider"

    link = await client.post("/api/p/signup/payment-account")
    assert link.status_code == 200, link.text
    assert link.json()["url"] == "https://dev.example.test/p/signup?onboarding=done"  # the fake: instant
    done = (await client.get("/api/p/signup")).json()
    assert done["payment_account_status"] == "enabled"
    states = {s["key"]: s["state"] for s in done["steps"]}
    assert states["details"] == states["tax"] == states["payouts"] == "done"
    assert states["identity"] == "now" and states["insurance"] == "todo"
    once = await client.post("/api/p/signup/payment-account")
    assert once.status_code == 200
    assert await db["fake_gateway"].count_documents({"kind": "account", "provider_id": provider.id}) == 1


async def test_tax_details_are_checked(client, db, catalogue):
    await sign_in(client, db, "07700 900212")
    await client.post("/api/p/signup/start", json=START)
    assert (
        await client.put("/api/p/signup/tax", json={"ni_number": "123", "date_of_birth": "1958-03-14"})
    ).status_code == 422
    young = await client.put("/api/p/signup/tax", json={"ni_number": "QQ123456C", "date_of_birth": "2020-01-01"})
    assert young.status_code == 422 and young.json()["detail"]["code"] == "bad_dob"


async def test_call_me_emails_the_team_once_a_day(client, db, catalogue):
    admin = await make_user(db, "Asha Admin", "+447700900301", ["admin"])
    await db["users"].update_one({"_id": admin.id}, {"$set": {"email": "asha@example.com"}})
    await sign_in(client, db, "07700 900212", "Ken Ashworth")
    for _ in range(2):
        r = await client.post("/api/p/signup/callback", json={"step": "Tax details"})
        assert r.status_code == 202 and r.json()["ok"]
    msgs = await db["outbox"].find({"template_id": "callback_requested"}).to_list()
    assert len(msgs) == 1 and msgs[0]["channel"] == "email" and "07700 900212" in msgs[0]["body"]


async def test_a_bad_postcode_is_refused(client, db, catalogue):
    await sign_in(client, db, "07700 900212")
    r = await client.post("/api/p/signup/start", json={**START, "postcode": "NOT IT"})
    assert r.status_code == 422
