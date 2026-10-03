"""users, sessions, login_codes, magic_links. Owner: F (auth)."""

from pymongo import DESCENDING

from app.core.db import DbSession
from app.core.timeutil import utcnow
from app.models.common import Role
from app.models.users import LoginCode, MagicLink, Session, User
from app.repos.base import Repo, idx

_STR = {"$type": "string"}


class Users(Repo[User]):
    model = User
    indexes = [
        idx("phone", unique=True, partialFilterExpression={"phone": _STR}),
        idx("email", unique=True, partialFilterExpression={"email": _STR}),
        idx("demo_key", unique=True, partialFilterExpression={"demo_key": _STR}),
        idx("roles"),
    ]

    async def by_phone(self, phone: str, *, session: DbSession | None = None) -> User | None:
        return await self.find_one({"phone": phone}, session=session)

    async def by_email(self, email: str, *, session: DbSession | None = None) -> User | None:
        return await self.find_one({"email": email.lower()}, session=session)

    async def by_identifier(self, identifier: str, *, session: DbSession | None = None) -> User | None:
        if identifier.startswith("+"):
            return await self.by_phone(identifier, session=session)
        return await self.by_email(identifier, session=session)

    async def add_role(self, user_id: str, role: Role, *, session: DbSession | None = None) -> User | None:
        raw = await self.coll.find_one_and_update(
            {"_id": user_id},
            {"$addToSet": {"roles": role}, "$set": {"updated_at": utcnow()}},
            return_document=True,
            session=self.s(session),
        )
        return self._load(raw)

    async def demo_users(self, *, session: DbSession | None = None) -> list[User]:
        return await self.find({"demo_key": _STR}, sort=[("demo_key", 1)], session=session)


class Sessions(Repo[Session]):
    model = Session
    touch_updated_at = False
    indexes = [idx("user_id"), idx("expires_at", expireAfterSeconds=0)]


class LoginCodes(Repo[LoginCode]):
    model = LoginCode
    touch_updated_at = False
    indexes = [idx("identifier", ("created_at", DESCENDING)), idx("expires_at", expireAfterSeconds=3600)]

    async def latest(self, identifier: str, *, session: DbSession | None = None) -> LoginCode | None:
        return await self.find_one({"identifier": identifier}, sort=[("created_at", DESCENDING)], session=session)


class MagicLinks(Repo[MagicLink]):
    model = MagicLink
    touch_updated_at = False
    indexes = [idx("token_hash", unique=True), idx("expires_at", expireAfterSeconds=86400)]
