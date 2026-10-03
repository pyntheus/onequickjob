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
    assert by["Alan P."]["insurance"] == {"status": "warn", "expires_on": soon.isoformat(), "renewal_waiting": False}
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


async def test_a_renewal_waiting_shows_beside_the_checked_copy_not_as_missing(jo, db, catalogue):
    """Session S, item 3c: with an in-date insurance copy and a renewal waiting for a check, the
    table shows the in-date copy and "renewal waiting"; the page shows the renewal to check with
    the checked copy's expiry; the overview asks for a check, not a reminder."""
    alan = await make_provider(db, "Alan Pryce", "+447700900210", ["mowing"])
    await Providers(db).patch(alan.id, {"tax": TaxDetails(complete=True).model_dump(mode="python")})
    soon = london_today() + timedelta(days=9)
    renewal = ProviderDocument(
        type="insurance", status="pending", file_id="f-renewal", expires_on=soon + timedelta(days=365)
    )
    current = ProviderDocument(type="insurance", status="verified", file_id="f-current", expires_on=soon)
    others = [d for d in alan.documents if d.type != "insurance"]
    await Providers(db).patch(
        alan.id, {"documents": [d.model_dump(mode="python") for d in [*others, renewal, current]]}
    )

    [row] = ok(await jo.get("/api/admin/providers"))
    assert row["insurance"] == {"status": "warn", "expires_on": soon.isoformat(), "renewal_waiting": True}
    assert [r["short"] for r in ok(await jo.get("/api/admin/providers?filter=attention"))] == ["Alan P."]
    d = ok(await jo.get(f"/api/admin/providers/{alan.id}"))
    ins = next(x for x in d["documents"] if x["type"] == "insurance")
    assert ins["status"] == "pending" and ins["current_expires_on"] == soon.isoformat()
    assert not any("Not yet checked" in i for i in d["issues"])
    attention = [a for a in ok(await jo.get("/api/admin/overview"))["attention"] if a["short"] == "Alan P."]
    assert [(a["issue"], a["action"]) for a in attention] == [("Insurance renewal to check", "Check it")]

    # Checking the renewal replaces the old copy: in date for a year, nothing waiting.
    d = ok(await jo.post(f"/api/admin/providers/{alan.id}/documents/insurance/verify", json={}))
    assert d["insurance"] == {
        "status": "ok",
        "expires_on": (soon + timedelta(days=365)).isoformat(),
        "renewal_waiting": False,
    }
    # No checked copy in date and an upload waiting: "renewal", not "missing".
    lapsed = ProviderDocument(type="insurance", status="pending", file_id="f-late")
    await Providers(db).patch(alan.id, {"documents": [d.model_dump(mode="python") for d in [*others, lapsed]]})
    [row] = ok(await jo.get("/api/admin/providers"))
    assert row["insurance"]["status"] == "renewal" and row["insurance"]["renewal_waiting"] is False


async def _with_helper(db, docs: list[ProviderDocument], status: str = "checking"):
    from app.models.providers import Helper
    from app.models.users import User
    from app.repos import Users

    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing", "cleaning"])
    tom = User(name="Tom Hughes", phone="+447700900220", roles=[], helper_of=dave.id)
    await Users(db).insert(tom)
    helper = Helper(user_id=tom.id, name="Tom Hughes", relationship="Son", status=status, documents=docs)  # type: ignore[arg-type]
    await Providers(db).update(dave.id, {}, push={"helpers": helper.model_dump(mode="python")})
    return dave, tom


async def test_admins_check_a_helpers_documents_and_mark_them_ready(jo, db, catalogue):
    """Session S, item 3b: a helper's documents are verified or rejected like a provider's (the
    helper is texted), and an admin marks them ready once their ID is checked (the provider is
    texted). Each step is audit-logged."""
    upload = [
        ProviderDocument(type="identity", status="pending", file_id="f-id"),
        ProviderDocument(type="dbs_basic", status="pending", file_id="f-dbs"),
    ]
    dave, tom = await _with_helper(db, upload)
    d = ok(await jo.get(f"/api/admin/providers/{dave.id}"))
    [h] = d["helper_checks"]
    assert (h["name"], h["status"], h["phone"], h["can_mark_ready"]) == (
        "Tom Hughes",
        "checking",
        "07700 900220",
        False,
    )
    assert {x["type"]: x["status"] for x in h["documents"]}["identity"] == "pending"
    r = await jo.post(f"/api/admin/providers/{dave.id}/helpers/{tom.id}/ready")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "identity_not_checked"

    d = ok(await jo.post(f"/api/admin/providers/{dave.id}/helpers/{tom.id}/documents/identity/verify", json={}))
    [h] = d["helper_checks"]
    assert {x["type"]: x["status"] for x in h["documents"]}["identity"] == "verified" and h["can_mark_ready"]
    msg = await db["outbox"].find_one({"template_id": "document_verified"})
    assert msg["recipient"]["phone"] == "+447700900220" and "we've checked your identity" in msg["body"]
    rejected = ok(
        await jo.post(
            f"/api/admin/providers/{dave.id}/helpers/{tom.id}/documents/dbs_basic/reject", json={"reason": "Too blurry"}
        )
    )
    dbs = next(x for x in rejected["helper_checks"][0]["documents"] if x["type"] == "dbs_basic")
    assert dbs["status"] == "rejected" and dbs["note"] == "Too blurry"
    told = await db["outbox"].find_one({"template_id": "document_rejected"})
    assert told["recipient"]["phone"] == "+447700900220" and "Too blurry." in told["body"]
    assert (await Providers(db).get(dave.id)).documents == dave.documents, "Dave's own documents are untouched"

    d = ok(await jo.post(f"/api/admin/providers/{dave.id}/helpers/{tom.id}/ready"))
    assert d["helper_checks"][0]["status"] == "ready" and d["helper_checks"][0]["can_mark_ready"] is False
    ready = await db["outbox"].find_one({"template_id": "helper_ready"})
    assert ready["recipient"]["phone"] == "+447700900201" and "we've checked Tom's details" in ready["body"]
    again = await jo.post(f"/api/admin/providers/{dave.id}/helpers/{tom.id}/ready")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_ready"
    actions = {a["action"] async for a in db["audit_log"].find({"target.user_id": tom.id})}
    assert actions == {
        "provider.helper_document_verified",
        "provider.helper_document_rejected",
        "provider.helper_ready",
    }
    assert (await jo.post(f"/api/admin/providers/{dave.id}/helpers/nobody/ready")).status_code == 404


async def test_a_ready_helper_with_checked_documents_can_be_sent_to_a_visit(jo, db, catalogue):
    """What the admin's checks are for: the round sends a ready helper to a job whose documents
    they hold (A17), and not to one whose documents they don't."""
    from app.provider.helpers import helper_missing

    dave, tom = await _with_helper(db, [ProviderDocument(type="identity", status="pending", file_id="f-id")])
    ok(await jo.post(f"/api/admin/providers/{dave.id}/helpers/{tom.id}/documents/identity/verify", json={}))
    ok(await jo.post(f"/api/admin/providers/{dave.id}/helpers/{tom.id}/ready"))
    helper = (await Providers(db).get(dave.id)).helpers[0]
    assert helper_missing(helper, catalogue["mowing"]) == ["insurance"]
    assert helper_missing(helper, catalogue["cleaning"]) == ["insurance", "dbs_basic"]
