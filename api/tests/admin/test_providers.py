"""Providers: the table and its filters, a provider's page, document checks (a basic DBS check
runs 12 months from issue: A3), suspension, reminders and the payment account."""

from datetime import date, timedelta

from app.core.timeutil import add_months, london_today
from app.models.providers import ProviderDocument, TaxDetails
from app.repos import Categories, Providers
from app.services.eligibility import can_take
from tests.admin.conftest import ok
from tests.factories import make_provider


async def test_the_table_and_its_filters(jo, db, catalogue):
    alan = await make_provider(db, "Alan Pryce", "+447700900210", ["mowing"])
    soon = london_today() + timedelta(days=9)
    await Providers(db).set_document(alan.id, ProviderDocument(type="insurance", status="verified", expires_on=soon))
    await make_provider(db, "Jan Kowalski", "+447700900211", ["mowing"], status="payouts_paused")
    ken = await make_provider(db, "Ken Ashworth", "+447700900212", ["mowing"], docs=[], status="signing_up")
    for p in (alan, ken):
        await Providers(db).patch(p.id, {"tax": TaxDetails(complete=True).model_dump(mode="python")})
    everyone = ok(await jo.get("/api/admin/providers"))
    assert [r["short"] for r in everyone] == ["Alan P.", "Jan K.", "Ken A."]
    by = {r["short"]: r for r in everyone}
    assert by["Alan P."]["insurance"] == {"status": "warn", "expires_on": soon.isoformat()}
    assert by["Jan K."]["hmrc_complete"] is False and by["Jan K."]["insurance"]["status"] == "ok"
    attention = [r["short"] for r in ok(await jo.get("/api/admin/providers?filter=attention"))]
    assert attention == ["Alan P.", "Jan K."]
    assert [r["short"] for r in ok(await jo.get("/api/admin/providers?filter=signup"))] == ["Ken A."]
    assert (await jo.get("/api/admin/providers?filter=nonsense")).status_code == 422


async def test_a_basic_dbs_check_is_verified_for_12_months_from_issue(jo, db, catalogue):
    p = await make_provider(db, "Lorna Baines", "+447700900203", ["cleaning"], docs=["insurance"])
    issued = london_today() - timedelta(days=40)
    await Providers(db).set_document(p.id, ProviderDocument(type="dbs_basic", status="pending", file_id=None))
    cleaning = await Categories(db).get("cleaning")
    assert cleaning and not can_take(p, cleaning).ok

    r = await jo.post(f"/api/admin/providers/{p.id}/documents/dbs_basic/verify", json={})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "dates_needed"
    d = ok(
        await jo.post(f"/api/admin/providers/{p.id}/documents/dbs_basic/verify", json={"issued_on": issued.isoformat()})
    )
    dbs = next(x for x in d["documents"] if x["type"] == "dbs_basic")
    assert dbs["status"] == "verified" and dbs["expires_on"] == add_months(issued, 12).isoformat()
    assert dbs["verified_by"] and dbs["issued_on"] == issued.isoformat()
    after = await Providers(db).get(p.id)
    assert after and can_take(after, cleaning).ok
    msg = await db["outbox"].find_one({"template_id": "document_verified"})
    expiry = add_months(issued, 12)
    assert msg and msg["body"].endswith(
        f"we've checked your basic DBS check. Thanks, you're all set until {expiry.day} {expiry:%B %Y}."
    )
    assert await db["audit_log"].count_documents({"action": "provider.document_verified"}) == 1


async def test_insurance_needs_its_expiry_and_cant_be_in_the_past(jo, db, catalogue):
    p = await make_provider(db, "Sue Palmer", "+447700900208", ["hedges"])
    await Providers(db).set_document(p.id, ProviderDocument(type="insurance", status="pending"))
    r = await jo.post(f"/api/admin/providers/{p.id}/documents/insurance/verify", json={})
    assert r.status_code == 422
    r = await jo.post(f"/api/admin/providers/{p.id}/documents/insurance/verify", json={"expires_on": "2026-01-01"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "expired"
    ok(await jo.post(f"/api/admin/providers/{p.id}/documents/insurance/verify", json={"expires_on": "2027-11-19"}))
    r = await jo.post(f"/api/admin/providers/{p.id}/documents/waste_carrier/verify", json={"expires_on": "2027-11-19"})
    assert r.status_code == 200  # make_provider holds every document
    unknown = await make_provider(db, "Ray Mills", "+447700900206", ["mowing"], docs=[])
    r = await jo.post(
        f"/api/admin/providers/{unknown.id}/documents/insurance/verify", json={"expires_on": "2027-11-19"}
    )
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_document"


async def test_rejecting_a_document_tells_the_provider_why(jo, db, catalogue):
    p = await make_provider(db, "Steve Collins", "+447700900205", ["mowing"])
    d = ok(
        await jo.post(
            f"/api/admin/providers/{p.id}/documents/insurance/reject", json={"reason": "The certificate is blurred"}
        )
    )
    ins = next(x for x in d["documents"] if x["type"] == "insurance")
    assert (ins["status"], ins["note"]) == ("rejected", "The certificate is blurred")
    msg = await db["outbox"].find_one({"template_id": "document_rejected"})
    assert (
        msg
        and "we couldn't accept your public liability insurance: The certificate is blurred. Please upload"
        in msg["body"]
    )
    assert d["insurance"]["status"] == "missing" and "Not yet checked: Public liability insurance" in d["issues"]


async def test_suspend_and_reinstate(jo, db, catalogue):
    p = await make_provider(db, "Jan Kowalski", "+447700900211", ["mowing"], status="payouts_paused")
    mowing = await Categories(db).get("mowing")
    d = ok(await jo.post(f"/api/admin/providers/{p.id}/suspend", json={"reason": "Two no-shows this month"}))
    assert (d["status"], d["status_reason"]) == ("suspended", "Two no-shows this month")
    assert not can_take(await Providers(db).get(p.id), mowing).ok  # type: ignore[arg-type]
    r = await jo.post(f"/api/admin/providers/{p.id}/suspend", json={"reason": "Again"})
    assert r.status_code == 409
    d = ok(await jo.post(f"/api/admin/providers/{p.id}/reinstate"))
    assert d["status"] == "payouts_paused" and d["status_reason"] is None  # back to how they were
    sent = [m["template_id"] async for m in db["outbox"].find({"related.provider_id": p.id}).sort("created_at", 1)]
    assert sent == ["account_suspended", "account_reinstated"]
    actions = [a["action"] async for a in db["audit_log"].find().sort("at", 1)]
    assert actions == ["provider.suspended", "provider.reinstated"]
    assert (await jo.post(f"/api/admin/providers/{p.id}/reinstate")).status_code == 409


async def test_reminders(jo, db, catalogue):
    p = await make_provider(db, "Alan Pryce", "+447700900210", ["mowing"])
    soon = london_today() + timedelta(days=9)
    await Providers(db).set_document(p.id, ProviderDocument(type="insurance", status="verified", expires_on=soon))
    out = ok(await jo.post(f"/api/admin/providers/{p.id}/nudge", json={"kind": "insurance_reminder"}))
    assert out["template_id"] == "provider_nudge" and out["recipient"]["phone"] == "+447700900210"
    assert f"your public liability insurance runs out on {soon.day} {soon:%B %Y}" in out["body"]
    assert out["body"].endswith("https://dev.example.test/p/me")
    out = ok(
        await jo.post(
            f"/api/admin/providers/{p.id}/nudge", json={"kind": "tax_details", "note": "Ring us on 01494 000000."}
        )
    )
    assert out["body"] == "OneQuickJob: Ring us on 01494 000000. https://dev.example.test/p/signup"
    assert await db["audit_log"].count_documents({"action": "provider.nudged"}) == 2


async def test_provider_page_and_payment_account(jo, db, catalogue):
    p = await make_provider(db, "Ken Ashworth", "+447700900212", ["cleaning"], docs=["insurance"], status="signing_up")
    d = ok(await jo.get(f"/api/admin/providers/{p.id}"))
    assert d["phone"] == "07700 900212" and d["payout_account_status"] == "none"
    assert [x["type"] for x in d["documents"]] == ["identity", "insurance", "dbs_basic"]
    assert next(x for x in d["documents"] if x["type"] == "dbs_basic")["status"] == "missing"
    link = ok(await jo.post(f"/api/admin/providers/{p.id}/payment-account"))
    assert link["account_id"].startswith("acct_fake_") and link["url"].endswith("?onboarding=done")
    d = ok(await jo.post(f"/api/admin/providers/{p.id}/payment-account/sync"))
    assert (d["payout_account_status"], d["payout_account_id"]) == ("enabled", link["account_id"])
    again = ok(await jo.post(f"/api/admin/providers/{p.id}/payment-account"))
    assert again["account_id"] == link["account_id"]  # not a second account
    assert await db["audit_log"].count_documents({"action": "provider.payment_account_created"}) == 1
    assert (await jo.get("/api/admin/providers/nope")).status_code == 404


def test_add_months_matches_the_dbs_rule():
    assert add_months(date(2025, 10, 31), 12) == date(2026, 10, 31)
