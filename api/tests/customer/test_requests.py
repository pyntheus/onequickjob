"""Job requests from the customer's side: creating one broadcasts it (job alerts with single-use
links, held for quiet hours), the confirmation text, the "Finding someone local" view, counters
with a dearer first visit (A1), cancelling and expiring."""

from datetime import UTC, datetime, timedelta

from app.core.timeutil import utcnow
from app.customer import requests as request_service
from app.models.providers import AlertSettings
from app.repos import JobRequests, Offers, Quotes
from app.services import marketplace
from tests.conftest import make_settings, new_client, sign_in
from tests.customer.helpers import (
    customer_of,
    make_request_via_api,
    quote,
    request_body,
    signed_in_with_card,
)
from tests.factories import make_provider


async def test_create_request_broadcasts_with_magic_links_and_confirms(client, db, catalogue):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    await make_provider(db, "Far Away", "+447700900299", ["cleaning"])  # wrong skill: not alerted
    await signed_in_with_card(client, db)
    q = await quote(client)
    r = await client.post(
        "/api/c/requests", json=request_body(q["id"], contact={"name": "Sarah W", "email": "s@example.com"})
    )
    assert r.status_code == 201, r.text
    detail = r.json()
    assert detail["status"] == "open" and detail["guide_pence"] == 3100 and detail["alerted"] == 1
    assert detail["size_text"] == "Large (about 190 m²)"
    assert detail["frequency_label"] == "every 2 weeks"
    assert [t["kind"] for t in detail["timeline"]] == ["sent"]
    assert detail["timeline"][0]["text"] == "Sent to checked mowing providers near HP15"

    req = await JobRequests(db).by_ref(detail["ref"])
    assert req.broadcast.provider_ids == [dave.id] and req.quote_id == q["id"]
    assert (await Quotes(db).get(q["id"])).request_id == req.id
    alert = await db["outbox"].find_one({"template_id": "job_alert"})
    assert alert["recipient"]["phone"] == "+447700900201"
    assert "Lawn mowing in Hazlemere (HP15)" in alert["body"] and "Guide price £31, you'd get £26.35." in alert["body"]
    assert f"/p/j/{detail['ref']}?t=" in alert["body"]
    assert (
        await db["magic_links"].count_documents({"purpose": "job_alert", "target_path": f"/p/j/{detail['ref']}"}) == 1
    )
    sent = await db["outbox"].find_one({"template_id": "request_sent"})
    assert "lawn mowing request to checked providers near HP15" in sent["body"]
    customer = await customer_of(db)
    assert customer.name == "Sarah W" and customer.terms_accepted_at is not None
    assert customer.addresses[0].uprn == "999000000001"


async def test_the_job_alert_link_signs_the_provider_in(app, client, db, catalogue):
    await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    alert = await db["outbox"].find_one({"template_id": "job_alert"})
    token = alert["body"].split("?t=")[1].split()[0]
    async with await new_client(app) as pc:
        r = await pc.post("/api/auth/magic", json={"token": token})
        assert r.status_code == 200 and r.json()["next"] == f"/p/j/{detail['ref']}"


async def test_nobody_eligible_sends_request_no_providers(client, db, catalogue):
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    assert detail["alerted"] == 0
    assert detail["timeline"][0]["text"].startswith("We're finding someone local by hand")
    assert await db["outbox"].count_documents({"template_id": "request_no_providers"}) == 1
    assert await db["outbox"].count_documents({"template_id": "job_alert"}) == 0


async def test_a_card_is_needed_and_the_same_quote_twice_is_the_same_request(client, db, catalogue):
    await sign_in(client, db, "+447700900123", "Sarah Whitfield")
    q = await quote(client)
    r = await client.post("/api/c/requests", json=request_body(q["id"]))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "card_needed"
    s = (await client.post("/api/c/payment/setup")).json()
    await client.post(f"/api/c/payment/setup/{s['setup_id']}/confirm")
    first = await client.post("/api/c/requests", json=request_body(q["id"]))
    again = await client.post("/api/c/requests", json=request_body(q["id"]))
    assert first.status_code == 201 and again.status_code == 201
    assert first.json()["ref"] == again.json()["ref"]
    assert await JobRequests(db).count({}) == 1
    assert await db["outbox"].count_documents({"template_id": "request_no_providers"}) == 1


async def test_someone_elses_quote_and_photos_are_refused(app, client, db, catalogue):
    async with await new_client(app) as other:
        await sign_in(other, db, "+447700900130", "Robert Brown")
        theirs = await quote(other)
    await signed_in_with_card(client, db)
    r = await client.post("/api/c/requests", json=request_body(theirs["id"]))
    assert r.status_code == 404
    mine = await quote(client)
    r = await client.post("/api/c/requests", json=request_body(mine["id"], photos=["000000000000000000000000"]))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_photo"


async def test_photos_uploaded_after_sign_in_go_on_the_request(client, db, catalogue):
    await signed_in_with_card(client, db)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    up = await client.post("/api/files", files={"file": ("lawn.png", png, "image/png")}, data={"kind": "request_photo"})
    assert up.status_code == 201, up.text
    detail = await make_request_via_api(client, photos=[up.json()["id"]])
    assert (await JobRequests(db).by_ref(detail["ref"])).photos == [up.json()["id"]]


async def test_an_email_another_account_uses_is_refused(app, client, db, catalogue):
    async with await new_client(app) as other:
        await sign_in(other, db, "taken@example.com", "Someone Else")
    await signed_in_with_card(client, db)
    q = await quote(client)
    r = await client.post(
        "/api/c/requests", json=request_body(q["id"], contact={"name": "Sarah", "email": "TAKEN@example.com"})
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "email_in_use"
    assert await JobRequests(db).count({}) == 0


def test_quiet_hours_hold_alerts_until_morning():
    alerts = AlertSettings(quiet_hours=True, quiet_from="20:00", quiet_to="08:00")
    late = datetime(2026, 10, 5, 21, 30, tzinfo=UTC)  # 22:30 in London (BST)
    assert request_service.quiet_until(alerts, late) == datetime(2026, 10, 6, 7, 0, tzinfo=UTC)
    early = datetime(2026, 10, 6, 5, 0, tzinfo=UTC)  # 06:00 London
    assert request_service.quiet_until(alerts, early) == datetime(2026, 10, 6, 7, 0, tzinfo=UTC)
    assert request_service.quiet_until(alerts, datetime(2026, 10, 6, 12, 0, tzinfo=UTC)) is None
    assert request_service.quiet_until(AlertSettings(quiet_hours=False), late) is None


async def test_the_finding_screen_shows_viewers_and_a_counter_with_both_prices(app, client, db, catalogue):
    """A1: a counter on a job with a dearer first visit carries both stored prices."""
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["cleaning"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client, "cleaning")
    assert detail["guide_pence"] == 6600 and detail["first_pence"] == 8800
    req = await JobRequests(db).by_ref(detail["ref"])
    from app.models.job_requests import RequestEvent

    await JobRequests(db).record_view(req.id, mike.id, RequestEvent(at=utcnow(), kind="viewed", provider_id=mike.id))
    offer = await marketplace.make_counter(
        db, make_settings(), req.ref, mike, price_pence=7200, reasons=["Big kitchen"]
    )
    r = await client.get(f"/api/c/requests/{req.ref}")
    view = r.json()
    assert [t["kind"] for t in view["timeline"]] == ["sent", "viewing", "counter"]
    assert view["timeline"][1]["text"] == "Mike R. is looking at your job"
    assert view["timeline"][2]["text"] == "Mike R. suggested £72 a clean (first visit £96)"
    (pending,) = view["pending_offers"]
    assert pending["offer_id"] == offer.id and pending["price_pence"] == 7200
    assert pending["first_price_pence"] == offer.first_price_pence == 9600
    assert pending["reason_text"] == "Big kitchen"
    assert pending["provider"]["badges"][0]["label"] == "ID checked"


async def test_accepting_the_counter_books_both_prices(app, client, db, catalogue):
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["cleaning"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client, "cleaning")
    offer = await marketplace.make_counter(db, make_settings(), detail["ref"], mike, price_pence=7200, reasons=[])
    r = await client.post(f"/api/c/offers/{offer.id}/accept")
    assert r.status_code == 200 and r.json()["first_visit"]["price_pence"] == 9600
    view = (await client.get(f"/api/c/requests/{detail['ref']}")).json()
    assert view["status"] == "booked" and view["booked_via"] == "counter"
    assert view["booked_price_pence"] == 7200 and view["booked_first_price_pence"] == 9600
    assert view["timeline"][-1]["text"] == "You accepted Mike R.'s price of £72 (first visit £96)"
    assert view["booking_id"] and view["pending_offers"] == []


async def test_an_ineligible_counter_lapses_and_the_request_stays_open(client, db, catalogue):
    """Ruling A9, as the customer sees it."""
    from app.repos import Providers

    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    offer = await marketplace.make_counter(db, make_settings(), detail["ref"], mike, price_pence=3600, reasons=[])
    p = await Providers(db).get(mike.id)
    await Providers(db).patch(
        mike.id, {"documents": [d.model_dump(mode="python") for d in p.documents if d.type != "insurance"]}
    )
    r = await client.post(f"/api/c/offers/{offer.id}/accept")
    assert r.status_code == 409
    assert r.json()["detail"]["message"] == "Mike can no longer take this job. We're still finding someone local."
    view = (await client.get(f"/api/c/requests/{detail['ref']}")).json()
    assert view["status"] == "open" and view["pending_offers"] == []
    assert view["timeline"][-1] == {**view["timeline"][-1], "kind": "note", "text": r.json()["detail"]["message"]}
    lapsed = await db["outbox"].find_one({"template_id": "counter_lapsed"})
    assert "Some documents this job needs aren't checked or have run out." in lapsed["body"]


async def test_cancel_withdraws_counters_and_tells_those_providers(client, db, catalogue):
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    offer = await marketplace.make_counter(db, make_settings(), detail["ref"], mike, price_pence=3600, reasons=[])
    r = await client.post(f"/api/c/requests/{detail['ref']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert r.json()["timeline"][-1]["text"] == "You cancelled this request"
    assert (await Offers(db).get(offer.id)).status == "withdrawn"
    closed = await db["outbox"].find_one({"template_id": "request_closed"})
    assert closed["recipient"]["phone"] == "+447700900202" and "no longer available" in closed["body"]
    again = await client.post(f"/api/c/requests/{detail['ref']}/cancel")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "not_open"
    assert (await client.post(f"/api/c/offers/{offer.id}/accept")).status_code == 409


async def test_a_booked_request_cannot_be_cancelled(client, db, catalogue):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    await marketplace.accept_at_guide(db, make_settings(), detail["ref"], dave)
    r = await client.post(f"/api/c/requests/{detail['ref']}/cancel")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_booked"


async def test_someone_elses_request_is_not_found(app, client, db, catalogue):
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    async with await new_client(app) as other:
        await signed_in_with_card(other, db, "+447700900130", "Robert Brown")
        assert (await other.get(f"/api/c/requests/{detail['ref']}")).status_code == 404
        assert (await other.post(f"/api/c/requests/{detail['ref']}/cancel")).status_code == 404
        assert (await other.get("/api/c/requests")).json() == []
    listed = (await client.get("/api/c/requests")).json()
    assert [r["ref"] for r in listed] == [detail["ref"]]


async def test_requests_expire_after_a_week(client, db, catalogue):
    mike = await make_provider(db, "Mike Reynolds", "+447700900202", ["mowing"])
    await signed_in_with_card(client, db)
    old = await make_request_via_api(client)
    fresh = await make_request_via_api(client)
    offer = await marketplace.make_counter(db, make_settings(), old["ref"], mike, price_pence=3600, reasons=[])
    await JobRequests(db).coll.update_one({"ref": old["ref"]}, {"$set": {"created_at": utcnow() - timedelta(days=8)}})
    assert await request_service.expire_stale(db, make_settings()) == 1
    assert (await JobRequests(db).by_ref(old["ref"])).status == "expired"
    assert (await JobRequests(db).by_ref(fresh["ref"])).status == "open"
    assert (await Offers(db).get(offer.id)).status == "lapsed"
    assert await db["outbox"].count_documents({"template_id": "request_expired"}) == 1
    assert await db["outbox"].count_documents({"template_id": "request_closed"}) == 1
    assert await request_service.expire_stale(db, make_settings()) == 0, "idempotent"
