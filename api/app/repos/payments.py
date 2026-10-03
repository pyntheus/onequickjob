"""payment_events, payment_refunds and payment_attempts. Owner: L3 (app.payments).

Not yet in app.repos.ALL (F's registry): the payments router creates both collections and their
indexes at start-up (app.payments.store.ensure_payment_collections) until integration adds them.
"""

from pymongo import DESCENDING

from app.core.db import DbSession
from app.core.timeutil import utcnow
from app.models.payments import ChargeAttempt, PaymentEvent, RefundIntent, RefundStatus
from app.repos.base import Repo, idx


class PaymentEvents(Repo[PaymentEvent]):
    model = PaymentEvent
    touch_updated_at = False
    indexes = [
        idx(("received_at", DESCENDING)),
        idx("type", ("received_at", DESCENDING)),
        idx("payment_intent", partialFilterExpression={"outcome": "deferred"}, name="deferred_by_intent"),
    ]

    async def claim(self, event: PaymentEvent, *, session: DbSession | None = None) -> bool:
        """Record the event; False if it was already recorded (a duplicate delivery). Inside a
        transaction, two concurrent deliveries conflict and the driver re-runs one, which then
        sees the other's record."""
        res = await self.coll.update_one(
            {"_id": event.id}, {"$setOnInsert": event.to_mongo()}, upsert=True, session=self.s(session)
        )
        return res.upserted_id is not None

    async def set_outcome(
        self,
        event_id: str,
        outcome: str,
        note: str = "",
        *,
        payment_intent: str | None = None,
        payload: dict | None = None,
        session: DbSession | None = None,
    ):
        await self.coll.update_one(
            {"_id": event_id},
            {"$set": {"outcome": outcome, "note": note[:300], "payment_intent": payment_intent, "payload": payload}},
            session=self.s(session),
        )

    async def deferred_for(self, payment_intent: str, *, session: DbSession | None = None) -> list[PaymentEvent]:
        return await self.find(
            {"outcome": "deferred", "payment_intent": payment_intent}, sort=[("received_at", 1)], session=session
        )


class PaymentRefunds(Repo[RefundIntent]):
    model = RefundIntent
    indexes = [idx("visit_id", "created_at"), idx("status", "created_at"), idx("dispute_id"), idx("refund_id")]

    async def for_visit(self, visit_id: str, *, session: DbSession | None = None) -> list[RefundIntent]:
        return await self.find({"visit_id": visit_id}, sort=[("created_at", 1)], session=session)

    async def unsettled(self, visit_id: str, *, session: DbSession | None = None) -> list[RefundIntent]:
        """Refunds asked for whose customer refund isn't confirmed yet (still reserved)."""
        return [r for r in await self.for_visit(visit_id, session=session) if r.status == "pending"]

    async def unsettled_pence(self, visit_id: str, *, session: DbSession | None = None) -> int:
        return sum(r.amount_pence for r in await self.unsettled(visit_id, session=session))

    async def by_refund_id(self, refund_id: str, *, session: DbSession | None = None) -> RefundIntent | None:
        return await self.find_one({"refund_id": refund_id}, session=session)

    async def note_pending(
        self, intent_id: str, *, refund_id: str | None, failure_reason: str | None, session: DbSession | None = None
    ) -> RefundIntent | None:
        """Still pending at the gateway: remember the refund id once known, and why it's waiting."""
        fields: dict = {"failure_reason": failure_reason}
        if refund_id:
            fields["refund_id"] = refund_id
        return await self.update(intent_id, fields, extra_filter={"status": "pending"}, session=session)

    async def settle(
        self,
        intent_id: str,
        status: RefundStatus,
        *,
        refund_id: str | None,
        failure_reason: str | None,
        session: DbSession | None = None,
    ) -> RefundIntent | None:
        """Move a pending (or fee_pending) intent to its result; None if it had already moved."""
        return await self.update(
            intent_id,
            {"status": status, "refund_id": refund_id, "failure_reason": failure_reason, "recorded_at": utcnow()},
            extra_filter={"status": {"$in": ["pending", "fee_pending"]}},
            session=session,
        )


class ChargeAttempts(Repo[ChargeAttempt]):
    model = ChargeAttempt
    touch_updated_at = False
    indexes = [idx("visit_id")]
