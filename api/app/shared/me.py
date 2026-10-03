"""Building the Me response and setting the session cookie."""

from fastapi import Response

from app.core.config import Settings
from app.core.db import Db
from app.core.phone import to_national
from app.models.users import User
from app.repos.customers import Customers
from app.repos.providers import Providers
from app.shared.schemas import Me


def home_path(roles: list[str], helper: bool = False) -> str:
    if "admin" in roles:
        return "/admin"
    if "provider" in roles or helper:
        return "/p"
    return "/account"


async def build_me(db: Db, user: User) -> Me:
    customer = await Customers(db).by_user(user.id)
    provider = await Providers(db).by_user(user.id) if "provider" in user.roles else None
    return Me(
        user_id=user.id,
        name=user.name,
        phone=to_national(user.phone) if user.phone else None,
        email=user.email,
        roles=user.roles,
        customer_id=customer.id if customer else None,
        provider_id=provider.id if provider else None,
        helper_of=user.helper_of,
        home_path=home_path(user.roles, bool(user.helper_of)),
    )


def set_session_cookie(response: Response, s: Settings, token: str) -> None:
    response.set_cookie(
        s.cookie_name,
        token,
        max_age=s.session_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, s: Settings) -> None:
    response.delete_cookie(s.cookie_name, path="/", httponly=True, secure=s.cookie_secure, samesite="lax")
