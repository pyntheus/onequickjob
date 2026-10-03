"""bookings. Owner: F creates (marketplace core, own-customer invites via
app.services.bookings); L1 cancels; L3 reads."""

from pymongo import DESCENDING

from app.core.db import DbSession
from app.models.bookings import Booking
from app.repos.base import Repo, idx

_STR = {"$type": "string"}


class Bookings(Repo[Booking]):
    model = Booking
    indexes = [
        idx("ref", unique=True),
        # One booking per request and per invite: makes booking creation idempotent.
        idx("request_id", unique=True, partialFilterExpression={"request_id": _STR}),
        idx("invite_id", unique=True, partialFilterExpression={"invite_id": _STR}),
        idx("customer_id", ("created_at", DESCENDING)),
        idx("provider_id", "status"),
    ]

    async def by_request(self, request_id: str, *, session: DbSession | None = None) -> Booking | None:
        return await self.find_one({"request_id": request_id}, session=session)
