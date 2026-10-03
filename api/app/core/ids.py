"""Identifiers.

Every document's _id is a string: the hex of a fresh ObjectId (time-sortable, 24
characters). References between collections store that same string, so nothing ever
converts between ObjectId and str. Categories use readable ids ("mowing").

Human-facing references (R-2291 for requests, B-1042 for bookings, D-014 for
disputes) come from an atomic counter in the counters collection.
"""

import hashlib
import hmac
import secrets

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.core.db import DbSession, check_session

REF_PREFIX = {"request": "R", "booking": "B", "dispute": "D"}
REF_START = {"request": 2300, "booking": 1100, "dispute": 15}
REF_WIDTH = {"request": 4, "booking": 4, "dispute": 3}


def new_id() -> str:
    return str(ObjectId())


def seed_id(key: str) -> str:
    """Deterministic 24-hex id for seeded documents, so re-seeding upserts in place."""
    return hashlib.sha256(key.encode()).hexdigest()[:24]


async def next_ref(db: AsyncDatabase, kind: str, *, session: DbSession | None = None) -> str:
    """The next reference. Inside a transaction the number is only used if it commits."""
    doc = await db["counters"].find_one_and_update(
        {"_id": kind},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
        session=check_session(session),
    )
    n = REF_START[kind] + int(doc["seq"])
    return f"{REF_PREFIX[kind]}-{n:0{REF_WIDTH[kind]}d}"


def new_token(nbytes: int = 32) -> str:
    """URL-safe random token for session cookies, magic links and invites."""
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str, pepper: str) -> str:
    """What we store instead of a token or code: HMAC-SHA256 keyed with SECRET_KEY."""
    return hmac.new(pepper.encode(), token.encode(), hashlib.sha256).hexdigest()


def new_login_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"
