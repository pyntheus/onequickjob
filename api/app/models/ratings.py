"""ratings. Owner: L1."""

from typing import ClassVar

from pydantic import Field

from app.models.common import Pence, Timestamped


class Rating(Timestamped):
    COLLECTION: ClassVar[str] = "ratings"

    visit_id: str
    booking_id: str
    customer_id: str
    provider_id: str
    stars: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    tip_pence: Pence = 0
    comment: str = ""
