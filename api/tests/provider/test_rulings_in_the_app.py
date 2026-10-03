"""The rulings made after L2's first report, as the provider app shows them: a counter that
lapses because its provider can't take the job (A9), a raised guide price waiting for the
customer and then approved (A12), and an accepted change of frequency (A10). Each goes through
the real endpoints of the lane that owns it, then reads the provider's own screens."""

from app.repos import Providers
from app.services import marketplace
from tests.admin.conftest import jo  # noqa: F401 (the signed-in admin client)
from tests.conftest import make_settings
from tests.customer.helpers import make_request_via_api, signed_in_with_card
from tests.customer.test_plan_changes import _mowing_plan, _preview
from tests.factories import make_provider
from tests.provider.conftest import DAVE_PHONE, MIKE_PHONE, client_for


async def test_a_lapsed_counter_shows_on_the_offer_with_the_reason(app, client, db, catalogue):
    mike = await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    offer = await marketplace.make_counter(db, make_settings(), detail["ref"], mike, price_pence=3600, reasons=[])
    p = await Providers(db).get(mike.id)
    await Providers(db).patch(
        mike.id, {"documents": [d.model_dump(mode="python") for d in p.documents if d.type != "insurance"]}
    )
    assert (await client.post(f"/api/c/offers/{offer.id}/accept")).status_code == 409  # A9: it lapses

    async with client_for(app, db, MIKE_PHONE) as mc:
        r = await mc.get(f"/api/p/requests/{detail['ref']}")
        assert r.status_code == 200, r.text
        view = r.json()
        assert view["card"]["state"] == "lapsed" and view["request_status"] == "open"
        note = "Your suggested price of £36 lapsed because you can't take this job at the moment."
        assert view["counter_note"] == note
        assert view["can_take"] is False and view["my_counter"] is None
    text = await db["outbox"].find_one({"template_id": "counter_lapsed"})
    assert text["body"].endswith("/p/me"), "the text's link opens the provider app's documents"


async def test_a_raised_guide_shows_only_once_the_customer_approves(app, client, db, jo, catalogue):  # noqa: F811
    sue = await make_provider(db, "Sue Palmer", "+447700900208", ["windows"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client, "windows")
    ref = detail["ref"]
    await jo.post(f"/api/admin/requests/{ref}/raise-guide", json={"percent": 10})

    async with client_for(app, db, "+447700900208") as sc:
        waiting = (await sc.get(f"/api/p/requests/{ref}")).json()
        assert (waiting["card"]["guide_pence"], waiting["first_pence"]) == (2200, 3300), "the guide that stands now"
        assert waiting["counter_min_pence"] == 1800 and waiting["card"]["provider_pence"] == 1870

        change = (await client.get(f"/api/c/requests/{ref}")).json()["price_change"]["change_id"]
        r = await client.post(f"/api/c/requests/{ref}/price-change/approve", json={"change_id": change})
        assert r.status_code == 200, r.text

        raised = (await sc.get(f"/api/p/requests/{ref}")).json()
        assert (raised["card"]["guide_pence"], raised["first_pence"]) == (2400, 3600)
        assert raised["counter_min_pence"] == 1900 and raised["card"]["provider_pence"] == 2040
        home = (await sc.get("/api/p/home")).json()
        assert [(j["request_ref"], j["guide_pence"]) for j in home["new_jobs"]] == [(ref, 2400)]
    alert = (await db["outbox"].find({"template_id": "job_alert"}).sort("created_at", -1).to_list())[0]
    assert f"/p/j/{ref}?t=" in alert["body"], "the alert sent again opens the offer in the provider app"
    assert sue


async def test_an_accepted_change_of_frequency_shows_on_the_round(app, client, db, catalogue):
    dave, booking = await _mowing_plan(client, db)
    sid = booking.series_id
    price = await _preview(client, sid, "weekly")
    await client.patch(f"/api/c/plans/{sid}", json={"frequency": "weekly", "expected_price_pence": price})
    msg = await db["outbox"].find_one({"template_id": "plan_change_proposed"})
    token = msg["body"].split("/p/plan-change/")[1].split()[0]
    assert (await client.post(f"/api/c/plan-changes/{token}/accept")).status_code == 200

    async with client_for(app, db, DAVE_PHONE) as dc:
        visits = await db["visits"].find({"series_id": sid, "status": "scheduled", "is_first": False}).to_list()
        later = max(visits, key=lambda v: v["local_date"])
        r = await dc.get(f"/api/p/visits/{later['_id']}")
        assert r.status_code == 200, r.text
        assert r.json()["price_pence"] == price
    assert dave
