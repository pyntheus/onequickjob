"""app.core.db.transaction: the one way to write to several collections (CLAUDE.md)."""

import pytest

from app.core.db import transaction
from app.models.common import Related
from app.models.system import AuditEntry, Recipient
from app.repos import AuditLog, Outbox
from app.services.audit import SYSTEM
from app.services.notify import notify
from tests.conftest import make_settings


def _entry(note: str) -> AuditEntry:
    from app.core.timeutil import utcnow

    return AuditEntry(at=utcnow(), actor=SYSTEM, action="test.write", target=Related(), note=note)


async def test_everything_commits_together(db):
    async def write(session):
        await AuditLog(db).insert(_entry("one"), session=session)
        await notify(
            db,
            "login_code",
            to=Recipient(name="Sarah", phone="+447700900123"),
            data={"code": "123456", "minutes": 10},
            settings=make_settings(),
            session=session,
        )
        return "done"

    assert await transaction(db, write) == "done"
    assert await AuditLog(db).count({}) == 1 and await Outbox(db).count({}) == 1


async def test_an_exception_undoes_every_write(db):
    async def write(session):
        await AuditLog(db).insert(_entry("one"), session=session)
        await Outbox(db).count({}, session=session)
        raise ValueError("changed my mind")

    with pytest.raises(ValueError, match="changed my mind"):
        await transaction(db, write)
    assert await AuditLog(db).count({}) == 0


async def test_a_call_without_the_session_inside_a_transaction_fails_loudly(db):
    """It would run outside the transaction (and wait on its locks), so it's refused."""

    async def forgetful(session):
        await AuditLog(db).insert(_entry("in"), session=session)
        await AuditLog(db).insert(_entry("outside"))

    with pytest.raises(RuntimeError, match="pass session="):
        await transaction(db, forgetful)
    assert await AuditLog(db).count({}) == 0


async def test_transactions_do_not_nest(db):
    async def outer(session):
        await transaction(db, lambda s: AuditLog(db).count({}, session=s))

    with pytest.raises(RuntimeError, match="don't nest"):
        await transaction(db, outer)


async def test_outside_a_transaction_the_session_is_optional(db):
    await AuditLog(db).insert(_entry("plain"))
    assert await AuditLog(db).count({}) == 1
