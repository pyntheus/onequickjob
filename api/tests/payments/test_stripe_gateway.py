"""The Stripe gateway against mocked Stripe responses: what it sends (destination charges with
the provider as settlement merchant, our fee, off-session, idempotency keys) and how it reads
Stripe's answers. No network, no key."""

import pytest

from app.adapters.payments import PaymentConfigError, check_payment_config, make_payment_gateway
from app.adapters.payments.base import CustomerRef, ProviderRef, VisitRef
from app.adapters.payments.stripe_gateway import StripeGateway
from app.core import money
from app.main import create_app
from tests.conftest import make_settings
from tests.payments.stripe_mock import MockStripe, card_error, client, payment_intent

VISIT = VisitRef(
    visit_id="v1", booking_id="b1", customer_id="c1", gateway_customer_id="cus_1", description="Lawn mowing"
)


def gateway(mock: MockStripe) -> StripeGateway:
    return StripeGateway(client(mock), "pk_test_mock")


def with_saved_card(mock: MockStripe) -> MockStripe:
    return mock.on(
        "GET", "/v1/customers/cus_1", {"id": "cus_1", "invoice_settings": {"default_payment_method": "pm_1"}}
    )


# ---------------------------------------------------------------------------- providers
async def test_creates_an_express_account_for_an_individual_in_gb():
    mock = MockStripe().on(
        "POST",
        "/v1/accounts",
        {"id": "acct_1", "charges_enabled": False, "payouts_enabled": False, "requirements": {"currently_due": ["x"]}},
    )
    acct = await gateway(mock).create_provider_account(ProviderRef(provider_id="p1", name="Dave", email="d@x.test"))
    call = mock.one("POST", "/v1/accounts")
    assert call.params["type"] == "express"
    assert call.params["country"] == "GB" and call.params["business_type"] == "individual"
    assert call.params["capabilities[card_payments][requested]"] == "true"
    assert call.params["capabilities[transfers][requested]"] == "true"
    assert call.params["metadata[provider_id]"] == "p1" and call.params["email"] == "d@x.test"
    assert call.idempotency_key == "account:p1"
    assert (acct.account_id, acct.status, acct.payouts_enabled, acct.requirements_due) == (
        "acct_1",
        "pending",
        False,
        ["x"],
    )


async def test_onboarding_link_is_stripe_hosted():
    mock = MockStripe().on("POST", "/v1/account_links", {"url": "https://connect.stripe.com/setup/e/acct_1/x"})
    url = await gateway(mock).onboarding_link(
        "acct_1", return_url="https://r.test/back", refresh_url="https://r.test/again"
    )
    call = mock.one("POST", "/v1/account_links")
    assert call.params == {
        "account": "acct_1",
        "type": "account_onboarding",
        "return_url": "https://r.test/back",
        "refresh_url": "https://r.test/again",
    }
    assert url.startswith("https://connect.stripe.com/")


@pytest.mark.parametrize(
    ("acct", "status"),
    [
        ({"charges_enabled": True, "payouts_enabled": True}, "enabled"),
        ({"details_submitted": True, "requirements": {"disabled_reason": "requirements.past_due"}}, "restricted"),
        ({"details_submitted": False}, "pending"),
    ],
)
async def test_account_status(acct, status):
    body = {
        "id": "acct_1",
        "external_accounts": {"data": [{"last4": "2345"}]},
        **acct,
    }
    mock = MockStripe().on("GET", "/v1/accounts/acct_1", body)
    state = await gateway(mock).account_status("acct_1")
    assert state.status == status and state.bank_last4 == "2345"


# ---------------------------------------------------------------------------- cards
async def test_saving_a_card_creates_a_platform_customer_and_an_off_session_setup_intent():
    mock = (
        MockStripe()
        .on("POST", "/v1/customers", {"id": "cus_new"})
        .on(
            "POST",
            "/v1/setup_intents",
            {"id": "seti_1", "client_secret": "seti_1_secret", "status": "requires_payment_method"},
        )
    )
    setup = await gateway(mock).save_card_setup(CustomerRef(customer_id="c1", name="Sarah", phone="+447700900123"))
    cus = mock.one("POST", "/v1/customers")
    assert cus.idempotency_key == "customer:c1" and cus.stripe_account is None  # on the platform
    assert cus.params["metadata[customer_id]"] == "c1" and cus.params["phone"] == "+447700900123"
    si = mock.one("POST", "/v1/setup_intents")
    assert si.params["customer"] == "cus_new" and si.params["usage"] == "off_session"
    assert si.params["payment_method_types[0]"] == "card"
    assert setup.model_dump() == {
        "gateway": "stripe",
        "gateway_customer_id": "cus_new",
        "setup_id": "seti_1",
        "client_secret": "seti_1_secret",
        "publishable_key": "pk_test_mock",
        "status": "requires_confirmation",
    }


async def test_saving_another_card_reuses_the_customer():
    mock = MockStripe().on(
        "POST", "/v1/setup_intents", {"id": "seti_2", "client_secret": "s", "status": "requires_payment_method"}
    )
    await gateway(mock).save_card_setup(CustomerRef(customer_id="c1", name="Sarah", gateway_customer_id="cus_1"))
    assert not mock.find("POST", "/v1/customers")


async def test_a_confirmed_setup_becomes_the_default_card():
    mock = (
        MockStripe()
        .on(
            "GET",
            "/v1/setup_intents/seti_1",
            {
                "id": "seti_1",
                "status": "succeeded",
                "customer": "cus_1",
                "payment_method": {
                    "id": "pm_1",
                    "card": {"brand": "visa", "last4": "4242", "exp_month": 12, "exp_year": 2034},
                },
            },
        )
        .on("POST", "/v1/customers/cus_1", {"id": "cus_1"})
    )
    st = await gateway(mock).card_setup_status("seti_1")
    assert mock.one("GET", "/v1/setup_intents/seti_1").params["expand[0]"] == "payment_method"
    assert mock.one("POST", "/v1/customers/cus_1").params["invoice_settings[default_payment_method]"] == "pm_1"
    assert st.status == "succeeded" and st.card and (st.card.last4, st.card.exp_year) == ("4242", 2034)


async def test_a_refused_setup_is_failed_with_the_banks_message():
    mock = MockStripe().on(
        "GET",
        "/v1/setup_intents/seti_1",
        {
            "id": "seti_1",
            "status": "requires_payment_method",
            "last_setup_error": {"message": "Your card was declined."},
        },
    )
    st = await gateway(mock).card_setup_status("seti_1")
    assert (st.status, st.failure_reason) == ("failed", "Your card was declined.")


# ---------------------------------------------------------------------------- charges
async def test_a_visit_is_a_destination_charge_with_the_provider_as_settlement_merchant():
    split = money.split_for_visit(3000, "platform", "provider")
    mock = with_saved_card(MockStripe()).on(
        "POST", "/v1/payment_intents", payment_intent(metadata={"idempotency_key": "visit:v1:visit"})
    )
    res = await gateway(mock).charge_visit(VISIT, split.price_pence, split.fee_pence, "acct_1")
    call = mock.one("POST", "/v1/payment_intents")
    p = call.params
    assert (p["amount"], p["currency"], p["application_fee_amount"]) == ("3000", "gbp", "450")
    assert p["on_behalf_of"] == "acct_1" and p["transfer_data[destination]"] == "acct_1"
    assert (p["customer"], p["payment_method"], p["off_session"], p["confirm"]) == ("cus_1", "pm_1", "true", "true")
    assert p["metadata[visit_id]"] == "v1" and p["metadata[purpose]"] == "visit"
    assert call.idempotency_key == "visit:v1:visit" == p["metadata[idempotency_key]"]
    assert call.stripe_account is None  # created on the platform; the provider settles it
    # £30: our fee £4.50, the provider's transfer £25.50.
    assert int(p["amount"]) - int(p["application_fee_amount"]) == 2550 == split.provider_pence
    assert (res.status, res.charge_id, res.payment_intent_id) == ("succeeded", "ch_1", "pi_1")


async def test_an_own_customer_visit_takes_the_pound_minimum():
    split = money.split_for_visit(1500, "own_customer", "provider")
    mock = with_saved_card(MockStripe()).on(
        "POST", "/v1/payment_intents", payment_intent(amount=1500, application_fee_amount=100)
    )
    await gateway(mock).charge_visit(VISIT, split.price_pence, split.fee_pence, "acct_1")
    p = mock.one("POST", "/v1/payment_intents").params
    assert (p["amount"], p["application_fee_amount"]) == ("1500", "100")
    assert split.provider_pence == 1400


async def test_a_tip_carries_no_fee():
    mock = with_saved_card(MockStripe()).on(
        "POST", "/v1/payment_intents", payment_intent(amount=500, application_fee_amount=None)
    )
    res = await gateway(mock).charge_visit(VISIT, 500, 0, "acct_1", purpose="tip")
    call = mock.one("POST", "/v1/payment_intents")
    assert "application_fee_amount" not in call.params and call.params["transfer_data[destination]"] == "acct_1"
    assert call.idempotency_key == "visit:v1:tip" and res.fee_pence == 0


async def test_falls_back_to_the_latest_saved_card():
    mock = (
        MockStripe()
        .on("GET", "/v1/customers/cus_1", {"id": "cus_1", "invoice_settings": {"default_payment_method": None}})
        .on("GET", "/v1/payment_methods", {"data": [{"id": "pm_9"}]})
        .on("POST", "/v1/payment_intents", payment_intent())
    )
    await gateway(mock).charge_visit(VISIT, 3000, 450, "acct_1")
    assert mock.one("POST", "/v1/payment_intents").params["payment_method"] == "pm_9"


async def test_a_bank_wanting_authentication_needs_the_customer():
    pi = payment_intent(status="requires_payment_method", last_payment_error={"code": "authentication_required"})
    mock = with_saved_card(MockStripe()).on(
        "POST", "/v1/payment_intents", lambda c: card_error("authentication_required", "Authentication required.", pi)
    )
    res = await gateway(mock).charge_visit(VISIT, 3000, 450, "acct_1")
    assert (res.status, res.payment_intent_id, res.failure_code) == (
        "requires_action",
        "pi_1",
        "authentication_required",
    )


async def test_a_declined_card_fails_with_the_decline_code():
    pi = payment_intent(status="requires_payment_method")
    mock = with_saved_card(MockStripe()).on(
        "POST",
        "/v1/payment_intents",
        lambda c: card_error("card_declined", "Your card has insufficient funds.", pi, "insufficient_funds"),
    )
    res = await gateway(mock).charge_visit(VISIT, 3000, 450, "acct_1")
    assert (res.status, res.failure_code, res.failure_reason) == (
        "failed",
        "insufficient_funds",
        "Your card has insufficient funds.",
    )


async def test_stripe_unreachable_leaves_the_outcome_pending():
    mock = with_saved_card(MockStripe()).on(
        "POST", "/v1/payment_intents", lambda c: (500, {"error": {"type": "api_error", "message": "boom"}})
    )
    res = await gateway(mock).charge_visit(VISIT, 3000, 450, "acct_1", idempotency_key="visit:v1:visit")
    assert res.status == "pending" and res.failure_code == "platform:unreachable"
    assert res.idempotency_key == "visit:v1:visit"


async def test_a_refusal_that_isnt_the_card_is_a_platform_failure():
    mock = with_saved_card(MockStripe()).on(
        "POST",
        "/v1/payment_intents",
        lambda c: (
            400,
            {
                "error": {
                    "type": "invalid_request_error",
                    "code": "insufficient_capabilities_for_transfer",
                    "message": "x",
                }
            },
        ),
    )
    res = await gateway(mock).charge_visit(VISIT, 3000, 450, "acct_1")
    assert res.status == "failed" and res.failure_code == "platform:insufficient_capabilities_for_transfer"


async def test_no_saved_card():
    mock = (
        MockStripe()
        .on("GET", "/v1/customers/cus_1", {"id": "cus_1", "invoice_settings": {}})
        .on("GET", "/v1/payment_methods", {"data": []})
    )
    res = await gateway(mock).charge_visit(VISIT, 3000, 450, "acct_1")
    assert (res.status, res.failure_code) == ("failed", "no_saved_card")
    assert not mock.find("POST", "/v1/payment_intents")


async def test_cancelling_an_attempt_that_went_through_keeps_it():
    mock = MockStripe().on("GET", "/v1/payment_intents/pi_1", payment_intent())
    res = await gateway(mock).cancel_charge("pi_1")
    assert res.status == "succeeded" and not mock.find("POST", "/v1/payment_intents/pi_1/cancel")


async def test_cancelling_an_attempt_waiting_for_the_customer():
    mock = (
        MockStripe()
        .on(
            "GET",
            "/v1/payment_intents/pi_1",
            payment_intent(status="requires_payment_method", last_payment_error={"code": "authentication_required"}),
        )
        .on("POST", "/v1/payment_intents/pi_1/cancel", payment_intent(status="canceled"))
    )
    res = await gateway(mock).cancel_charge("pi_1")
    assert (res.status, res.failure_reason) == ("failed", "The payment was cancelled.")


# ---------------------------------------------------------------------------- refunds
async def test_a_refund_reverses_the_transfer_and_returns_exactly_our_share_of_the_fee():
    original = money.split_for_visit(3000, "platform", "provider")
    half = money.refund_split(original, 1500)
    assert (half.fee_pence, half.provider_pence) == (225, 1275)
    mock = (
        MockStripe()
        .on("POST", "/v1/refunds", {"id": "re_1", "status": "succeeded"})
        .on("GET", "/v1/charges/ch_1", {"id": "ch_1", "application_fee": "fee_1"})
        .on("POST", "/v1/application_fees/fee_1/refunds", {"id": "fr_1", "amount": 225})
    )
    res = await gateway(mock).refund("ch_1", 1500, half.fee_pence, reason="Clippings left", idempotency_key="rf1")
    refund = mock.one("POST", "/v1/refunds")
    assert refund.params["charge"] == "ch_1" and refund.params["amount"] == "1500"
    assert refund.params["reverse_transfer"] == "true" and refund.params["refund_application_fee"] == "false"
    assert refund.idempotency_key == "rf1"
    fee = mock.one("POST", "/v1/application_fees/fee_1/refunds")
    assert fee.params["amount"] == "225" and fee.idempotency_key == "rf1:fee"
    assert (res.status, res.refund_id, res.fee_refunded_pence) == ("succeeded", "re_1", 225)


async def test_a_refund_whose_fee_part_fails_is_pending():
    mock = (
        MockStripe()
        .on("POST", "/v1/refunds", {"id": "re_1", "status": "succeeded"})
        .on("GET", "/v1/charges/ch_1", {"id": "ch_1", "application_fee": "fee_1"})
        .on("POST", "/v1/application_fees/fee_1/refunds", lambda c: (500, {"error": {"type": "api_error"}}))
    )
    res = await gateway(mock).refund("ch_1", 1500, 225, reason="x", idempotency_key="rf1")
    assert (res.status, res.refund_id, res.fee_refunded_pence) == ("pending", "re_1", 0)


async def test_a_refused_refund_fails():
    mock = MockStripe().on(
        "POST",
        "/v1/refunds",
        lambda c: (
            400,
            {
                "error": {
                    "type": "invalid_request_error",
                    "code": "charge_already_refunded",
                    "message": "Already refunded.",
                }
            },
        ),
    )
    res = await gateway(mock).refund("ch_1", 1500, 225, reason="x")
    assert res.status == "failed" and not mock.find("POST", "/v1/application_fees/.*")


# ---------------------------------------------------------------------------- payouts
async def test_payout_summary_reads_the_connected_account():
    mock = (
        MockStripe()
        .on(
            "GET",
            "/v1/payouts",
            {
                "data": [
                    {
                        "id": "po_2",
                        "amount": 2550,
                        "status": "in_transit",
                        "arrival_date": 1790300000,
                        "destination": {"last4": "2345"},
                    },
                    {"id": "po_1", "amount": 9000, "status": "paid", "arrival_date": 1789700000, "destination": "ba_1"},
                ]
            },
        )
        .on(
            "GET",
            "/v1/balance",
            {"available": [{"amount": 100, "currency": "gbp"}], "pending": [{"amount": 1275, "currency": "gbp"}]},
        )
    )
    s = await gateway(mock).payout_summary("acct_1", limit=5)
    assert all(c.stripe_account == "acct_1" for c in mock.calls)
    assert mock.one("GET", "/v1/payouts").params["limit"] == "5"
    assert [(p.payout_id, p.status, p.amount_pence, p.bank_last4) for p in s.payouts] == [
        ("po_2", "in_transit", 2550, "2345"),
        ("po_1", "paid", 9000, None),
    ]
    assert s.pending_pence == 1375 and s.next_payout_date == s.payouts[0].arrival_date


# ---------------------------------------------------------------------------- configuration
@pytest.mark.parametrize(
    ("overrides", "ok"),
    [
        ({}, True),
        ({"stripe_secret_key": "sk_live_abc"}, False),  # live key in DEMO_MODE, even with the fake
        ({"stripe_publishable_key": "pk_live_abc"}, False),
        ({"stripe_secret_key": "sk_live_abc", "demo_mode": False, "payment_gateway": "stripe"}, True),
        ({"payment_gateway": "stripe"}, False),  # no key
        ({"payment_gateway": "stripe", "stripe_secret_key": "not-a-key"}, False),
        (
            {
                "payment_gateway": "stripe",
                "stripe_secret_key": "sk_test_a",
                "stripe_publishable_key": "pk_live_b",
                "demo_mode": False,
            },
            False,
        ),
        ({"payment_gateway": "stripe", "stripe_secret_key": "sk_test_a", "stripe_publishable_key": "pk_test_b"}, True),
        ({"payment_gateway": "stripe", "stripe_secret_key": "rk_test_a"}, True),
    ],
)
def test_payment_config(overrides, ok):
    s = make_settings(**{"stripe_secret_key": "", "stripe_publishable_key": "", **overrides})
    if ok:
        check_payment_config(s)
    else:
        with pytest.raises(PaymentConfigError) as e:
            check_payment_config(s)
        assert "abc" not in str(e.value) and "not-a-key" not in str(e.value)  # never echoes a key


async def test_the_api_refuses_to_start_with_a_live_key_in_demo_mode():
    app = create_app(make_settings(stripe_secret_key="sk_live_abc", demo_mode=True))
    with pytest.raises(PaymentConfigError):
        async with app.router.lifespan_context(app):
            pass


async def test_the_gateway_is_chosen_by_payment_gateway(db, monkeypatch):
    import app.adapters.payments as payments

    mock = MockStripe()
    monkeypatch.setattr(payments, "stripe_client", lambda key: client(mock))
    assert make_payment_gateway(make_settings(stripe_secret_key="sk_test_x"), db).name == "fake"
    assert (
        make_payment_gateway(make_settings(payment_gateway="stripe", stripe_secret_key="sk_test_x"), db).name
        == "stripe"
    )
