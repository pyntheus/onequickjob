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


@pytest.mark.parametrize("commit", [True, False])
async def test_job_alerts_and_their_magic_links_commit_or_roll_back_together(db, catalogue, commit):
    """What L1's broadcast does: eligibility, a magic link and an alert per provider, as one write."""
    from app.repos import Categories, MagicLinks, Users
    from app.services.auth import create_magic_link
    from app.services.eligibility import alert_targets
    from app.services.notify import recipient_for
    from tests.factories import make_customer, make_provider, make_request

    customer = await make_customer(db)
    await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    req = await make_request(db, customer)
    cat = await Categories(db).get("mowing")
    s = make_settings()

    async def broadcast(session):
        for target in await alert_targets(db, req, cat, session=session):
            user = await Users(db).get(target.provider.user_id, session=session)
            await create_magic_link(db, s, user.id, "job_alert", f"/p/j/{req.ref}", session=session)
            await notify(
                db,
                "login_code",  # any template will do here; the point is the outbox write
                to=recipient_for(user),
                data={"code": "123456", "minutes": 10},
                settings=s,
                session=session,
            )
        if not commit:
            raise RuntimeError("broadcast failed")

    if commit:
        await transaction(db, broadcast)
    else:
        with pytest.raises(RuntimeError):
            await transaction(db, broadcast)
    expected = 1 if commit else 0
    assert await MagicLinks(db).count({}) == expected
    assert await Outbox(db).count({"template_id": "login_code"}) == expected
