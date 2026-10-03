"""The fake gateway: behaves like a happy-path Stripe, stores what it did in Mongo
(fake_gateway collection) so payouts and refunds are consistent across restarts.

Test card behaviour: every card is a Visa ending 4242 (12/28) and every charge succeeds,
unless the customer name contains "decline" (charge fails) or "3ds" (requires_action),
so failure paths can be demoed. Payouts are every Friday for charges up to the Tuesday.
"""

from datetime import date, timedelta
from typing import Literal

from pymongo.asynchronous.database import AsyncDatabase

from app.adapters.payments.base import (
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
from app.core.ids import new_id
from app.core.timeutil import london_today, to_london, utcnow

COLL = "fake_gateway"
CARD = SavedCardInfo(brand="visa", last4="4242", exp_month=12, exp_year=2028)


def next_friday(d: date) -> date:
    return d + timedelta(days=(4 - d.weekday()) % 7 or 7)


class FakeGateway:
    name: Literal["fake"] = "fake"

    def __init__(self, db: AsyncDatabase, public_base_url: str = ""):
        self.db = db
        self.coll = db[COLL]
        self.base = public_base_url.rstrip("/")

    async def create_provider_account(self, provider: ProviderRef) -> ProviderAccount:
        acct = f"acct_fake_{new_id()[-12:]}"
        await self.coll.insert_one(
            {
                "_id": acct,
                "kind": "account",
                "provider_id": provider.provider_id,
                "status": "pending",
                "created_at": utcnow(),
            }
        )
        return ProviderAccount(
            account_id=acct, status="pending", payouts_enabled=False, requirements_due=["onboarding"]
        )

    async def onboarding_link(self, account_id: str, *, return_url: str, refresh_url: str) -> str:
        # The fake has no hosted onboarding: completing it is instant.
        await self.coll.update_one({"_id": account_id}, {"$set": {"status": "enabled", "bank_last4": "2100"}})
        return return_url

    async def account_status(self, account_id: str) -> ProviderAccount:
        doc = await self.coll.find_one({"_id": account_id}) or {}
        enabled = doc.get("status") == "enabled"
        return ProviderAccount(
            account_id=account_id,
            status="enabled" if enabled else "pending",
            payouts_enabled=enabled,
            bank_last4=doc.get("bank_last4"),
            requirements_due=[] if enabled else ["onboarding"],
        )

    async def save_card_setup(self, customer: CustomerRef) -> CardSetup:
        cus = customer.gateway_customer_id or f"cus_fake_{new_id()[-12:]}"
        seti = f"seti_fake_{new_id()[-12:]}"
        await self.coll.insert_one(
            {
                "_id": seti,
                "kind": "setup",
                "customer": cus,
                "name": customer.name,
                "status": "succeeded",
                "created_at": utcnow(),
            }
        )
        await self.coll.update_one({"_id": cus}, {"$set": {"kind": "customer", "name": customer.name}}, upsert=True)
        return CardSetup(gateway="fake", gateway_customer_id=cus, setup_id=seti, status="succeeded")

    async def card_setup_status(self, setup_id: str) -> CardSetupStatus:
        doc = await self.coll.find_one({"_id": setup_id})
        if doc is None:
            return CardSetupStatus(setup_id=setup_id, status="failed", failure_reason="Unknown setup")
        return CardSetupStatus(setup_id=setup_id, status="succeeded", card=CARD)

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
        existing = await self.coll.find_one({"kind": "charge", "idempotency_key": key})
        if existing:
            return ChargeResult.model_validate(existing["result"])
        cust = await self.coll.find_one({"_id": visit.gateway_customer_id}) or {}
        name = (cust.get("name") or "").lower()
        status = "failed" if "decline" in name else "requires_action" if "3ds" in name else "succeeded"
        ch = f"ch_fake_{new_id()[-12:]}"
        result = ChargeResult(
            status=status,
            charge_id=ch if status == "succeeded" else None,
            payment_intent_id=f"pi_fake_{new_id()[-12:]}",
            amount_pence=price_pence,
            fee_pence=fee_pence,
            idempotency_key=key,
            created_at=utcnow(),
            failure_reason={
                "failed": "Your card was declined.",
                "requires_action": "The bank wants the customer to confirm.",
            }.get(status),
        )
        await self.coll.insert_one(
            {
                "_id": ch,
                "kind": "charge",
                "idempotency_key": key,
                "account": provider_account,
                "visit_id": visit.visit_id,
                "net_pence": price_pence - fee_pence,
                "refunded_pence": 0,
                "result": result.model_dump(mode="python"),
            }
        )
        return result

    async def refund(self, charge_id: str, amount_pence: int, fee_refund_pence: int, *, reason: str) -> RefundResult:
        ch = await self.coll.find_one({"_id": charge_id, "kind": "charge"})
        if ch is None:
            return RefundResult(
                status="failed", amount_pence=amount_pence, fee_refunded_pence=0, failure_reason="No such charge"
            )
        if ch["refunded_pence"] + amount_pence > ch["result"]["amount_pence"]:
            return RefundResult(
                status="failed",
                amount_pence=amount_pence,
                fee_refunded_pence=0,
                failure_reason="That's more than is left to refund",
            )
        re_id = f"re_fake_{new_id()[-12:]}"
        await self.coll.update_one(
            {"_id": charge_id},
            {"$inc": {"refunded_pence": amount_pence, "net_pence": -(amount_pence - fee_refund_pence)}},
        )
        return RefundResult(
            status="succeeded", refund_id=re_id, amount_pence=amount_pence, fee_refunded_pence=fee_refund_pence
        )

    async def payout_summary(self, provider_account: str, *, limit: int = 8) -> PayoutSummary:
        """Charges are paid out the Friday after they're made (Friday's own go next week)."""
        today = london_today()
        by_friday: dict[date, int] = {}
        async for ch in self.coll.find({"kind": "charge", "account": provider_account, "result.status": "succeeded"}):
            day = to_london(ch["result"]["created_at"]).date()
            by_friday[next_friday(day)] = by_friday.get(next_friday(day), 0) + int(ch["net_pence"])
        payouts = [
            Payout(
                payout_id=f"po_fake_{f:%Y%m%d}",
                arrival_date=f,
                amount_pence=amt,
                status="paid" if f <= today else "pending",
                bank_last4="2100",
            )
            for f, amt in sorted(by_friday.items(), reverse=True)
        ]
        pending = sum(p.amount_pence for p in payouts if p.status != "paid")
        return PayoutSummary(
            account_id=provider_account,
            payouts=[p for p in payouts if p.status == "paid"][:limit],
            pending_pence=pending,
            next_payout_date=next_friday(today - timedelta(days=1)),
        )
