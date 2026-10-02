"""outbox, audit_log, files. Owner: F. Every lane writes through app.services.notify,
app.services.audit and the FileStore adapter."""

from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import Field

from app.models.common import Actor, Channel, Doc, Model, Related


class Recipient(Model):
    user_id: str | None = None
    name: str = ""
    phone: str | None = Field(default=None, description="E.164, for sms and whatsapp")
    email: str | None = None


class OutboxMessage(Doc):
    """A message we would have sent. Nothing is ever sent: the outbox is the channel."""

    COLLECTION: ClassVar[str] = "outbox"

    channel: Channel
    recipient: Recipient
    template_id: str
    subject: str | None = Field(default=None, description="Email only")
    body: str = Field(description="Rendered text exactly as it would be sent")
    data: dict[str, Any] = Field(default_factory=dict, description="Template variables (no secrets)")
    related: Related = Field(default_factory=Related)
    status: Literal["logged"] = "logged"
    not_before: datetime | None = Field(default=None, description="Held for quiet hours: would send at")
    created_at: datetime


class AuditEntry(Doc):
    COLLECTION: ClassVar[str] = "audit_log"

    at: datetime
    actor: Actor
    action: str = Field(description='Dotted verb, e.g. "request.guide_raised", "pricing.approved"')
    target: Related
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    note: str = ""


FileKind = Literal["request_photo", "visit_before", "visit_after", "document", "receipt", "dispute_photo", "other"]


class StoredFile(Doc):
    COLLECTION: ClassVar[str] = "files"

    kind: FileKind
    owner_user_id: str
    path: str = Field(description="Relative to FILES_DIR; random, unguessable")
    url: str = Field(description="Served by Caddy behind basic auth (and by the API in dev)")
    content_type: str
    size: int
    original_name: str = ""
    related: Related = Field(default_factory=Related)
    created_at: datetime
