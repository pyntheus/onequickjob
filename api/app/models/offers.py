"""offers: a provider's counter-offer on an open request. Owner: F (marketplace core).

Accepting at the guide price is not an offer: it books the request directly.
A pending counter waits for the customer to accept it or keep waiting; if anyone
books the request first, pending counters lapse.
"""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.common import Pence, Timestamped

OfferStatus = Literal["pending", "accepted", "declined", "lapsed", "withdrawn"]


class Offer(Timestamped):
    """Immutable terms: a provider who changes their price withdraws this offer and makes a
    new one, so a customer always accepts exactly the price they saw."""

    COLLECTION: ClassVar[str] = "offers"

    request_id: str
    provider_id: str
    price_pence: Pence = Field(description="Suggested price per visit")
    first_price_pence: Pence | None = Field(
        default=None,
        description="First-visit price: the first-visit guide x price / guide, half-up to whole pounds. "
        "None when the job has no separate first-visit price",
    )
    guide_pence: Pence = Field(description="The guide price when the counter was made")
    first_guide_pence: Pence | None = Field(default=None, description="The first-visit guide when the counter was made")
    reasons: list[str] = Field(default_factory=list)
    message: str = ""
    status: OfferStatus = "pending"
    supersedes: str | None = Field(default=None, description="The offer this one replaced (now withdrawn)")
    decided_at: datetime | None = None
