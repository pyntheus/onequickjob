"""Choose the payment gateway from the environment. Owner: L3.

PAYMENT_GATEWAY=fake (the default) uses the fake; PAYMENT_GATEWAY=stripe uses Stripe and needs
STRIPE_SECRET_KEY. Stripe is test mode only in the prototype: the API refuses to start with a
live key while DEMO_MODE is on (check_payment_config runs at start-up, from the payments
router's lifespan, and again whenever a gateway is made). Errors never echo a key.
"""

import logging
from functools import lru_cache

import stripe
from pymongo.asynchronous.database import AsyncDatabase

from app.adapters.payments.base import PaymentGateway
from app.adapters.payments.fake import FakeGateway
from app.adapters.payments.stripe_gateway import StripeGateway
from app.core.config import Settings

log = logging.getLogger("oqj.payments")

SECRET_PREFIXES = {"sk_test_": "test", "rk_test_": "test", "sk_live_": "live", "rk_live_": "live"}
PUBLISHABLE_PREFIXES = {"pk_test_": "test", "pk_live_": "live"}


class PaymentConfigError(RuntimeError):
    pass


def key_mode(key: str, prefixes: dict[str, str]) -> str | None:
    """test, live, or None for a value that isn't a Stripe key of that kind."""
    return next((mode for prefix, mode in prefixes.items() if key.startswith(prefix)), None)


def check_payment_config(s: Settings) -> None:
    """Refuse live Stripe keys while DEMO_MODE is on, and a Stripe gateway without a usable key."""
    secret = s.stripe_secret_key.strip()
    publishable = s.stripe_publishable_key.strip()
    secret_mode = key_mode(secret, SECRET_PREFIXES) if secret else None
    publishable_mode = key_mode(publishable, PUBLISHABLE_PREFIXES) if publishable else None
    if s.demo_mode and "live" in (secret_mode, publishable_mode):
        raise PaymentConfigError(
            "A live Stripe key is set while DEMO_MODE is on. The prototype takes test payments only: "
            "use test keys (sk_test_..., pk_test_...)."
        )
    if s.payment_gateway != "stripe":
        return
    if not secret:
        raise PaymentConfigError("PAYMENT_GATEWAY=stripe needs STRIPE_SECRET_KEY (a test key, sk_test_...).")
    if secret_mode is None:
        raise PaymentConfigError("STRIPE_SECRET_KEY isn't a Stripe secret key (it should start sk_test_).")
    if publishable and publishable_mode is None:
        raise PaymentConfigError("STRIPE_PUBLISHABLE_KEY isn't a Stripe publishable key (it should start pk_test_).")
    if publishable and publishable_mode != secret_mode:
        raise PaymentConfigError("STRIPE_SECRET_KEY and STRIPE_PUBLISHABLE_KEY are from different modes (test/live).")


def warn_about_payment_config(s: Settings) -> None:
    if s.payment_gateway != "stripe":
        return
    if not s.stripe_publishable_key.strip():
        log.warning("STRIPE_PUBLISHABLE_KEY is empty: customers can't save a card until it's set")
    if not s.stripe_webhook_secret.strip():
        log.warning("STRIPE_WEBHOOK_SECRET is empty: webhooks are refused until it is set (see docs/spec/payments.md)")


@lru_cache(maxsize=4)
def stripe_client(secret_key: str) -> stripe.StripeClient:
    """One client (and connection pool) per key. Tests replace this to mock Stripe's HTTP."""
    return stripe.StripeClient(secret_key, http_client=stripe.HTTPXClient(), max_network_retries=2)


def make_payment_gateway(settings: Settings, db: AsyncDatabase) -> PaymentGateway:
    check_payment_config(settings)
    match settings.payment_gateway:
        case "fake":
            return FakeGateway(db, settings.public_base_url)
        case "stripe":
            return StripeGateway(stripe_client(settings.stripe_secret_key.strip()), settings.stripe_publishable_key)
    raise ValueError(f"unknown PAYMENT_GATEWAY {settings.payment_gateway!r}")  # pragma: no cover
