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
    COLLECTION: ClassVar[str] = "offers"

    request_id: str
    provider_id: str
    price_pence: Pence = Field(description="Suggested price per visit")
    first_price_pence: Pence | None = Field(default=None, description="Optional different first-visit price")
    guide_pence: Pence = Field(description="The guide price when the counter was made")
    reasons: list[str] = Field(default_factory=list)
    message: str = ""
    status: OfferStatus = "pending"
    decided_at: datetime | None = None
