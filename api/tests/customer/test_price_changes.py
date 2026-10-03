"""Ruling A12: a raised guide price needs the customer's approval. The admin's raise creates a
pending price change; the customer approves it (the guide changes and the job goes out again
to eligible providers at the new price) or declines it (the original guide stands)."""

import pytest

from app.repos import JobRequests
from app.services import marketplace
from tests.admin.conftest import jo  # noqa: F401 (the signed-in admin client)
from tests.conftest import make_settings
from tests.customer.helpers import make_request_via_api, signed_in_with_card
from tests.factories import make_provider


@pytest.fixture
async def open_windows_request(client, db, catalogue):
    """A windows request (£22 a clean, first clean £33) with one eligible provider."""
    sue = await make_provider(db, "Sue Palmer", "+447700900208", ["windows"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client, "windows")
    assert (detail["guide_pence"], detail["first_pence"]) == (2200, 3300)
    return detail, sue


async def test_a_raise_waits_for_the_customer(client, db, jo, open_windows_request):  # noqa: F811
    detail, _sue = open_windows_request
    r = await jo.post(f"/api/admin/requests/{detail['ref']}/raise-guide", json={"percent": 10})
    assert r.status_code == 200 and r.json()["awaiting_customer"] is True
    msg = await db["outbox"].find_one({"template_id": "guide_raise_proposed"})
    assert msg["recipient"]["phone"] == "+447700900123"
    assert "we suggest raising the guide price to £24 (first visit £36) (it's £22 now)" in msg["body"]
    assert f"/requests/{detail['ref']}" in msg["body"]
    view = (await client.get(f"/api/c/requests/{detail['ref']}")).json()
    assert view["guide_pence"] == 2200
    assert view["price_change"] == {
        **view["price_change"],
        "guide_pence": 2400,
        "first_pence": 3600,
        "from_guide_pence": 2200,
    }
    assert view["timeline"][-1]["text"] == "We suggested raising the guide price to £24"
    overview = (await jo.get("/api/admin/overview")).json()
    waiting = [w for w in overview["waiting"] if w["request_ref"] == detail["ref"]]
    assert not waiting or waiting[0]["why"].startswith("Awaiting customer")


async def test_approving_raises_the_guide_and_sends_the_job_out_again(client, db, jo, open_windows_request):  # noqa: F811
    detail, sue = open_windows_request
    alerts_before = await db["outbox"].count_documents({"template_id": "job_alert"})
    assert alerts_before == 1
    await jo.post(f"/api/admin/requests/{detail['ref']}/raise-guide", json={"percent": 10})
    r = await client.post(f"/api/c/requests/{detail['ref']}/price-change/approve")
    assert r.status_code == 200, r.text
    view = r.json()
    assert (view["guide_pence"], view["first_pence"]) == (2400, 3600) and view["price_change"] is None
    assert (
        view["timeline"][-1]["text"]
        == "You approved a guide price of £24, and we've sent it to checked providers near HP15 again"
    )
    alerts = await db["outbox"].find({"template_id": "job_alert"}).sort("created_at", 1).to_list()
    assert len(alerts) == 2 and alerts[-1]["recipient"]["phone"] == "+447700900208"
    assert "Guide price £24, you'd get £20.40." in alerts[-1]["body"]
    assert await db["audit_log"].count_documents({"action": "request.guide_raise_approved"}) == 1
    out = await marketplace.accept_at_guide(db, make_settings(), detail["ref"], sue)
    assert out.booking.price_pence == 2400 and out.booking.first_price_pence == 3600
    again = await client.post(f"/api/c/requests/{detail['ref']}/price-change/approve")
    assert again.status_code == 409


async def test_declining_keeps_the_original_guide(client, db, jo, open_windows_request):  # noqa: F811
    detail, _sue = open_windows_request
    await jo.post(f"/api/admin/requests/{detail['ref']}/raise-guide", json={"percent": 10})
    r = await client.post(f"/api/c/requests/{detail['ref']}/price-change/decline")
    assert r.status_code == 200
    view = r.json()
    assert view["guide_pence"] == 2200 and view["price_change"] is None
    assert view["timeline"][-1]["text"] == "You kept the guide price at £22"
    stored = await JobRequests(db).by_ref(detail["ref"])
    assert stored.price_change.status == "declined"
    assert await db["outbox"].count_documents({"template_id": "job_alert"}) == 1, "nothing sent again"
    # The team can suggest a raise again later.
    assert (await jo.post(f"/api/admin/requests/{detail['ref']}/raise-guide", json={"percent": 20})).status_code == 200


async def test_a_booked_request_cant_take_a_waiting_raise(client, db, jo, open_windows_request):  # noqa: F811
    detail, sue = open_windows_request
    await jo.post(f"/api/admin/requests/{detail['ref']}/raise-guide", json={"percent": 10})
    out = await marketplace.accept_at_guide(db, make_settings(), detail["ref"], sue)
    assert out.booking.price_pence == 2200, "booked at the guide the provider saw"
    r = await client.post(f"/api/c/requests/{detail['ref']}/price-change/approve")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_open"
    assert (await client.get(f"/api/c/requests/{detail['ref']}")).json()["price_change"] is None


async def test_no_raise_to_answer(client, db, open_windows_request):
    detail, _sue = open_windows_request
    r = await client.post(f"/api/c/requests/{detail['ref']}/price-change/approve")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_price_change"
