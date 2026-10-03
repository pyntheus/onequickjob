"""customers. Owner: L1."""

from app.core.db import DbSession
from app.models.common import Address
from app.models.customers import Customer, CustomerPayment
from app.repos.base import Repo, idx


class Customers(Repo[Customer]):
    model = Customer
    indexes = [idx("user_id", unique=True)]

    async def by_user(self, user_id: str, *, session: DbSession | None = None) -> Customer | None:
        return await self.find_one({"user_id": user_id}, session=session)

    async def add_address(
        self, customer_id: str, address: Address, *, session: DbSession | None = None
    ) -> Customer | None:
        """Adds the address unless one with the same UPRN (or same label) is already saved."""
        c = await self.get(customer_id, session=session)
        if c is None:
            return None
        if any((a.uprn and a.uprn == address.uprn) or a.label == address.label for a in c.addresses):
            return c
        return await self.update(
            customer_id, {}, push={"addresses": address.model_dump(mode="python")}, session=session
        )

    async def set_payment(
        self, customer_id: str, payment: CustomerPayment, *, session: DbSession | None = None
    ) -> Customer | None:
        return await self.update(customer_id, {"payment": payment.model_dump(mode="python")}, session=session)
