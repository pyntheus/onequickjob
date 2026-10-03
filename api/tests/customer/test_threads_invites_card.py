"""Messages with the provider, own-customer invites (the price is the provider's; the fee isn't
added to it), saving a card, and the landing page's fee example."""

from app.core.ids import new_token, token_hash
from app.models.provider_ops import OwnCustomerInvite
from app.repos import Bookings, Customers, Messages, OwnCustomerInvites, Users
from tests.conftest import make_settings, new_client, sign_in
from tests.customer.helpers import address, book_at_guide, make_request_via_api, signed_in_with_card
from tests.factories import make_provider

MARY = "+447700900140"


# ------------------------------------------------------------------------------- threads


async def test_message_the_provider_and_read_their_reply(client, db, catalogue):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    booking = (await book_at_guide(db, detail["ref"], dave)).booking
    (summary,) = (await client.get("/api/c/threads")).json()
    assert summary["id"] == booking.thread_id and summary["kind"] == "booking"
    assert summary["title"] == "Lawn mowing with Dave H." and summary["other_party"] == "Dave H."
    r = await client.post(f"/api/c/threads/{booking.thread_id}/messages", json={"body": "  The gate sticks!  "})
    assert r.status_code == 201 and r.json()["mine"] is True and r.json()["body"] == "The gate sticks!"
    texted = await db["outbox"].find_one({"template_id": "message_received"})
    assert texted["recipient"]["phone"] == "+447700900201" and '"The gate sticks!"' in texted["body"]
    await Messages(db).post(booking.thread_id, dave.user_id, "provider", "No problem, see you Tuesday.")
    assert (await client.get("/api/c/threads")).json()[0]["unread"] == 1
    msgs = (await client.get(f"/api/c/threads/{booking.thread_id}/messages")).json()
    assert [(m["sender_name"], m["mine"]) for m in msgs] == [("Sarah Whitfield", True), ("Dave H.", False)]
    assert (await client.get("/api/c/threads")).json()[0]["unread"] == 0, "reading marks them read"
    assert (await client.post(f"/api/c/threads/{booking.thread_id}/messages", json={"body": "   "})).status_code == 422


async def test_threads_are_private(app, client, db, catalogue):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client)
    booking = (await book_at_guide(db, detail["ref"], dave)).booking
    async with await new_client(app) as other:
        await signed_in_with_card(other, db, "+447700900130", "Robert Brown")
        assert (await other.get(f"/api/c/threads/{booking.thread_id}/messages")).status_code == 404
        assert (
            await other.post(f"/api/c/threads/{booking.thread_id}/messages", json={"body": "hi"})
        ).status_code == 404


# ------------------------------------------------------------------------------- invites


async def _invite(db, provider, phone: str = MARY, price: int = 2500, frequency: str = "fortnightly") -> str:
    token = new_token(24)
    await OwnCustomerInvites(db).insert(
        OwnCustomerInvite(
            provider_id=provider.id,
            name="Mary Bishop",
            phone=phone,
            category_id="mowing",
            price_pence=price,
            frequency=frequency,
            token_hash=token_hash(token, make_settings().pepper),
        )
    )
    return token


async def test_invite_preview_is_public_and_shows_the_providers_price_and_fee(client, db, catalogue):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    token = await _invite(db, dave)
    r = await client.get(f"/api/c/invites/{token}")
    assert r.status_code == 200
    p = r.json()
    assert p["status"] == "invited" and p["customer_first_name"] == "Mary" and p["provider"]["short"] == "Dave H."
    assert p["price_pence"] == 2500 and p["provider_fee_pence"] == 125, "5% of £25, paid by Dave"
    assert p["frequency_label"] == "every 2 weeks" and p["phone_hint"] == "07700 9•••40" and p["next_visit_text"]
    assert (await client.get("/api/c/invites/not-a-real-token-xyz")).status_code == 404


async def test_accepting_an_invite_makes_an_own_customer_booking_at_the_providers_price(client, db, catalogue):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    token = await _invite(db, dave)
    await sign_in(client, db, MARY, "Mary Bishop")
    r = await client.post(f"/api/c/invites/{token}/accept", json={"agree_terms": True, "address": address()})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "card_needed"
    s = (await client.post("/api/c/payment/setup")).json()
    await client.post(f"/api/c/payment/setup/{s['setup_id']}/confirm")
    customer = await Customers(db).by_user((await Users(db).by_phone(MARY)).id)
    assert customer.joined_via == "own_customer" and customer.invited_by_provider_id == dave.id
    no_address = await client.post(f"/api/c/invites/{token}/accept", json={"agree_terms": True})
    assert no_address.status_code == 422 and no_address.json()["detail"]["code"] == "address_needed"

    r = await client.post(f"/api/c/invites/{token}/accept", json={"agree_terms": True, "address": address()})
    assert r.status_code == 201, r.text
    card = r.json()
    assert card["source"] == "own_customer" and card["price_pence"] == 2500 and card["recurring"] is True
    assert card["split"] == {
        "mode": "own_customer",
        "rate_percent": 5,
        "price_pence": 2500,
        "fee_pence": 125,
        "provider_pence": 2375,
    }
    booking = await Bookings(db).get(card["id"])
    assert booking.via == "invite" and booking.invite_id and booking.series_id
    invite = await OwnCustomerInvites(db).get(booking.invite_id)
    assert invite.status == "accepted" and invite.booking_id == booking.id
    msg = await db["outbox"].find_one({"template_id": "invite_accepted"})
    assert msg["recipient"]["phone"] == "+447700900201" and msg["body"].startswith(
        "OneQuickJob: Mary Bishop accepted your invite."
    )
    again = await client.post(f"/api/c/invites/{token}/accept", json={"agree_terms": True})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_accepted"
    assert (await client.get(f"/api/c/invites/{token}")).json()["status"] == "accepted"
    detail = (await client.get(f"/api/c/bookings/{booking.id}")).json()
    assert (
        detail["agreement_text"].startswith("Your agreement is still with Dave.")
        and "isn't added to your price" in detail["agreement_text"]
    )


async def test_only_the_invited_number_can_accept(client, db, catalogue):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    token = await _invite(db, dave)
    await signed_in_with_card(client, db, "+447700900155", "Not Mary")
    r = await client.post(f"/api/c/invites/{token}/accept", json={"agree_terms": True, "address": address()})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "wrong_number"
    assert "07700 9•••40" in r.json()["detail"]["message"]


async def test_a_platform_customer_stays_on_the_standard_terms(client, db, catalogue):
    """The invite-only rule, if they booked through us after the invite was sent."""
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    token = await _invite(db, dave, phone="+447700900123")
    await signed_in_with_card(client, db)
    customer = await Customers(db).by_user((await Users(db).by_phone("+447700900123")).id)
    await Customers(db).update(customer.id, {"joined_via": "platform"})
    await make_request_via_api(client)
    r = await client.post(f"/api/c/invites/{token}/accept", json={"agree_terms": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "platform_customer"
    assert await Bookings(db).count({"source": "own_customer"}) == 0


# ------------------------------------------------------------------------------- card and profile


async def test_saving_a_card_creates_the_customer_record(client, db, catalogue):
    await sign_in(client, db, "+447700900160", "New Person")
    assert (await client.get("/api/c/profile")).status_code == 404
    setup = (await client.post("/api/c/payment/setup")).json()
    assert setup["gateway"] == "fake" and setup["status"] == "succeeded"
    assert (await client.post("/api/c/payment/setup/seti_nope/confirm")).status_code == 404
    r = await client.post(f"/api/c/payment/setup/{setup['setup_id']}/confirm")
    assert r.json()["card"]["last4"] == "4242"
    profile = (await client.get("/api/c/profile")).json()
    assert profile["name"] == "New Person" and profile["card"]["last4"] == "4242"
    assert (await client.get("/api/c/payment/card")).json()["last4"] == "4242"
    customer = await Customers(db).by_user((await Users(db).by_phone("+447700900160")).id)
    assert customer.joined_via == "platform" and customer.payment.gateway_customer_id.startswith("cus_fake_")
    r = await client.patch("/api/c/profile", json={"name": "New P. Person", "email": "New@Example.com"})
    assert r.json()["name"] == "New P. Person" and r.json()["email"] == "new@example.com"


async def test_fee_example_comes_from_money(client, db):
    r = await client.get("/api/c/fees/example")
    assert r.json()["split"] == {
        "mode": "standard",
        "rate_percent": 15,
        "price_pence": 3000,
        "fee_pence": 450,
        "provider_pence": 2550,
    }
    assert (await client.get("/api/c/fees/example?price_pence=5")).status_code == 422
