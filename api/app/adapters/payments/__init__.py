"""Choose the payment gateway from the environment. Owner: L3 (adds Stripe here)."""

from pymongo.asynchronous.database import AsyncDatabase

from app.adapters.payments.base import PaymentGateway
from app.adapters.payments.fake import FakeGateway
from app.core.config import Settings


def make_payment_gateway(settings: Settings, db: AsyncDatabase) -> PaymentGateway:
    match settings.payment_gateway:
        case "fake":
            return FakeGateway(db, settings.public_base_url)
        case "stripe":
            raise NotImplementedError("Lane L3 implements the Stripe gateway (PAYMENT_GATEWAY=stripe)")
    raise ValueError(f"unknown PAYMENT_GATEWAY {settings.payment_gateway!r}")  # pragma: no cover
