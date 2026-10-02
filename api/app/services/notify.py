"""The Notifier: OUTBOX ONLY. Every message is rendered and written to the outbox
collection. Nothing is ever sent to a phone, WhatsApp or an inbox.
"""

from datetime import datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.core.config import Settings, get_settings
from app.core.db import Db
from app.core.timeutil import utcnow
from app.models.common import Channel, Related
from app.models.system import OutboxMessage, Recipient
from app.models.users import User
from app.repos.outbox import Outbox
from app.services import templates


def recipient_for(user: User) -> Recipient:
    return Recipient(user_id=user.id, name=user.name, phone=user.phone, email=user.email)


def link(path: str, settings: Settings | None = None) -> str:
    """Absolute link for a message body. Paths start with /."""
    s = settings or get_settings()
    return s.public_base_url.rstrip("/") + path


async def notify(
    db: Db,
    template_id: str,
    *,
    to: Recipient,
    data: dict[str, Any],
    related: Related | None = None,
    channel: Channel | None = None,
    not_before: datetime | None = None,
    settings: Settings | None = None,
    idempotency_key: str | None = None,
) -> OutboxMessage:
    """Render a catalogue template and log it to the outbox. Returns the stored message.

    With an idempotency_key the message is written at most once, however many times (or
    however concurrently) this is called: later calls return the message already written."""
    s = settings or get_settings()
    t = templates.get(template_id)
    ch = channel or t.channels[0]
    if ch not in t.channels:
        raise templates.TemplateError(f"{template_id} isn't sent by {ch}")
    if ch in ("sms", "whatsapp") and not to.phone:
        raise templates.TemplateError(f"{template_id}: recipient has no phone for {ch}")
    if ch == "email" and not to.email:
        raise templates.TemplateError(f"{template_id}: recipient has no email")
    values = {"brand": s.brand, **data}
    subject, body = templates.render(t, values)
    msg = OutboxMessage(
        channel=ch,
        recipient=to,
        template_id=t.id,
        subject=subject,
        body=body,
        data={k: v for k, v in data.items() if k not in SECRET_KEYS},
        related=related or Related(),
        not_before=not_before,
        idempotency_key=idempotency_key,
        created_at=utcnow(),
    )
    outbox = Outbox(db)
    try:
        await outbox.insert(msg)
    except DuplicateKeyError:
        if idempotency_key is None:
            raise
        existing = await outbox.find_one({"idempotency_key": idempotency_key})
        assert existing is not None
        return existing
    return msg


# Values that appear in a body but are not copied into `data` (the body already holds them).
SECRET_KEYS = frozenset({"code", "token"})
