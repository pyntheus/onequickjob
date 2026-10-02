"""FastAPI dependencies for auth. Use these in every lane:

    user: CurrentUser = Depends(current_user)          # any signed-in user
    customer: Customer = Depends(current_customer)     # signed in, with a customers doc
    provider: Provider = Depends(current_provider)     # signed in with the provider role
    admin: User = Depends(require_admin)

Helpers (users with helper_of set) get a provider context for the provider they help:
current_provider returns that provider, and `acting_as_helper` is True.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Depends, Request, status

from app.core.config import Settings, get_settings
from app.core.db import Db, get_db
from app.core.errors import fail
from app.models.common import Actor
from app.models.customers import Customer
from app.models.providers import Provider
from app.models.users import Session, User
from app.repos.customers import Customers
from app.repos.providers import Providers
from app.services.auth import session_user

if TYPE_CHECKING:
    from app.adapters.address.base import AddressLookup
    from app.adapters.payments.base import PaymentGateway


@dataclass(frozen=True)
class CurrentUser:
    user: User
    session: Session

    @property
    def id(self) -> str:
        return self.user.id

    def actor(self, role: str | None = None) -> Actor:
        return Actor(kind="user", user_id=self.user.id, role=role, name=self.user.name)  # type: ignore[arg-type]


def settings_dep(request: Request) -> Settings:
    """The app's settings (tests build apps with their own)."""
    return getattr(request.app.state, "settings", None) or get_settings()


def gateway_dep(request: Request, db: Db = Depends(get_db)) -> PaymentGateway:
    from app.adapters.payments import make_payment_gateway

    return make_payment_gateway(settings_dep(request), db)


def address_dep(request: Request, db: Db = Depends(get_db)) -> AddressLookup:
    from app.adapters.address import make_address_lookup

    return make_address_lookup(settings_dep(request), db)


async def current_user_optional(
    request: Request, db: Db = Depends(get_db), s: Settings = Depends(settings_dep)
) -> CurrentUser | None:
    found = await session_user(db, s, request.cookies.get(s.cookie_name))
    return None if found is None else CurrentUser(user=found[1], session=found[0])


async def current_user(cu: CurrentUser | None = Depends(current_user_optional)) -> CurrentUser:
    if cu is None:
        fail(status.HTTP_401_UNAUTHORIZED, "not_signed_in", "Please sign in.")
    return cu


async def require_admin(cu: CurrentUser = Depends(current_user)) -> CurrentUser:
    if "admin" not in cu.user.roles:
        fail(status.HTTP_403_FORBIDDEN, "admins_only", "This is for the OneQuickJob team only.")
    return cu


async def current_customer(cu: CurrentUser = Depends(current_user), db: Db = Depends(get_db)) -> Customer:
    """The signed-in user's customer record. 404 until their first request or invite creates it."""
    if "customer" not in cu.user.roles:
        fail(status.HTTP_403_FORBIDDEN, "customers_only", "This is for customers.")
    customer = await Customers(db).by_user(cu.user.id)
    if customer is None:
        fail(status.HTTP_404_NOT_FOUND, "no_customer_profile", "You haven't booked anything yet.")
    return customer


async def current_provider(cu: CurrentUser = Depends(current_user), db: Db = Depends(get_db)) -> Provider:
    providers = Providers(db)
    if cu.user.helper_of:
        provider = await providers.get(cu.user.helper_of)
    elif "provider" in cu.user.roles:
        provider = await providers.by_user(cu.user.id)
    else:
        provider = None
    if provider is None:
        fail(status.HTTP_403_FORBIDDEN, "providers_only", "This is for providers. Sign up to earn with OneQuickJob.")
    # Suspended providers can still sign in to see earnings and records; taking jobs is
    # refused by app.services.eligibility.can_take.
    return provider
