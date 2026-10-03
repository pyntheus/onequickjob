"""Sign-in by phone or email plus a 6-digit code from the outbox; server-side sessions.

- Codes expire after LOGIN_CODE_TTL_MINUTES (10) and allow LOGIN_CODE_MAX_ATTEMPTS (5)
  wrong tries. Only the latest code for an identifier is valid.
- Codes and tokens are stored as HMAC-SHA256 (keyed with SECRET_KEY), never in clear;
  the plain code exists only in the outbox message, which is the "text" we sent.
- New codes for one identifier: at most one every 30 seconds and six an hour.
- Sessions live in Mongo; the browser holds a random token in an httpOnly, Secure,
  SameSite=Lax cookie. The session _id is the token's HMAC.
- Magic links (job alerts) are single-use tokens that create a session.
"""

import hmac
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from fastapi import status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core import phone as phones
from app.core.config import Settings
from app.core.db import Db, DbSession
from app.core.errors import fail
from app.core.ids import new_login_code, new_token, token_hash
from app.core.timeutil import utcnow
from app.models.common import Channel, Related, Role
from app.models.system import Recipient
from app.models.users import LoginCode, MagicLink, Session, User
from app.repos.users import LoginCodes, MagicLinks, Sessions, Users
from app.services.notify import notify

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CODES_PER_HOUR = 6


@dataclass(frozen=True)
class Identifier:
    value: str  # E.164 phone or lower-cased email
    channel: Channel

    @property
    def masked(self) -> str:
        if self.channel == "sms":
            return phones.mask(self.value)
        local, _, domain = self.value.partition("@")
        return f"{local[:1]}•••@{domain}"


def parse_identifier(raw: str) -> Identifier:
    raw = raw.strip()
    if "@" in raw:
        if not _EMAIL.match(raw) or len(raw) > 254:
            fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_email", "That doesn't look like an email address.")
        return Identifier(raw.lower(), "email")
    try:
        return Identifier(phones.to_e164(raw), "sms")
    except phones.InvalidPhone as e:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_phone", str(e))


def _code_hash(identifier: str, code: str, s: Settings) -> str:
    return token_hash(f"login:{identifier}:{code}", s.pepper)


async def issue_code(db: Db, s: Settings, raw_identifier: str) -> tuple[Identifier, LoginCode]:
    ident = parse_identifier(raw_identifier)
    codes = LoginCodes(db)
    now = utcnow()
    latest = await codes.latest(ident.value)
    if latest and (now - latest.created_at).total_seconds() < s.login_code_min_interval_seconds:
        fail(status.HTTP_429_TOO_MANY_REQUESTS, "too_soon", "We've just sent a code. Please wait a moment.")
    recent = await codes.count({"identifier": ident.value, "created_at": {"$gt": now - timedelta(hours=1)}})
    if recent >= CODES_PER_HOUR:
        fail(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_codes", "Too many codes asked for. Try again in an hour.")

    code = new_login_code()
    user = await Users(db).by_identifier(ident.value)
    row = LoginCode(
        identifier=ident.value,
        channel=ident.channel,
        code_hash=_code_hash(ident.value, code, s),
        max_attempts=s.login_code_max_attempts,
        created_at=now,
        expires_at=now + timedelta(minutes=s.login_code_ttl_minutes),
    )
    to = Recipient(
        user_id=user.id if user else None,
        name=user.name if user else "",
        phone=ident.value if ident.channel == "sms" else None,
        email=ident.value if ident.channel == "email" else None,
    )
    msg = await notify(
        db,
        "login_code",
        to=to,
        channel=ident.channel,
        data={"code": code, "minutes": s.login_code_ttl_minutes},
        related=Related(user_id=user.id if user else None),
        settings=s,
    )
    row.outbox_id = msg.id
    await codes.insert(row)
    return ident, row


async def verify_code(db: Db, s: Settings, raw_identifier: str, code: str, name: str | None = None) -> User:
    """Check a code; on success return the user, creating a customer account if new."""
    ident = parse_identifier(raw_identifier)
    codes = LoginCodes(db)
    now = utcnow()
    row = await codes.latest(ident.value)
    if row is None or row.consumed_at is not None or row.expires_at <= now:
        fail(status.HTTP_400_BAD_REQUEST, "code_expired", "That code has expired. We can send you a new one.")
    live = {"_id": row.id, "consumed_at": None, "expires_at": {"$gt": now}}

    # Every guess, right or wrong, first takes one of the code's attempts atomically, so
    # concurrent guesses can't share an attempt: at most max_attempts are ever compared.
    reserved = await codes.coll.find_one_and_update(
        {**live, "attempts": {"$lt": row.max_attempts}}, {"$inc": {"attempts": 1}}, return_document=ReturnDocument.AFTER
    )
    if reserved is None:
        if await codes.count(live) == 0:
            fail(status.HTTP_400_BAD_REQUEST, "code_expired", "That code has expired. We can send you a new one.")
        fail(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts", "Too many wrong tries. Ask for a new code.")

    if not hmac.compare_digest(row.code_hash, _code_hash(ident.value, code.strip(), s)):
        left = row.max_attempts - reserved["attempts"]
        if left <= 0:
            fail(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts", "Too many wrong tries. Ask for a new code.")
        fail(status.HTTP_400_BAD_REQUEST, "wrong_code", "That code isn't right.", attempts_left=left)

    # Only the latest code counts: one sent meanwhile replaces this one.
    if await codes.count({"identifier": ident.value, "created_at": {"$gt": row.created_at}}):
        fail(status.HTTP_400_BAD_REQUEST, "code_expired", "That code has expired. We can send you a new one.")
    # Consume exactly once, even if two requests race with the right code, and never after expiry.
    used = await codes.coll.update_one(live, {"$set": {"consumed_at": now}})
    if used.modified_count != 1:
        fail(status.HTTP_400_BAD_REQUEST, "code_expired", "That code has already been used. Ask for a new one.")
    return await find_or_create_user(db, ident, name)


async def find_or_create_user(db: Db, ident: Identifier, name: str | None) -> User:
    users = Users(db)
    user = await users.by_identifier(ident.value)
    now = utcnow()
    if user is None:
        user = User(
            name=(name or "").strip()[:80],
            phone=ident.value if ident.channel == "sms" else None,
            email=ident.value if ident.channel == "email" else None,
            roles=["customer"],
        )
        try:
            await users.insert(user)
        except DuplicateKeyError:  # created concurrently
            user = await users.by_identifier(ident.value)
            assert user is not None
    elif name and not user.name:
        user = await users.update(user.id, {"name": name.strip()[:80]}) or user
    if user.status != "active":
        fail(status.HTTP_403_FORBIDDEN, "account_suspended", "This account is paused. Please contact us.")
    await users.update(user.id, {"last_login_at": now})
    return user


async def create_session(
    db: Db, s: Settings, user: User, via: Literal["code", "magic", "demo"], user_agent: str = ""
) -> str:
    token = new_token()
    now = utcnow()
    await Sessions(db).insert(
        Session(
            id=token_hash(token, s.pepper),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=s.session_days),
            last_seen_at=now,
            via=via,
            user_agent=user_agent[:200],
        )
    )
    return token


async def session_user(db: Db, s: Settings, token: str | None) -> tuple[Session, User] | None:
    if not token:
        return None
    sessions = Sessions(db)
    session = await sessions.get(token_hash(token, s.pepper))
    now = utcnow()
    if session is None or session.expires_at <= now:
        return None
    if session.via == "demo" and not s.demo_mode:
        # Switch-user sessions exist only while DEMO_MODE is on; turning it off ends them.
        await sessions.delete(session.id)
        return None
    user = await Users(db).get(session.user_id)
    if user is None or user.status != "active":
        return None
    if (now - session.last_seen_at) > timedelta(hours=1):
        await sessions.update(session.id, {"last_seen_at": now})
    return session, user


async def end_session(db: Db, s: Settings, token: str | None) -> None:
    if token:
        await Sessions(db).delete(token_hash(token, s.pepper))


async def create_magic_link(
    db: Db,
    s: Settings,
    user_id: str,
    purpose: Literal["job_alert", "invite", "helper_signup"],
    target_path: str,
    *,
    session: DbSession | None = None,
) -> str:
    """Mint a single-use sign-in token. Put it in a link as ?t=<token>. With session, the link
    exists only if the caller's transaction (say, a request and its job alerts) commits."""
    token = new_token(24)
    now = utcnow()
    await MagicLinks(db).insert(
        MagicLink(
            token_hash=token_hash(token, s.pepper),
            user_id=user_id,
            purpose=purpose,
            target_path=target_path,
            created_at=now,
            expires_at=now + timedelta(hours=s.magic_link_ttl_hours),
        ),
        session=session,
    )
    return token


async def consume_magic_link(db: Db, s: Settings, token: str) -> tuple[User, str]:
    now = utcnow()
    raw = await MagicLinks(db).coll.find_one_and_update(
        {"token_hash": token_hash(token, s.pepper), "used_at": None, "expires_at": {"$gt": now}},
        {"$set": {"used_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if raw is None:
        fail(status.HTTP_400_BAD_REQUEST, "link_expired", "That link has expired or been used. Sign in with a code.")
    link = MagicLink.model_validate(raw)
    user = await Users(db).get(link.user_id)
    if user is None or user.status != "active":
        fail(status.HTTP_403_FORBIDDEN, "account_suspended", "This account is paused. Please contact us.")
    return user, link.target_path


def has_role(user: User, role: Role) -> bool:
    return role in user.roles
