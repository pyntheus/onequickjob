"""time_off and own_customer_invites. Owner: L2 (L1 accepts invites)."""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.bookings import Frequency
from app.models.common import E164, IsoDate, Model, Pence, Timestamped


class Arrangement(Model):
    visit_id: str
    action: Literal["cover", "helper", "skip"]
    helper_user_id: str | None = None
    cover_request_id: str | None = None
    state: Literal["planned", "arranged", "done", "failed"] = "planned"


class TimeOff(Timestamped):
    COLLECTION: ClassVar[str] = "time_off"

    provider_id: str
    from_date: IsoDate
    to_date: IsoDate
    status: Literal["planned", "active", "done", "cancelled"] = "planned"
    arrangements: list[Arrangement] = Field(default_factory=list)


class OwnCustomerInvite(Timestamped):
    """A provider inviting a customer they already have, at the provider's own price.

    Invite-only rule: a number that already belongs to a platform customer is blocked
    (status blocked, kept for the admin count) and they stay on the standard fee.
    """

    COLLECTION: ClassVar[str] = "own_customer_invites"

    provider_id: str
    name: str
    phone: E164
    category_id: str
    price_pence: Pence
    frequency: Frequency
    token_hash: str | None = Field(default=None, description="HMAC of the token in the invite link")
    status: Literal["invited", "accepted", "declined", "blocked", "expired"] = "invited"
    blocked_reason: str | None = None
    customer_id: str | None = None
    booking_id: str | None = None
    accepted_at: datetime | None = None
    outbox_id: str | None = None
