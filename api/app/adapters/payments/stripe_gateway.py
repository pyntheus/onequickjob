"""The Stripe PaymentGateway: Connect Express, destination charges, test mode only.

- Providers: Express connected accounts (country GB, individual), Stripe-hosted onboarding
  links, and their state read back from the account (account.updated keeps it in sync).
- Customers: a Customer on the PLATFORM account; the card is saved with a SetupIntent
  (usage off_session) that the browser confirms with Stripe.js, then made the customer's
  default payment method.
- Charging a visit: a PaymentIntent created and confirmed off-session with the saved card,
  as a destination charge: on_behalf_of the provider's account (the provider is the
  settlement merchant), transfer_data.destination the same account and
  application_fee_amount = the fee from app.core.money (none on tips). The caller's
  per-visit idempotency key goes to Stripe, so a repeated call never charges twice.
- Refunds: reverse_transfer, so the provider funds the refund, and our fee is refunded with
  an explicit application-fee refund of exactly the amount money.refund_split gives, rather
  than Stripe's own proportional rounding.
- Payouts: listed from the connected account itself.

Every amount is integer pence (GBP minor units). Responses are turned into plain dicts
(StripeObject.to_dict) before anything reads them.
"""

import logging
from datetime import UTC, date, datetime
from typing import Any, Literal

import stripe
from stripe import StripeClient

from app.adapters.payments.base import (
    PLATFORM_FAILURE,
    CardSetup,
    CardSetupStatus,
    ChargeResult,
    CustomerRef,
    Payout,
    PayoutSummary,
    ProviderAccount,
    ProviderRef,
    RefundResult,
    SavedCardInfo,
    VisitRef,
)
from app.core.timeutil import to_london, utcnow

log = logging.getLogger("oqj.payments.stripe")

CURRENCY = "gbp"
AUTH_REQUIRED = "authentication_required"
UNREACHABLE = "We couldn't reach Stripe, so we don't know yet whether the payment went through."
UNREACHABLE_REFUND = "We couldn't reach Stripe, so we don't know yet whether the refund was made."
FEE_RETRY = "The customer's refund went through; returning our fee to the provider needs another try."

type Json = dict[str, Any]


def as_dict(obj: Any) -> Json:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    return obj.to_dict()


def ref_id(value: Any) -> str | None:
    """An id from a field that may be an id or an expanded object."""
    if value is None or isinstance(value, str):
        return value
    return as_dict(value).get("id")


def _local_date(ts: int | None) -> date | None:
    return None if ts is None else to_london(datetime.fromtimestamp(ts, UTC)).date()


def provider_account_from_stripe(acct: Json) -> ProviderAccount:
    """Our view of an Express account (also used by the account.updated webhook)."""
    reqs = acct.get("requirements") or {}
    due = list(dict.fromkeys([*(reqs.get("past_due") or []), *(reqs.get("currently_due") or [])]))
    if acct.get("charges_enabled") and acct.get("payouts_enabled"):
        status: Literal["pending", "enabled", "restricted"] = "enabled"
    elif acct.get("details_submitted") and (reqs.get("disabled_reason") or reqs.get("past_due")):
        status = "restricted"
    else:
        status = "pending"
    banks = ((acct.get("external_accounts") or {}).get("data")) or []
    return ProviderAccount(
        account_id=acct["id"],
        status=status,
        payouts_enabled=bool(acct.get("payouts_enabled")),
        bank_last4=banks[0].get("last4") if banks else None,
        requirements_due=due,
    )


def charge_result_from_intent(pi: Json, *, idempotency_key: str | None = None) -> ChargeResult:
    """Map a PaymentIntent to our charge states. requires_confirmation counts as needing
    the customer, processing as pending, a returned card as failed."""
    error = pi.get("last_payment_error") or {}
    match pi.get("status"):
        case "succeeded":
            status: Literal["succeeded", "pending", "requires_action", "failed"] = "succeeded"
        case "processing":
            status = "pending"
        case "requires_action" | "requires_confirmation":
            status = "requires_action"
        case "requires_payment_method" if error.get("code") == AUTH_REQUIRED:
            # Off-session, a bank that wants the customer to authenticate declines this way.
            status = "requires_action"
        case _:  # requires_payment_method (declined), canceled
            status = "failed"
    reason = None
    if status == "failed":
        reason = (
            "The payment was cancelled."
            if pi.get("status") == "canceled"
            else error.get("message") or "The card was declined."
        )
    elif status == "requires_action":
        reason = "The bank wants the customer to confirm the payment."
    meta = pi.get("metadata") or {}
    created = pi.get("created")
    return ChargeResult(
        status=status,
        charge_id=ref_id(pi.get("latest_charge")) if status == "succeeded" else None,
        payment_intent_id=pi.get("id"),
        amount_pence=int(pi.get("amount") or 0),
        fee_pence=int(pi.get("application_fee_amount") or 0),
        idempotency_key=idempotency_key or meta.get("idempotency_key") or "",
        failure_reason=reason,
        failure_code=(error.get("decline_code") or error.get("code") or None) if status != "succeeded" else None,
        created_at=datetime.fromtimestamp(created, UTC) if created else utcnow(),
    )


def refund_state(re: Json) -> RefundResult:
    """A Stripe Refund as our RefundResult (the customer's refund only)."""
    status = re.get("status")
    mapped: Literal["succeeded", "pending", "failed"] = (
        "succeeded" if status == "succeeded" else "failed" if status in ("failed", "canceled") else "pending"
    )
    return RefundResult(
        status=mapped,
        refund_id=re.get("id"),
        amount_pence=int(re.get("amount") or 0),
        fee_refunded_pence=0,
        failure_reason=(re.get("failure_reason") or "The refund failed.")
        if mapped == "failed"
        else "Stripe is still processing the refund."
        if mapped == "pending"
        else None,
    )


class StripeGateway:
    name: Literal["stripe"] = "stripe"

    def __init__(self, client: StripeClient, publishable_key: str = ""):
        self.c = client.v1
        self.publishable_key = publishable_key

    # ------------------------------------------------------------------ providers
    async def create_provider_account(self, provider: ProviderRef) -> ProviderAccount:
        params: Json = {
            "type": "express",
            "country": "GB",
            "business_type": "individual",
            "capabilities": {"card_payments": {"requested": True}, "transfers": {"requested": True}},
            "metadata": {"provider_id": provider.provider_id},
        }
        if provider.email:
            params["email"] = provider.email
        acct = await self.c.accounts.create_async(
            params,  # type: ignore[arg-type]
            {"idempotency_key": f"account:{provider.provider_id}"},
        )
        return provider_account_from_stripe(as_dict(acct))

    async def onboarding_link(self, account_id: str, *, return_url: str, refresh_url: str) -> str:
        link = await self.c.account_links.create_async(
            {"account": account_id, "type": "account_onboarding", "return_url": return_url, "refresh_url": refresh_url}
        )
        return as_dict(link)["url"]

    async def account_status(self, account_id: str) -> ProviderAccount:
        return provider_account_from_stripe(as_dict(await self.c.accounts.retrieve_async(account_id)))

    # ------------------------------------------------------------------ customers and cards
    async def save_card_setup(self, customer: CustomerRef) -> CardSetup:
        cus = customer.gateway_customer_id
        if not cus:
            params: Json = {"name": customer.name, "metadata": {"customer_id": customer.customer_id}}
            if customer.email:
                params["email"] = customer.email
            if customer.phone:
                params["phone"] = customer.phone
            created = await self.c.customers.create_async(
                params,  # type: ignore[arg-type]
                {"idempotency_key": f"customer:{customer.customer_id}"},
            )
            cus = as_dict(created)["id"]
        si = as_dict(
            await self.c.setup_intents.create_async(
                {
                    "customer": cus,
                    "usage": "off_session",
                    "payment_method_types": ["card"],
                    "metadata": {"customer_id": customer.customer_id},
                }
            )
        )
        return CardSetup(
            gateway="stripe",
            gateway_customer_id=cus,
            setup_id=si["id"],
            client_secret=si.get("client_secret"),
            publishable_key=self.publishable_key or None,
            status="succeeded" if si.get("status") == "succeeded" else "requires_confirmation",
        )

    async def card_setup_status(self, setup_id: str) -> CardSetupStatus:
        si = as_dict(await self.c.setup_intents.retrieve_async(setup_id, {"expand": ["payment_method"]}))
        match si.get("status"):
            case "succeeded":
                pm = si.get("payment_method")
                pm = as_dict(pm) if pm and not isinstance(pm, str) else {}
                if not pm:  # not expanded (shouldn't happen): fetch it
                    pm = as_dict(await self.c.payment_methods.retrieve_async(ref_id(si.get("payment_method")) or ""))
                card = pm.get("card") or {}
                if si.get("customer") and pm.get("id"):
                    # Off-session charges use the customer's default payment method.
                    await self.c.customers.update_async(
                        ref_id(si["customer"]) or "", {"invoice_settings": {"default_payment_method": pm["id"]}}
                    )
                return CardSetupStatus(
                    setup_id=setup_id,
                    status="succeeded",
                    card=SavedCardInfo(
                        brand=card.get("brand", "card"),
                        last4=card.get("last4", "????"),
                        exp_month=int(card.get("exp_month") or 0),
                        exp_year=int(card.get("exp_year") or 0),
                    ),
                )
            case "processing":
                return CardSetupStatus(setup_id=setup_id, status="processing")
            case "canceled":
                return CardSetupStatus(
                    setup_id=setup_id, status="failed", failure_reason="The card setup was cancelled."
                )
            case "requires_payment_method" if si.get("last_setup_error"):
                err = si["last_setup_error"]
                return CardSetupStatus(
                    setup_id=setup_id, status="failed", failure_reason=err.get("message") or "The card wasn't accepted."
                )
            case _:
                return CardSetupStatus(setup_id=setup_id, status="requires_confirmation")

    async def _payment_method(self, customer_id: str) -> str | None:
        cus = as_dict(await self.c.customers.retrieve_async(customer_id))
        default = ref_id((cus.get("invoice_settings") or {}).get("default_payment_method"))
        if default:
            return default
        pms = as_dict(await self.c.payment_methods.list_async({"customer": customer_id, "type": "card", "limit": 1}))
        data = pms.get("data") or []
        return data[0]["id"] if data else None

    # ------------------------------------------------------------------ charges
    async def charge_visit(
        self,
        visit: VisitRef,
        price_pence: int,
        fee_pence: int,
        provider_account: str,
        *,
        idempotency_key: str | None = None,
        purpose: Literal["visit", "tip"] = "visit",
    ) -> ChargeResult:
        key = idempotency_key or f"visit:{visit.visit_id}:{purpose}"

        def outcome(status: Literal["pending", "failed"], reason: str, code: str) -> ChargeResult:
            return ChargeResult(
                status=status,
                amount_pence=price_pence,
                fee_pence=fee_pence,
                idempotency_key=key,
                failure_reason=reason,
                failure_code=code,
                created_at=utcnow(),
            )

        try:
            pm = await self._payment_method(visit.gateway_customer_id)
        except stripe.APIConnectionError, stripe.APIError, stripe.RateLimitError:
            return outcome("pending", UNREACHABLE, PLATFORM_FAILURE + "unreachable")
        except stripe.StripeError as e:
            code = PLATFORM_FAILURE + (e.code or "error")
            return outcome("failed", "The customer's saved card couldn't be found.", code)
        if pm is None:
            return outcome("failed", "There's no saved card to charge.", "no_saved_card")
        params: Json = {
            "amount": price_pence,
            "currency": CURRENCY,
            "customer": visit.gateway_customer_id,
            "payment_method": pm,
            "off_session": True,
            "confirm": True,
            "on_behalf_of": provider_account,
            "transfer_data": {"destination": provider_account},
            "transfer_group": f"visit_{visit.visit_id}",
            "description": visit.description[:1000],
            "metadata": {
                "visit_id": visit.visit_id,
                "booking_id": visit.booking_id,
                "customer_id": visit.customer_id,
                "purpose": purpose,
                "idempotency_key": key,
            },
        }
        if fee_pence > 0:
            params["application_fee_amount"] = fee_pence
        try:
            pi = await self.c.payment_intents.create_async(params, {"idempotency_key": key})  # type: ignore[arg-type]
        except stripe.CardError as e:
            failed_pi = as_dict(as_dict(e.error).get("payment_intent")) if e.error else {}
            needs_customer = e.code == AUTH_REQUIRED or failed_pi.get("status") == "requires_action"
            return ChargeResult(
                status="requires_action" if needs_customer else "failed",
                payment_intent_id=failed_pi.get("id"),
                amount_pence=price_pence,
                fee_pence=fee_pence,
                idempotency_key=key,
                failure_reason="The bank wants the customer to confirm the payment."
                if needs_customer
                else e.user_message or "The card was declined.",
                failure_code=AUTH_REQUIRED if needs_customer else (as_dict(e.error).get("decline_code") or e.code),
                created_at=utcnow(),
            )
        except stripe.APIConnectionError, stripe.APIError, stripe.RateLimitError:
            # The outcome is unknown: repeating the call with the same key, or the webhook, settles it.
            log.warning("stripe unreachable charging visit %s", visit.visit_id)
            return outcome("pending", UNREACHABLE, PLATFORM_FAILURE + "unreachable")
        except stripe.IdempotencyError:
            # Another request with this key is still in flight: its result (or the webhook) settles it.
            log.warning("concurrent charge for visit %s (%s)", visit.visit_id, key)
            return outcome(
                "pending", "Another request for this payment is in progress.", PLATFORM_FAILURE + "in_flight"
            )
        except stripe.StripeError as e:
            # Not the card: our request or the provider's account (capabilities, a bad key...).
            log.error("stripe refused a charge for visit %s: %s", visit.visit_id, e.code)
            return outcome(
                "failed",
                "Stripe couldn't take this payment: " + (e.user_message or str(e.code or "error")),
                PLATFORM_FAILURE + (e.code or "error"),
            )
        return charge_result_from_intent(as_dict(pi), idempotency_key=key)

    async def charge_status(self, payment_intent_id: str) -> ChargeResult:
        return charge_result_from_intent(as_dict(await self.c.payment_intents.retrieve_async(payment_intent_id)))

    async def cancel_charge(self, payment_intent_id: str) -> ChargeResult:
        current = await self.charge_status(payment_intent_id)
        if current.status == "succeeded":
            return current
        try:
            pi = await self.c.payment_intents.cancel_async(payment_intent_id)
        except stripe.InvalidRequestError:
            # Already cancelled, or it went through in the meantime: report where it ended up.
            return await self.charge_status(payment_intent_id)
        return charge_result_from_intent(as_dict(pi))

    # ------------------------------------------------------------------ refunds
    async def refund(
        self,
        charge_id: str,
        amount_pence: int,
        fee_refund_pence: int,
        *,
        reason: str,
        idempotency_key: str | None = None,
    ) -> RefundResult:
        def result(status: Literal["succeeded", "pending", "failed"], reason_: str | None, re_id: str | None = None):
            return RefundResult(
                status=status, refund_id=re_id, amount_pence=amount_pence, fee_refunded_pence=0, failure_reason=reason_
            )

        opts: Any = {"idempotency_key": idempotency_key} if idempotency_key else {}
        try:
            re = as_dict(
                await self.c.refunds.create_async(
                    {
                        "charge": charge_id,
                        "amount": amount_pence,
                        "reverse_transfer": True,  # the provider funds the refund
                        "refund_application_fee": False,  # our fee goes back exactly, below
                        "metadata": {
                            "reason": reason[:500],
                            "fee_refund_pence": str(fee_refund_pence),
                            "intent": idempotency_key or "",
                        },
                    },
                    opts,
                )
            )
        except stripe.APIConnectionError, stripe.APIError, stripe.RateLimitError, stripe.IdempotencyError:
            # Stripe may have made the refund: repeat with the same key (or wait for the webhook).
            log.warning("refund of %s: outcome unknown", charge_id)
            return result("pending", UNREACHABLE_REFUND)
        except stripe.StripeError as e:
            return result("failed", e.user_message or "Stripe couldn't make this refund.")
        state = refund_state(re)
        if state.status != "succeeded":
            # Our fee goes back once the customer's refund has gone through (refund.updated).
            return state.model_copy(update={"amount_pence": amount_pence})
        if fee_refund_pence <= 0:
            return state.model_copy(update={"amount_pence": amount_pence})
        fee = await self.refund_fee(
            charge_id, fee_refund_pence, idempotency_key=f"{idempotency_key}:fee" if idempotency_key else ""
        )
        return state.model_copy(
            update={
                "amount_pence": amount_pence,
                "fee_refunded_pence": fee.fee_refunded_pence,
                "failure_reason": None if fee.status == "succeeded" else fee.failure_reason,
            }
        )

    async def refund_status(self, refund_id: str) -> RefundResult:
        return refund_state(as_dict(await self.c.refunds.retrieve_async(refund_id)))

    async def refund_fee(self, charge_id: str, fee_refund_pence: int, *, idempotency_key: str) -> RefundResult:
        def result(status: Literal["succeeded", "pending", "failed"], done: int, reason: str | None = None):
            return RefundResult(status=status, amount_pence=0, fee_refunded_pence=done, failure_reason=reason)

        opts: Any = {"idempotency_key": idempotency_key} if idempotency_key else {}
        try:
            fee_id = ref_id(as_dict(await self.c.charges.retrieve_async(charge_id)).get("application_fee"))
            if not fee_id:
                return result("succeeded", 0)  # no fee on this charge (a tip)
            await self.c.application_fees.refunds.create_async(
                fee_id, {"amount": fee_refund_pence, "metadata": {"intent": idempotency_key}}, opts
            )
        except stripe.APIConnectionError, stripe.APIError, stripe.RateLimitError, stripe.IdempotencyError:
            log.warning("application fee refund for %s: outcome unknown", charge_id)
            return result("pending", 0, FEE_RETRY)
        except stripe.StripeError as e:
            log.error("application fee refund for %s refused: %s", charge_id, e.code)
            return result("failed", 0, FEE_RETRY + " Stripe said: " + (e.user_message or str(e.code)))
        return result("succeeded", fee_refund_pence)

    # ------------------------------------------------------------------ payouts
    async def payout_summary(self, provider_account: str, *, limit: int = 8) -> PayoutSummary:
        opts: Any = {"stripe_account": provider_account}
        listed = as_dict(await self.c.payouts.list_async({"limit": limit, "expand": ["data.destination"]}, opts))
        balance = as_dict(await self.c.balance.retrieve_async(None, opts))
        payouts: list[Payout] = []
        for po in listed.get("data") or []:
            dest = po.get("destination")
            status = po.get("status")
            payouts.append(
                Payout(
                    payout_id=po["id"],
                    arrival_date=_local_date(po.get("arrival_date")) or utcnow().date(),
                    amount_pence=int(po.get("amount") or 0),
                    status=status if status in ("paid", "in_transit", "pending") else "failed",
                    bank_last4=as_dict(dest).get("last4") if dest and not isinstance(dest, str) else None,
                )
            )
        unpaid = sum(
            int(b.get("amount") or 0)
            for part in ("available", "pending")
            for b in balance.get(part) or []
            if b.get("currency") == CURRENCY
        )
        upcoming = sorted(p.arrival_date for p in payouts if p.status in ("pending", "in_transit"))
        return PayoutSummary(
            account_id=provider_account,
            payouts=payouts,
            pending_pence=max(unpaid, 0),
            next_payout_date=upcoming[0] if upcoming else None,
        )
