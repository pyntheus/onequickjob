"""Rulings after F review (c): a basic DBS check is valid for 12 months from its issue date,
expiry is tracked, a reminder goes 30 days before (as for insurance), and expired means not
eligible for categories that need it."""

from datetime import date, timedelta

import pytest

from app.core.timeutil import london_today
from app.models.categories import DocumentType
from app.repos import Providers
from app.services import documents, eligibility
from tests.factories import make_provider

DBS = DocumentType(id="dbs_basic", label="Basic DBS check", expires=True, valid_months=12)
INSURANCE = DocumentType(id="insurance", label="Public liability insurance", expires=True)
IDENTITY = DocumentType(id="identity", label="Identity", expires=False)


def test_dbs_runs_twelve_months_from_issue():
    assert documents.expiry_for(DBS, date(2026, 3, 14), None) == date(2027, 3, 14)
    assert documents.expiry_for(DBS, date(2028, 2, 29), None) == date(2029, 2, 28)
    assert documents.expiry_for(DBS, date(2026, 3, 14), date(2030, 1, 1)) == date(2027, 3, 14), "issue date wins"
    with pytest.raises(documents.DocumentDateError):
        documents.expiry_for(DBS, None, date(2027, 1, 1))
    assert documents.expiry_for(INSURANCE, None, date(2027, 3, 14)) == date(2027, 3, 14)
    with pytest.raises(documents.DocumentDateError):
        documents.expiry_for(INSURANCE, None, None)
    assert documents.expiry_for(IDENTITY, None, None) is None


async def test_the_catalogue_says_dbs_is_valid_twelve_months(db, catalogue):
    dbs = await db["document_types"].find_one({"_id": "dbs_basic"})
    assert dbs["expires"] is True and dbs["valid_months"] == 12


async def test_expired_dbs_means_not_eligible(db, catalogue):
    p = await make_provider(db, "Lorna Baines", "+447700900203", ["cleaning"], docs=["insurance", "dbs_basic"])
    today = london_today()
    issued = today - timedelta(days=200)
    await db["providers"].update_one(
        {"_id": p.id, "documents.type": "dbs_basic"},
        {
            "$set": {
                "documents.$.issued_on": issued.isoformat(),
                "documents.$.expires_on": documents.expiry_for(DBS, issued, None).isoformat(),
            }
        },
    )
    p = await Providers(db).get(p.id)
    assert eligibility.can_take(p, catalogue["cleaning"], today).ok
    a_year_on = documents.expiry_for(DBS, issued, None) + timedelta(days=1)
    e = eligibility.can_take(p, catalogue["cleaning"], a_year_on)
    assert not e.ok and "dbs_basic" in e.missing_documents
    assert eligibility.can_take(p, catalogue["cleaning"], a_year_on - timedelta(days=1)).ok, "valid on its last day"


async def test_reminder_thirty_days_before_once_per_expiry(db, catalogue):
    p = await make_provider(db, "Lorna Baines", "+447700900203", ["cleaning", "oven"], docs=["insurance", "dbs_basic"])
    today = london_today()
    soon, later = today + timedelta(days=25), today + timedelta(days=40)
    await db["providers"].update_one(
        {"_id": p.id},
        {"$set": {"documents.$[d].expires_on": soon.isoformat()}},
        array_filters=[{"d.type": "dbs_basic"}],
    )
    await db["providers"].update_one(
        {"_id": p.id},
        {"$set": {"documents.$[d].expires_on": later.isoformat()}},
        array_filters=[{"d.type": "insurance"}],
    )
    assert await documents.send_expiry_reminders(db, today) == 1
    await documents.send_expiry_reminders(db, today)
    await documents.send_expiry_reminders(db, today + timedelta(days=1))
    msgs = await db["outbox"].find({"template_id": "document_expiring"}).to_list()
    assert len(msgs) == 1, "once per document per expiry date"
    assert "your basic dbs check runs out on" in msgs[0]["body"]
    assert "regular cleaning and oven cleaning jobs" in msgs[0]["body"]
    # The insurance reminder comes when it's 30 days out, exactly the same way.
    assert await documents.send_expiry_reminders(db, later - timedelta(days=30)) == 2  # (DBS key repeats: no new msg)
    assert await db["outbox"].count_documents({"template_id": "document_expiring"}) == 2
