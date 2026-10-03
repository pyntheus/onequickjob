"""Overview and dispatch: figures from real data, the waiting list, the WhatsApp text and
raising a guide price (audit-logged, whole pounds, first visit scaled as for a counter)."""

from datetime import timedelta

from app.core import money
from app.core.timeutil import utcnow
from app.models.providers import ProviderDocument
from app.repos import JobRequests, Providers, Visits
from app.services import marketplace
from tests.admin.conftest import ok
from tests.conftest import make_settings, sign_in
from tests.factories import make_customer, make_provider, make_request
from tests.payments.helpers import card_customer, finished_visit, payable_provider


async def aged(db, req, hours: int):
    await JobRequests(db).update(req.id, {"created_at": utcnow() - timedelta(hours=hours)})
    return await JobRequests(db).get(req.id)


async def test_admin_only(client, db, catalogue):
    assert (await client.get("/api/admin/overview")).status_code == 401
    await sign_in(client, db, "07700 900456")
    r = await client.get("/api/admin/overview")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "admins_only"


async def test_overview_from_real_data(jo, db, catalogue):
    from app.adapters.payments.fake import FakeGateway
    from app.payments import charging

    customer = await card_customer(db)
    provider = await payable_provider(db)
    v = await finished_visit(db, customer, provider)
    await charging.charge_visit(db, make_settings(), FakeGateway(db), v.id)
    old = await aged(db, await make_request(db, customer, "hedges", {"length": 12, "height": "above"}), 5)
    await make_request(db, customer, "mowing")  # new: still being answered, not "waiting"
    expiring = utcnow().date() + timedelta(days=9)
    await Providers(db).set_document(
        provider.id, ProviderDocument(type="insurance", status="verified", expires_on=expiring)
    )
    await make_provider(db, "Jan Kowalski", "+447700900211", ["mowing"], status="payouts_paused")

    d = ok(await jo.get("/api/admin/overview"))
    kpis = {k["label"]: k for k in d["kpis"]}
    assert kpis["Requests"]["value"] == "2"
    assert kpis["Job value"]["value"] == "£30" and kpis["Our revenue"]["value"] == "£4.50"
    assert kpis["Our revenue"]["sub"] == "15% of job value"
    [waiting] = d["waiting"]
    assert waiting["request_ref"] == old.ref and waiting["age_text"] == "5 hours"
    assert waiting["brief"] == "12 m, taller than a person, my side only"
    assert waiting["why"] == "No providers in reach were alerted. Nobody has seen it."  # the factory alerts nobody
    issues = {(a["short"], a["issue"], a["action"]) for a in d["attention"]}
    assert ("Dave H.", f"Insurance expires on {expiring.day} {expiring:%B}", "Send reminder") in issues
    assert ("Jan K.", "Tax details missing, so payouts are paused", "Chase") in issues
    assert d["attention"][0]["tone"] == "danger"  # the worst first
    assert {t["code"] for t in d["districts"]} >= {"HP15"}


async def test_failed_charges_show_for_a_retry(jo, db, catalogue):
    from app.adapters.payments.fake import FakeGateway
    from app.payments import charging
    from tests.payments.helpers import rename_card_holder

    customer = await card_customer(db, "Dee Decline", "+447700900301")
    v = await finished_visit(db, customer, await payable_provider(db))
    await charging.charge_visit(db, make_settings(), FakeGateway(db), v.id)
    [issue] = ok(await jo.get("/api/admin/overview"))["payments"]
    assert (issue["visit_id"], issue["status"], issue["customer_name"]) == (v.id, "failed", "Dee D.")
    await rename_card_holder(db, customer, "Dee")
    st = ok(await jo.post(f"/api/admin/visits/{v.id}/retry-charge"))
    assert st == {"visit_id": v.id, "status": "succeeded", "failure_reason": None}
    assert ok(await jo.get("/api/admin/overview"))["payments"] == []


async def test_whatsapp_text_for_the_providers_group(jo, db, catalogue):
    customer = await make_customer(db)
    req = await make_request(db, customer, "hedges", {"length": 20, "height": "above", "sides": "both"})
    text = ok(await jo.get(f"/api/admin/requests/{req.ref}/whatsapp"))["text"]
    keep = money.format_pounds(money.split(req.guide_pence).provider_pence)
    assert text == (
        "Job going: hedge trimming in Hazlemere, HP15. 20 m, taller than a person, both sides and the top. "
        f"Guide price {money.format_pounds(req.guide_pence)}, you'd get {keep}. "
        f"Take it here: https://dev.example.test/p/j/{req.ref}"
    )
    assert "?t=" not in text  # a group link signs nobody in
    assert (await jo.get("/api/admin/requests/R-0000/whatsapp")).status_code == 404


async def test_raise_the_guide_ten_percent(jo, db, catalogue):
    """A12 (L1 change): the raise is proposed to the customer; the guide moves only on approval."""
    customer = await make_customer(db)
    req = await make_request(db, customer, "windows")  # £22 a clean, first clean £33
    assert (req.guide_pence, req.first_pence) == (2200, 3300)
    out = ok(await jo.post(f"/api/admin/requests/{req.ref}/raise-guide", json={"note": "Ladder work"}))
    assert out["guide_pence"] == 2200 and out["awaiting_customer"] is True
    assert out["proposed_guide_pence"] == 2400  # £24.20 to whole pounds
    assert out["why"].startswith("Awaiting customer")
    after = await JobRequests(db).get(req.id)
    assert after and (after.guide_pence, after.first_pence) == (2200, 3300), "unchanged until the customer approves"
    pc = after.price_change
    assert pc and (pc.status, pc.guide_pence, pc.first_pence) == ("pending", 2400, 3600)  # 3300 x 24/22, whole pounds
    assert after.events[-1].kind == "price_change_proposed" and after.events[-1].price_pence == 2400
    log = await db["audit_log"].find_one({"action": "request.guide_raise_proposed"})
    assert log and log["before"] == {"guide_pence": 2200, "first_pence": 3300}
    assert log["after"]["guide_pence"] == 2400 and log["note"] == "Ladder work"
    assert log["actor"]["name"] == "Jo Morgan"


async def test_a_raise_beats_a_stale_acceptance_and_closed_requests_cant_be_raised(jo, db, catalogue):
    from app.customer import price_changes
    from app.repos import Users

    customer = await make_customer(db)
    provider = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    req = await make_request(db, customer, "mowing")
    stale_guide = req.guide_pence
    ok(await jo.post(f"/api/admin/requests/{req.ref}/raise-guide", json={"percent": 20}))
    again = await jo.post(f"/api/admin/requests/{req.ref}/raise-guide", json={"percent": 20})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "awaiting_customer"
    pending = await JobRequests(db).get(req.id)
    await price_changes.approve(
        db, make_settings(), pending, await Users(db).get(customer.user_id), pending.price_change.id
    )
    # A provider who read the old guide gets price_changed, not the old price.
    claimed = await marketplace.claim_request(
        db, req.id, provider_id=provider.id, price_pence=stale_guide, first_price_pence=None, via="guide",
        expect_guide_pence=stale_guide,
    )  # fmt: skip
    assert claimed is None
    await marketplace.accept_at_guide(db, make_settings(), req.ref, provider)
    r = await jo.post(f"/api/admin/requests/{req.ref}/raise-guide", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_open"
    booked = await JobRequests(db).get(req.id)
    assert booked and booked.booked and booked.booked.price_pence == round(stale_guide * 1.2 / 100) * 100
    assert await Visits(db).count({"booking_id": booked.booked.booking_id}) >= 1
