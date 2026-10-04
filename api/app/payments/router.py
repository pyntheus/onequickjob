"""Payment gateway webhooks (/api/payments). Owner: L3.

The router's lifespan runs at API start-up: it refuses to start with a live Stripe key while
DEMO_MODE is on (or PAYMENT_GATEWAY=stripe without a usable key). The payments collections are
created with every other (app.repos.ALL).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import stripe
from fastapi import APIRouter, Depends, FastAPI, Request, status

from app.adapters.payments import check_payment_config, warn_about_payment_config
from app.admin.schemas import WebhookAck
from app.core.config import Settings
from app.core.db import Db, get_db
from app.core.deps import settings_dep
from app.core.errors import ERROR_RESPONSES, ErrorResponse, fail
from app.payments import webhooks


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s: Settings = app.state.settings
    check_payment_config(s)
    warn_about_payment_config(s)
    yield


RESPONSES: dict[int | str, dict[str, Any]] = {**ERROR_RESPONSES, 503: {"model": ErrorResponse}}
router = APIRouter(prefix="/api/payments", tags=["L3 payments"], responses=RESPONSES, lifespan=lifespan)


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request, db: Annotated[Db, Depends(get_db)], s: Annotated[Settings, Depends(settings_dep)]
) -> WebhookAck:
    """Verify the Stripe-Signature header, then handle payment_intent.*, account.updated,
    payout.* and charge.refunded idempotently (by event id). Webhooks are the source of
    truth for final payment states."""
    secret = s.stripe_webhook_secret.strip()
    if not secret:
        fail(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "webhooks_not_configured",
            "Stripe webhooks aren't set up on this server (STRIPE_WEBHOOK_SECRET is empty).",
        )
    payload = await request.body()
    try:
        event = webhooks.verify(payload, request.headers.get("stripe-signature"), secret)
    except stripe.SignatureVerificationError, ValueError, UnicodeDecodeError:
        fail(status.HTTP_400_BAD_REQUEST, "bad_signature", "That isn't a webhook signed by Stripe for this server.")
    return WebhookAck(received=True, duplicate=await webhooks.handle(db, s, event))
