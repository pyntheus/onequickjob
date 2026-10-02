"""Writing ledger entries: the provider's money records. gross == fee + net always.

L2 calls record_charge (and record_tip) when a visit is charged; L3 calls record_refund.
The tax pack (L2) and the HMRC export (L3) are derived from these entries only.
"""

from datetime import datetime

from pymongo.errors import DuplicateKeyError

from app.core import money
from app.core.db import Db
from app.core.timeutil import tax_year, to_london
from app.models.records import LedgerEntry
from app.models.visits import Visit
from app.repos.ledger_entries import LedgerEntries


def _entry(
    visit: Visit, kind: str, split: money.Split, sign: int, at: datetime, gateway: str, ref: str | None
) -> LedgerEntry:
    day = to_london(at).date()
    return LedgerEntry(
        provider_id=visit.provider_id,
        customer_id=visit.customer_id,
        visit_id=visit.id,
        booking_id=visit.booking_id,
        kind=kind,  # type: ignore[arg-type]
        source=visit.source,
        gross_pence=sign * split.price_pence,
        fee_pence=sign * split.fee_pence,
        net_pence=sign * split.provider_pence,
        occurred_at=at,
        local_date=day,
        tax_year=tax_year(day),
        gateway=gateway,  # type: ignore[arg-type]
        gateway_ref=ref,
    )


async def record_charge(
    db: Db, visit: Visit, split: money.Split, *, at: datetime, gateway: str, charge_id: str | None
) -> LedgerEntry:
    """One charge entry per visit. Re-recording returns the existing entry."""
    repo = LedgerEntries(db)
    entry = _entry(visit, "charge", split, 1, at, gateway, charge_id)
    try:
        await repo.insert(entry)
        return entry
    except DuplicateKeyError:
        existing = await repo.find_one({"visit_id": visit.id, "kind": "charge"})
        assert existing is not None
        return existing


async def record_tip(
    db: Db, visit: Visit, tip_pence: int, *, at: datetime, gateway: str, charge_id: str | None
) -> LedgerEntry:
    entry = _entry(visit, "tip", money.split(tip_pence, "tip"), 1, at, gateway, charge_id)
    await LedgerEntries(db).insert(entry)
    return entry


async def record_refund(
    db: Db, visit: Visit, refund: money.Split, *, at: datetime, gateway: str, refund_id: str | None
) -> LedgerEntry:
    """A refund entry with negative amounts (from money.refund_split)."""
    entry = _entry(visit, "refund", refund, -1, at, gateway, refund_id)
    await LedgerEntries(db).insert(entry)
    return entry
