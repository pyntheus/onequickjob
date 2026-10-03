"""Categories viewer, the HMRC export (identity fields unsealed, takings and fees from the
ledger, exact pence), the audit log and the refund endpoint."""

import csv
import io
from datetime import UTC, datetime

from app.core.crypto import seal
from app.core.ids import new_id
from app.models.providers import TaxDetails
from app.models.records import LedgerEntry
from app.repos import LedgerEntries, Providers, TaxIdentities
from tests.admin.conftest import ok
from tests.conftest import make_settings
from tests.factories import make_provider


async def test_categories_with_provider_counts(jo, db, catalogue):
    await make_provider(db, "Dave Hughes", "+447700900201", ["mowing", "cleaning"], docs=["insurance"])
    rows = {r["category"]["id"]: r for r in ok(await jo.get("/api/admin/categories"))}
    assert len(rows) == 15
    assert rows["mowing"]["provider_count"] == 1
    assert rows["cleaning"]["provider_count"] == 0  # no basic DBS check
    assert rows["cleaning"]["extra_documents"] == ["Basic DBS check"]
    assert rows["dogwalking"]["extra_documents"] == ["Basic DBS check", "Insurance that covers pet care"]
    rec = ok(await jo.get("/api/admin/categories/mowing"))
    assert rec["pricing_version"] == 1 and rec["pricing_params"]["growth"]["overgrown"] == 1.9
    assert (await jo.get("/api/admin/categories/boilers")).status_code == 404


def entry(provider, kind: str, gross: int, fee: int, day: str) -> LedgerEntry:
    d = datetime.fromisoformat(day).replace(hour=12, tzinfo=UTC)
    return LedgerEntry(
        provider_id=provider.id,
        customer_id="c1",
        visit_id=new_id(),
        booking_id=None,
        kind=kind,  # type: ignore[arg-type]
        source="platform",
        gross_pence=gross,
        fee_pence=fee,
        net_pence=gross - fee,
        occurred_at=d,
        local_date=d.date(),
        tax_year="2026-27",
        gateway="fake",
    )


async def test_hmrc_export(jo, db, catalogue):
    s = make_settings()
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    await Providers(db).patch(
        dave.id, {"tax": TaxDetails(complete=True, ni_masked="QQ •• •• •• A").model_dump(mode="python")}
    )
    await TaxIdentities(db).upsert(dave.id, seal("QQ123456A", s), seal("1958-03-14", s))
    sneaky = await make_provider(db, "=HYPERLINK Smith", "+447700900299", ["mowing"])
    ledger = LedgerEntries(db)
    for e in [
        entry(dave, "charge", 3000, 450, "2026-02-10"),
        entry(dave, "charge", 1500, 100, "2026-07-01"),
        entry(dave, "tip", 500, 0, "2026-07-01"),
        entry(dave, "refund", -1500, -225, "2026-07-02"),
        entry(dave, "charge", 3000, 450, "2025-12-31"),  # last year
        entry(sneaky, "charge", 2000, 300, "2026-11-11"),
    ]:
        await ledger.insert(e)

    r = await jo.get("/api/admin/hmrc-export.csv?year=2026")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["cache-control"] == "no-store" and "onequickjob-hmrc-2026.csv" in r.headers["content-disposition"]
    lines = r.text.splitlines()
    assert lines[0].startswith("# Draft format: check it against HMRC's specification")
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[2:]))))
    assert [x["name"] for x in rows] == ["'=HYPERLINK Smith", "Dave Hughes"]  # a name can't become a formula
    dave_row = rows[1]
    assert (dave_row["ni_number"], dave_row["date_of_birth"]) == ("QQ123456A", "1958-03-14")
    assert (dave_row["charges"], dave_row["gross_takings"], dave_row["fees"]) == ("2", "50.00", "3.25")
    assert (dave_row["refunds"], dave_row["net_paid"]) == ("15.00", "31.75")
    assert (dave_row["q1_gross"], dave_row["q3_gross"]) == ("30.00", "20.00")
    assert rows[0]["ni_number"] == "" and rows[0]["tax_details_complete"] == "no"
    log = await db["audit_log"].find_one({"action": "hmrc.exported"})
    assert log and log["after"]["year"] == 2026 and log["after"]["providers"] == 2
    assert (await jo.get("/api/admin/hmrc-export.csv")).status_code == 422


async def test_audit_log_newest_first(jo, db, catalogue):
    p = await make_provider(db, "Jan Kowalski", "+447700900211", ["mowing"])
    ok(await jo.post(f"/api/admin/providers/{p.id}/suspend", json={"reason": "No-shows"}))
    ok(await jo.post(f"/api/admin/providers/{p.id}/reinstate"))
    log = ok(await jo.get("/api/admin/audit?limit=5"))
    assert [e["action"] for e in log] == ["provider.reinstated", "provider.suspended"]
    assert log[0]["actor"]["name"] == "Jo Morgan"
