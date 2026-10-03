"""disputes. Owner: L3 (L1 opens them). We mediate; we don't guarantee."""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.common import Model, Pence, Timestamped

DisputeStage = Literal[0, 1, 2, 3]
DISPUTE_STAGES = ("Reported", "Provider replied", "Fix agreed", "Closed")


class DisputeEvent(Model):
    at: datetime
    by_user_id: str | None = None
    kind: Literal["opened", "provider_replied", "proposed", "agreed", "message", "refunded", "closed"]
    text: str = ""


class Resolution(Model):
    kind: Literal["return_visit", "partial_refund", "full_refund", "none"]
    amount_pence: Pence | None = None
    refund_id: str | None = None
    funded_by: Literal["provider"] = "provider"
    note: str = ""


class DisputeClosing(Model):
    """A close in progress (L3): claimed before any refund, so two closes can't both refund."""

    outcome: Literal["return_visit", "partial_refund", "full_refund", "none"]
    amount_pence: Pence | None = None
    attempt: int
    note: str = ""
    by_user_id: str | None = None
    at: datetime

    def refund_intent_id(self, dispute_id: str) -> str:
        """Each close attempt's one refund, always under the same key."""
        return f"dispute-{dispute_id}-close-{self.attempt}"


class Dispute(Timestamped):
    """We mediate; we don't guarantee. Refunds are provider-funded (decisions.md)."""

    COLLECTION: ClassVar[str] = "disputes"

    ref: str = Field(description="Human reference, e.g. D-014")
    visit_id: str
    booking_id: str
    customer_id: str
    provider_id: str
    category_id: str
    title: str
    description: str = ""
    photos: list[str] = Field(default_factory=list)
    amount_pence: Pence = Field(description="Value of the visit in dispute")
    stage: DisputeStage = Field(default=0, description="Index into Reported, Provider replied, Fix agreed, Closed")
    status_text: str = Field(description="One line for the admin card, e.g. Waiting for Alan's reply")
    proposed: Resolution | None = None
    resolution: Resolution | None = None
    thread_id: str | None = None
    events: list[DisputeEvent] = Field(default_factory=list)
    closed_at: datetime | None = None
    closing: DisputeClosing | None = Field(default=None, description="A close in progress (L3)")
    close_attempts: int = Field(default=0, description="Closes started, for each one's refund key (L3)")
