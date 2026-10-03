"""A10's plan-change page lives in the provider app: the provider's text links to
/p/plan-change/{token}, and that token alone answers it (no sign-in), as before."""

from tests.conftest import make_settings
from tests.customer.test_plan_changes import _mowing_plan, _preview


async def test_the_providers_text_links_into_the_provider_app(client, db, catalogue):
    _dave, booking = await _mowing_plan(client, db)
    sid = booking.series_id
    price = await _preview(client, sid, "weekly")
    r = await client.patch(f"/api/c/plans/{sid}", json={"frequency": "weekly", "expected_price_pence": price})
    assert r.status_code == 200, r.text
    msg = await db["outbox"].find_one({"template_id": "plan_change_proposed"})
    base = make_settings().public_base_url.rstrip("/")
    assert f"{base}/p/plan-change/" in msg["body"]
    token = msg["body"].split(f"{base}/p/plan-change/")[1].split()[0]

    client.cookies.clear()  # the provider opens the link without signing in: the token is the authority
    view = await client.get(f"/api/c/plan-changes/{token}")
    assert view.status_code == 200 and view.json()["status"] == "pending"
    done = await client.post(f"/api/c/plan-changes/{token}/accept")
    assert done.status_code == 200 and done.json()["status"] == "accepted"
