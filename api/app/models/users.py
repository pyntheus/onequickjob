"""users, sessions, login_codes, magic_links. Owner: F (auth). Lanes call app.services.auth."""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.common import E164, Channel, Doc, Role, Timestamped


class User(Timestamped):
    COLLECTION: ClassVar[str] = "users"

    name: str = ""
    phone: E164 | None = None
    email: str | None = Field(default=None, description="Lower-cased")
    roles: list[Role] = Field(default_factory=list)
    status: Literal["active", "suspended"] = "active"
    helper_of: str | None = Field(default=None, description="Provider id this user helps, if a helper")
    demo_key: str | None = Field(default=None, description="Seeded users only: key for Switch user")
    last_login_at: datetime | None = None


class Session(Doc):
    """Server-side session. _id is the HMAC of the cookie token, never the token."""

    COLLECTION: ClassVar[str] = "sessions"

    user_id: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    via: Literal["code", "magic", "demo"]
    user_agent: str = ""


class LoginCode(Doc):
    COLLECTION: ClassVar[str] = "login_codes"

    identifier: str = Field(description="E.164 phone or lower-cased email")
    channel: Channel
    code_hash: str
    attempts: int = 0
    max_attempts: int = 5
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    outbox_id: str | None = None


class MagicLink(Doc):
    """Single-use sign-in token carried in job-alert links (/p/j/R-2301?t=...)."""

    COLLECTION: ClassVar[str] = "magic_links"

    token_hash: str
    user_id: str
    purpose: Literal["job_alert", "invite", "helper_signup"]
    target_path: str = Field(description="Where the web goes after signing in")
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
