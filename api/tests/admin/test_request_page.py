"""One request's admin page (A38): admins only; the customer's request with its answers and the
lawn size and method behind it; status and age; offers and counters; the timeline; the outbox
messages about it; a raise waiting for the customer; who could take it (A36). And the admin
summary's "across N lawns" (A39)."""

from datetime import timedelta

from app.admin.views import brief_for
from app.core.timeutil import utcnow
from app.repos import Categories, JobRequests, Providers
from app.services import marketplace
from tests.admin.conftest import ok
from tests.conftest import make_settings, new_client, sign_in, signed_out
from tests.factories import make_customer, make_provider, make_request

TWO_LAWNS = {"method": "paced", "lawns": [{"length": 15, "width": 10}, {"length": 10, "width": 10}]}


async def aged(db, req, hours: float):
    await JobRequests(db).update(req.id, {"created_at": utcnow() - timedelta(hours=hours)})
    return await JobRequests(db).get(req.id)


async def test_admins_only(client, app, db, catalogue):
    customer = await make_customer(db)
    req = await make_request(db, customer)
    assert signed_out(await client.get(f"/api/admin/requests/{req.id}"))
    async with await new_client(app) as c:
        await sign_in(c, db, "07700 900123")  # Sarah, the customer who made it
        r = await c.get(f"/api/admin/requests/{req.id}")
        assert r.status_code == 403 and r.json()["detail"]["code"] == "admins_only"
    await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    async with await new_client(app) as c:
        await sign_in(c, db, "07700 900201")
        r = await c.get(f"/api/admin/requests/{req.id}")
        assert r.status_code == 403 and r.json()["detail"]["code"] == "admins_only"


async def test_by_id_or_reference_and_404(jo, db, catalogue):
    customer = await make_customer(db)
    req = await make_request(db, customer)
    assert ok(await jo.get(f"/api/admin/requests/{req.id}"))["ref"] == req.ref
    assert ok(await jo.get(f"/api/admin/requests/{req.ref}"))["request_id"] == req.id
    r = await jo.get("/api/admin/requests/R-9999")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"


async def test_the_request_its_lawn_and_where_it_stands(jo, db, catalogue):
    customer = await make_customer(db)
    req = await aged(db, await make_request(db, customer, "mowing", {"grassState": "long"}, TWO_LAWNS), 5)
    d = ok(await jo.get(f"/api/admin/requests/{req.id}"))
    assert (d["ref"], d["status"], d["age_text"], d["waiting"]) == (req.ref, "open", "5 hours", True)
    who = ("Lawn mowing", "Sarah Whitfield", "+447700900123")
    assert (d["category_name"], d["customer_name"], d["customer_phone"]) == who
    assert d["address"]["line1"] == "12 Orchard Way" and d["address"]["postcode"] == "HP15 7QT"
    assert d["when_text"] == "Weekday mornings"
    assert (d["guide_pence"], d["first_pence"]) == (req.guide_pence, req.first_pence)
    assert d["mins"] == req.mins and d["unit"] == req.unit
    questions = {a["question"]: a["answer"] for a in d["answers"]}
    assert questions["How long is the grass right now?"] == "Getting long"
    assert d["lawn"] == {
        "area_m2": 250,
        "summary": "2 lawns paced out, about 250 m² in total",
        "method": "paced",
        "method_text": "Paced it out (a big stride counts as a metre)",
        "estimator": "customer_measured_v0",
        "confidence": "medium",
        "lawns": [
            {"given": "15 × 10 strides", "metres": "15 × 10 metres", "area_m2": 150},
            {"given": "10 × 10 strides", "metres": "10 × 10 metres", "area_m2": 100},
        ],
    }
    # A size band, nudged, says so.
    banded = await make_request(db, customer, "mowing", lawn={"band": "large", "adjust": "bigger"})
    lawn = ok(await jo.get(f"/api/admin/requests/{banded.id}"))["lawn"]
    assert (lawn["method"], lawn["method_text"], lawn["estimator"], lawn["lawns"]) == (
        "band",
        "Picked a size: Large, looks bigger",
        "manual_bands_v0",
        [],
    )
    # Not a lawn job: no lawn.
    hedges = await make_request(db, customer, "hedges")
    assert ok(await jo.get(f"/api/admin/requests/{hedges.id}"))["lawn"] is None


async def test_offers_timeline_messages_and_a_raise_waiting_for_the_customer(jo, db, catalogue):
    s = make_settings()
    customer = await make_customer(db)
    req = await aged(db, await make_request(db, customer, "hedges"), 3)
    gary = await make_provider(db, "Gary Tomlinson", "+447700900209", ["hedges"])
    price = req.guide_pence + 1500
    await marketplace.make_counter(db, s, req.ref, gary, price_pence=price, reasons=["Taller than described"])
    ok(await jo.post(f"/api/admin/requests/{req.ref}/raise-guide", json={"percent": 10, "note": ""}))

    d = ok(await jo.get(f"/api/admin/requests/{req.id}"))
    [offer] = d["offers"]
    assert (offer["provider_short"], offer["price_pence"], offer["guide_pence"], offer["status"]) == (
        "Gary T.",
        req.guide_pence + 1500,
        req.guide_pence,
        "pending",
    )
    assert offer["reasons"] == ["Taller than described"]
    raised = d["price_change"]
    assert raised["status"] == "pending" and raised["from_guide_pence"] == req.guide_pence
    assert raised["guide_pence"] > req.guide_pence and raised["guide_pence"] % 100 == 0
    texts = [t["text"] for t in d["timeline"]]
    assert texts[0] == "Requested"
    assert f"Gary T. suggested £{(req.guide_pence + 1500) // 100}" in texts
    assert texts[-1].startswith("A raise to £") and texts[-1].endswith("was sent to the customer to approve")
    templates = {m["template_id"] for m in d["messages"]}
    assert {"counter_offer", "guide_raise_proposed"} <= templates
    assert all(m["related"]["request_id"] == req.id for m in d["messages"])
    stamps = [m["created_at"] for m in d["messages"]]
    assert stamps == sorted(stamps, reverse=True), "newest first"


async def test_booked_it_says_by_whom_and_the_raise_is_withdrawn(jo, db, catalogue):
    s = make_settings()
    customer = await make_customer(db)
    req = await make_request(db, customer, "mowing")
    ok(await jo.post(f"/api/admin/requests/{req.ref}/raise-guide", json={"percent": 10, "note": ""}))
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    await marketplace.accept_at_guide(db, s, req.ref, dave)
    d = ok(await jo.get(f"/api/admin/requests/{req.id}"))
    assert (d["status"], d["waiting"], d["price_change"]) == ("booked", False, None)
    b = d["booked"]
    assert (b["provider_short"], b["price_pence"], b["via"]) == ("Dave H.", req.guide_pence, "guide")
    assert b["booking_ref"].startswith("B-")
    texts = [t["text"] for t in d["timeline"]]
    assert f"Dave H. took it at £{req.guide_pence // 100}" in texts
    assert any(t.startswith("The raise to £") and t.endswith("was withdrawn: it was booked first") for t in texts)


async def test_who_could_take_it(jo, db, catalogue):
    """The same coverage as the map (A36): who's in reach, what they do, and whether any does it."""
    customer = await make_customer(db)
    req = await make_request(db, customer, "hedges")
    kasia = await make_provider(db, "Kasia Nowak", "+447700900204", ["cleaning"])
    d = ok(await jo.get(f"/api/admin/requests/{req.id}"))
    c = d["coverage"]
    assert (c["in_reach"], c["in_reach_doing_it"], c["uncovered"]) == (1, 0, True)
    assert [(n["short"], n["jobs"], n["does_it"]) for n in c["nearby"]] == [("Kasia N.", ["Regular cleaning"], False)]
    await Providers(db).update(kasia.id, {"skills": ["cleaning", "hedges"]})
    c = ok(await jo.get(f"/api/admin/requests/{req.id}"))["coverage"]
    assert (c["in_reach_doing_it"], c["uncovered"]) == (1, False)


async def test_the_admin_summary_says_across_how_many_lawns(db, catalogue):
    """A39: "About 250 m² lawn across 2 lawns" for more than one lawn; one lawn as before."""
    customer = await make_customer(db)
    cat = await Categories(db).get("mowing")
    two = await make_request(db, customer, "mowing", lawn=TWO_LAWNS)
    assert brief_for(cat, two.answers, two.measure).startswith("About 250 m² lawn across 2 lawns, ")
    one = await make_request(db, customer, "mowing", lawn={"method": "paced", "lawns": [{"length": 19, "width": 10}]})
    assert brief_for(cat, one.answers, one.measure).startswith("About 190 m² lawn, ")
    band = await make_request(db, customer, "mowing")
    assert brief_for(cat, band.answers, band.measure).startswith("About 190 m² lawn, ")


async def test_the_dispatch_list_shows_the_lawns_too(jo, db, catalogue):
    customer = await make_customer(db)
    req = await aged(db, await make_request(db, customer, "mowing", lawn=TWO_LAWNS), 2)
    [waiting] = ok(await jo.get("/api/admin/overview"))["waiting"]
    assert waiting["request_id"] == req.id
    assert waiting["brief"].startswith("About 250 m² lawn across 2 lawns")
