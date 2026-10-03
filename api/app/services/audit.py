"""Audit log: who changed what. Admin actions, pricing changes and money-affecting
changes must call audit()."""

from typing import Any

from app.core.db import Db, DbSession
from app.core.timeutil import utcnow
from app.models.common import Actor, Related
from app.models.system import AuditEntry
from app.repos.audit_log import AuditLog


async def audit(
    db: Db,
    actor: Actor,
    action: str,
    target: Related,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    note: str = "",
    session: DbSession | None = None,
) -> AuditEntry:
    entry = AuditEntry(at=utcnow(), actor=actor, action=action, target=target, before=before, after=after, note=note)
    await AuditLog(db).insert(entry, session=session)
    return entry


SYSTEM = Actor(kind="system", name="system")
