"""Payment gateway webhooks (/api/payments). Owner: L3."""

from fastapi import APIRouter, Request

from app.admin.schemas import WebhookAck
from app.core.errors import ERROR_RESPONSES, not_implemented

router = APIRouter(prefix="/api/payments", tags=["L3 payments"], responses=ERROR_RESPONSES)


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request) -> WebhookAck:
    """Verify the Stripe-Signature header, then handle payment_intent.*, account.updated,
    payout.* and charge.refunded idempotently (by event id). Webhooks are the source of
    truth for final payment states."""
    not_implemented("L3")
