"""own_customer_invites. Owner: L2 (create); L1 (accept)."""

from app.models.provider_ops import OwnCustomerInvite
from app.repos.base import Repo, idx

_STR = {"$type": "string"}


class OwnCustomerInvites(Repo[OwnCustomerInvite]):
    model = OwnCustomerInvite
    indexes = [
        idx("provider_id", "status"),
        idx("phone"),
        idx("token_hash", unique=True, partialFilterExpression={"token_hash": _STR}),
    ]

    async def by_token_hash(self, token_hash: str) -> OwnCustomerInvite | None:
        return await self.find_one({"token_hash": token_hash})
