"""New jobs, the offer screen and the suggested-price preview (decisions.md A1)."""

from datetime import date

from app.models.job_requests import JobRequest
from app.models.offers import Offer
from app.repos import JobRequests, Offers, Providers
from app.services import marketplace
from tests.conftest import make_settings
from tests.factories import make_customer, make_provider, make_request
from tests.provider.conftest import MIKE_PHONE, client_for


async def _ref(dave_client, ref: str) -> dict:
    r = await dave_client.get(f"/api/p/requests/{ref}")
    assert r.status_code == 200, r.text
    return r.json()


async def test_jobs_lists_open_jobs_the_provider_can_take_nearest_first(dave_client, db, dave):
    customer = await make_customer(db)
    near = await make_request(db, customer)
    far = await make_request(db, customer, "hedges")
    far_away = far.address.model_copy(update={"lat": 51.75, "lng": -0.71, "locality": "Great Missenden"})
    await JobRequests(db).update(far.id, {"address": far_away.model_dump()})
    not_mine = await make_request(db, customer, "windows")  # not one of Dave's skills
    r = await dave_client.get("/api/p/jobs")
    assert r.status_code == 200, r.text
    refs = [c["request_ref"] for c in r.json()]
    assert refs == [near.ref], "outside the travel radius and not alerted: not listed; windows isn't his"
    card = r.json()[0]
    assert (card["guide_pence"], card["provider_pence"]) == (near.guide_pence, near.guide_pence * 85 // 100)
    assert card["area"] == "Hazlemere" and card["frequency_label"] == "Every 2 weeks"
    assert card["state"] is None and card["over_limit"] is False
    # Alerted to him (in the broadcast), so listed even though it's further than he usually goes.
    await JobRequests(db).update(far.id, {"broadcast": {"at": far.created_at, "provider_ids": [dave.id]}})
    refs = [c["request_ref"] for c in (await dave_client.get("/api/p/jobs")).json()]
    assert refs == [near.ref, far.ref]
    assert not_mine


async def test_jobs_need_the_documents_the_category_requires(dave_client, db, dave):
    customer = await make_customer(db)
    await make_request(db, customer, "cleaning")  # needs a basic DBS check
    assert len((await dave_client.get("/api/p/jobs")).json()) == 1
    docs = [d for d in dave.documents if d.type != "dbs_basic"]
    await Providers(db).patch(dave.id, {"documents": [d.model_dump(mode="python") for d in docs]})
    assert (await dave_client.get("/api/p/jobs")).json() == []
    offer = await _ref(dave_client, (await JobRequests(db).find_one({})).ref)
    assert offer["can_take"] is False and offer["missing_documents"] == ["dbs_basic"]
    assert offer["not_eligible_reasons"]


async def test_over_limit_jobs_are_marked(dave_client, db, dave):
    customer = await make_customer(db)
    req = await make_request(db, customer)
    r = await dave_client.put("/api/p/limit", json={"on": True, "period": "week", "amount_pence": 2000})
    assert r.status_code == 200 and r.json()["remaining_pence"] == 2000
    card = (await dave_client.get("/api/p/jobs")).json()[0]
    assert card["over_limit"] is True  # he'd get £26.35 with £20 left
    offer = await _ref(dave_client, req.ref)
    assert offer["over_limit_by_pence"] == req.guide_pence * 85 // 100 - 2000


async def test_the_offer_screen_hides_the_address_until_the_job_is_yours(dave_client, db, dave):
    customer = await make_customer(db)
    req = await make_request(db, customer)
    offer = await _ref(dave_client, req.ref)
    assert offer["address_line"] is None and "Orchard" not in str(offer)
    assert offer["approx"] == {"lat": 51.65, "lng": -0.71}
    assert offer["customer"]["name"] == "Sarah W." and offer["fee_percent"] == 15
    labels = [f["label"] for f in offer["facts"]]
    assert labels[0] == "Lawn" and "Grass" in labels and "Clippings" in labels and labels[-1] == "Estimate"
    assert offer["counter_min_pence"] == 2500 and offer["counter_max_pence"] == 9300  # guide £31
    assert offer["can_take"] and offer["can_counter"] and offer["request_status"] == "open"

    accepted = await dave_client.post(f"/api/p/requests/{req.ref}/accept")
    assert accepted.status_code == 200, accepted.text
    offer = await _ref(dave_client, req.ref)
    assert offer["booked_by_me"] and offer["card"]["state"] == "yours"
    assert offer["address_line"] == "12 Orchard Way, Hazlemere, HP15 7QT"
    assert offer["first_visit_text"].startswith("Added to ")
    assert [c["state"] for c in (await dave_client.get("/api/p/jobs")).json()] == ["yours"]


async def test_opening_a_job_records_one_view(dave_client, db, dave):
    customer = await make_customer(db)
    req = await make_request(db, customer)
    for _ in range(3):
        await _ref(dave_client, req.ref)
    stored = await JobRequests(db).get(req.id)
    assert stored.viewed_by == [dave.id]
    assert sum(1 for e in stored.events if e.kind == "viewed") == 1


async def test_a_job_offered_directly_to_someone_else_is_private(dave_client, db, dave):
    customer = await make_customer(db)
    mike = await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"])
    req = await make_request(db, customer)
    await JobRequests(db).update(req.id, {"direct_provider_id": mike.id})
    assert (await dave_client.get(f"/api/p/requests/{req.ref}")).status_code == 404
    assert (await dave_client.get("/api/p/jobs")).json() == []


async def test_counter_preview_shows_the_first_visit_consequence_from_the_api(dave_client, db, dave):
    """A1: the provider sets only the per-visit price; a dearer first visit scales by the same
    ratio, worked out by marketplace.scaled_first_price. The web shows this sentence as given."""
    customer = await make_customer(db)
    req = await make_request(db, customer, "cleaning")  # guide £66 a clean, first visit £88
    assert (req.guide_pence, req.first_pence) == (6600, 8800)
    r = await dave_client.get(f"/api/p/requests/{req.ref}/counter-preview", params={"price_pence": 7200})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["valid"] and p["first_price_pence"] == 9600  # 88 x 72 / 66 = 96
    assert p["text"] == "Your price: £72 a clean. The first visit becomes £96."
    assert (p["provider_pence"], p["first_provider_pence"]) == (6120, 8160)
    assert p["first_price_pence"] == marketplace.scaled_first_price(6600, 8800, 7200)

    # The counter the provider then sends carries exactly those prices.
    sent = await dave_client.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 7200})
    assert sent.status_code == 200, sent.text
    assert (sent.json()["price_pence"], sent.json()["first_price_pence"]) == (7200, 9600)


async def test_counter_preview_for_the_brief_example(dave_client, db, dave):
    """ "Your price: £36 a visit. The first visit becomes £66." (guide £30, first visit £55)."""
    customer = await make_customer(db)
    req = await make_request(db, customer)
    await JobRequests(db).update(req.id, {"guide_pence": 3000, "first_pence": 5500})
    p = (await dave_client.get(f"/api/p/requests/{req.ref}/counter-preview", params={"price_pence": 3600})).json()
    assert p["text"] == "Your price: £36 a visit. The first visit becomes £66."


async def test_counter_preview_explains_prices_that_cant_be_sent(dave_client, db, dave):
    customer = await make_customer(db)
    req = await make_request(db, customer)  # guide £31
    for price, problem in [
        (3100, "That's the guide price. Accept it instead."),
        (2400, "Suggest a whole-pound price between £25 and £93."),
        (3650, "Suggest a whole-pound price between £25 and £93."),
    ]:
        p = (await dave_client.get(f"/api/p/requests/{req.ref}/counter-preview", params={"price_pence": price})).json()
        assert not p["valid"] and p["problem"] == problem and p["first_price_pence"] is None
    p = (await dave_client.get(f"/api/p/requests/{req.ref}/counter-preview", params={"price_pence": 2500})).json()
    assert p["valid"] and p["text"] == "Your price: £25 a visit."


async def test_card_states_for_a_waiting_price_a_lost_job_and_a_lapsed_price(app, dave_client, db, dave):
    customer = await make_customer(db)
    mike = await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"])
    countered = await make_request(db, customer)
    taken = await make_request(db, customer)
    lapsed = await make_request(db, customer)
    for req in (countered, taken, lapsed):
        r = await dave_client.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700})
        assert r.status_code == 200, r.text
    await marketplace.accept_at_guide(db, make_settings(), taken.ref, mike)
    # A counter lapsing while its job stays open: what L1's change does when the provider can't take it any more.
    await Offers(db).coll.update_one({"request_id": lapsed.id}, {"$set": {"status": "lapsed"}})
    states = {c["request_ref"]: c["state"] for c in (await dave_client.get("/api/p/jobs")).json()}
    assert states == {countered.ref: "countered", lapsed.ref: "lapsed", taken.ref: "taken"}
    offer = await _ref(dave_client, lapsed.ref)
    assert offer["my_counter"] is None
    assert offer["counter_note"].startswith("Your suggested price of £37 lapsed")
    offer = await _ref(dave_client, countered.ref)
    assert offer["my_counter"]["price_pence"] == 3700 and offer["counter_note"] is None


async def test_a_declined_price_says_the_job_is_still_open(dave_client, db, dave):
    customer = await make_customer(db)
    req = await make_request(db, customer)
    offer = (await dave_client.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700})).json()
    await marketplace.decline_counter(db, make_settings(), offer["id"], customer)
    o = await _ref(dave_client, req.ref)
    assert "would rather wait for the guide price" in o["counter_note"] and o["can_take"]


async def test_route_hint_finds_another_visit_within_a_mile(dave_client, db, dave):
    from tests.provider.conftest import book

    customer = await make_customer(db)
    other = await make_customer(db, "Margaret Turner", "+447700900133")
    await book(db, other, dave)  # a regular at the same address, from tomorrow
    await make_request(db, customer)
    card = (await dave_client.get("/api/p/jobs")).json()[0]
    assert card["route_hint"] and card["route_hint"].startswith("0.1 miles from your 9:00 on ")


async def test_cover_requests_show_as_cover_and_cant_be_countered(app, db, dave):
    from tests.provider.conftest import book, make_dave

    customer = await make_customer(db)
    mike = await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"])
    _, visit = await book(db, customer, dave)
    req = await make_request(db, customer)
    cover = JobRequest.model_validate(
        {**req.model_dump(exclude={"id", "ref"}), "ref": "R-9201", "cover_for_visit_id": visit.id}
    )
    await JobRequests(db).insert(cover)
    async with client_for(app, db, MIKE_PHONE) as mc:
        o = (await mc.get("/api/p/requests/R-9201")).json()
    assert o["is_cover"] and not o["can_counter"] and o["can_take"]
    assert o["cover_text"].startswith("Cover for Dave H.'s regular customer on ")
    assert o["card"]["frequency_label"].startswith("Cover, ")
    assert mike and make_dave and date


async def test_helpers_cant_see_jobs(app, db, dave):
    from tests.provider.conftest import TOM_PHONE, add_tom

    await add_tom(db, dave)
    async with client_for(app, db, TOM_PHONE) as tc:
        r = await tc.get("/api/p/jobs")
        assert r.status_code == 403 and r.json()["detail"]["code"] == "helpers_cant"
        home = (await tc.get("/api/p/home")).json()
        assert home["helper"] and home["new_jobs"] == [] and home["greeting"].endswith("Tom")


async def test_a_pending_offer_appears_on_the_offer(dave_client, db, dave):
    customer = await make_customer(db)
    req = await make_request(db, customer)
    await dave_client.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700})
    stored = await Offers(db).find_one({"request_id": req.id})
    assert isinstance(stored, Offer) and stored.status == "pending"


async def test_a_helper_sees_none_of_the_providers_money(app, db, dave):
    """Codex third review (medium): no earnings and no limit on a helper's home."""
    from tests.provider.conftest import TOM_PHONE, add_tom

    await db["providers"].update_one(
        {"_id": dave.id}, {"$set": {"earnings_limit": {"on": True, "period": "week", "amount_pence": 25000}}}
    )
    await add_tom(db, dave)
    async with client_for(app, db, TOM_PHONE) as tc:
        home = (await tc.get("/api/p/home")).json()
    assert home["week_earned_pence"] == 0 and home["limit"]["on"] is False
    assert home["limit"]["amount_pence"] == 0 and home["limit"]["earned_pence"] == 0


async def test_a_provider_who_works_none_of_the_customers_days_cant_take_the_job(app, dave_client, db, dave):
    """A23: a weekends-only provider gets no alert for a weekdays request and doesn't see it in
    their jobs; the job page says why; accepting or suggesting a price is refused, clearly. A
    counter made before they stopped working those days lapses when the customer accepts it (A9)."""
    from app.services.eligibility import alert_targets

    customer = await make_customer(db)
    req = await make_request(db, customer)  # weekdays, morning
    await Providers(db).patch(dave.id, {"working_days": ["sat", "sun"]})
    cat = await db["categories"].find_one({"_id": "mowing"})
    from app.models.categories import Category

    assert dave.id not in [t.provider.id for t in await alert_targets(db, req, Category.model_validate(cat))]
    assert req.ref not in [c["request_ref"] for c in (await dave_client.get("/api/p/jobs")).json()]
    page = await _ref(dave_client, req.ref)
    days = "This customer wants weekdays, and you don't work any weekdays. You can change your working days in Me."
    assert page["can_take"] is False and days in page["not_eligible_reasons"]
    for r in (
        await dave_client.post(f"/api/p/requests/{req.ref}/accept"),
        await dave_client.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700}),
    ):
        assert r.status_code == 403 and r.json()["detail"]["code"] == "not_eligible", r.text
        assert r.json()["detail"]["message"] == days
    assert (await JobRequests(db).get(req.id)).status == "open"

    # Back on weekdays, Dave suggests a price; then he stops working weekdays before Sarah accepts it.
    await Providers(db).patch(dave.id, {"working_days": ["mon", "tue"]})
    offer = (await dave_client.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700})).json()
    await Providers(db).patch(dave.id, {"working_days": ["sat"]})
    from tests.conftest import new_client, sign_in

    async with await new_client(app) as sc:
        await sign_in(sc, db, "+447700900123")
        r = await sc.post(f"/api/c/offers/{offer['id']}/accept")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "provider_unavailable"
    assert (await Offers(db).get(offer["id"])).status == "lapsed"
    lapsed = await db["outbox"].find_one({"template_id": "counter_lapsed"})
    assert "you don't work any weekdays" in lapsed["body"]
