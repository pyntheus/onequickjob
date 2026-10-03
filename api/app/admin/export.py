"""The HMRC export: per calendar year, each provider's identity fields and their gross takings
and fees, derived from the ledger only (so it uses exactly what was charged: the stored
first-visit and per-visit prices and the fee from money.py, cover visits included).

DRAFT FORMAT. It must be checked against HMRC's specification for digital platform reporting
before any real use. The full NI number and date of birth are unsealed here and nowhere else
(decisions.md R28); every export is audit-logged.
"""

import csv
import io
from datetime import date

from app.admin.views import short_name
from app.core.config import Settings
from app.core.crypto import unseal
from app.core.db import Db
from app.core.phone import to_national
from app.models.common import Actor, Related
from app.repos import LedgerEntries, Providers, TaxIdentities, Users
from app.services.audit import audit

NOTE = (
    "Draft format: check it against HMRC's specification for digital platform reporting before any real use. "
    "Contains personal data: keep it safe and delete it when done."
)
COLUMNS = [
    "provider_id",
    "name",
    "ni_number",
    "date_of_birth",
    "home_postcode",
    "phone",
    "email",
    "payment_account",
    "tax_details_complete",
    "charges",
    "gross_takings",
    "fees",
    "refunds",
    "net_paid",
    "q1_gross",
    "q2_gross",
    "q3_gross",
    "q4_gross",
]


def pounds(pence: int) -> str:
    """Integer pence as pounds with two decimals, without floats: -1275 -> -12.75."""
    sign = "-" if pence < 0 else ""
    whole, part = divmod(abs(pence), 100)
    return f"{sign}{whole}.{part:02d}"


def cell(value: object) -> str:
    """Text that a spreadsheet won't run as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not _is_number(text) else text


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _open(sealed: str | None, s: Settings) -> str:
    if not sealed:
        return ""
    try:
        return unseal(sealed, s)
    except ValueError:
        return "UNREADABLE"


async def hmrc_csv(db: Db, s: Settings, year: int, actor: Actor) -> tuple[str, int]:
    first, last = date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()
    entries = await LedgerEntries(db).find(
        {"local_date": {"$gte": first, "$lte": last}}, sort=[("provider_id", 1), ("occurred_at", 1)]
    )
    by_provider: dict[str, list] = {}
    for e in entries:
        by_provider.setdefault(e.provider_id, []).append(e)
    providers = sorted(await Providers(db).find({"_id": {"$in": list(by_provider)}}), key=lambda p: p.name)
    identities = {t.provider_id: t for t in await TaxIdentities(db).find({"provider_id": {"$in": list(by_provider)}})}
    users = {u.id: u for u in await Users(db).find({"_id": {"$in": [p.user_id for p in providers]}})}

    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow([f"# {NOTE}"])
    w.writerow([f"# OneQuickJob platform report for the calendar year {year}. Amounts in pounds (GBP)."])
    w.writerow(COLUMNS)
    for p in providers:
        rows = by_provider[p.id]
        ident = identities.get(p.id)
        user = users.get(p.user_id)
        quarters = [0, 0, 0, 0]
        for e in rows:
            if e.kind != "refund":
                quarters[(e.local_date.month - 1) // 3] += e.gross_pence
        w.writerow(
            [
                cell(p.id),
                cell(p.name),
                cell(_open(ident.ni_number_sealed if ident else None, s)),
                cell(_open(ident.dob_sealed if ident else None, s)),
                cell(p.home.postcode),
                cell(to_national(user.phone) if user and user.phone else ""),
                cell(user.email if user else ""),
                cell(p.payment_account.account_id if p.payment_account else ""),
                "yes" if p.tax.complete else "no",
                sum(1 for e in rows if e.kind == "charge"),
                pounds(sum(e.gross_pence for e in rows if e.kind != "refund")),
                pounds(sum(e.fee_pence for e in rows)),
                pounds(-sum(e.gross_pence for e in rows if e.kind == "refund")),
                pounds(sum(e.net_pence for e in rows)),
                *(pounds(q) for q in quarters),
            ]
        )
    await audit(
        db,
        actor,
        "hmrc.exported",
        Related(),
        after={"year": year, "providers": len(providers), "names": [short_name(p.name) for p in providers]},
        note="Unsealed NI numbers and dates of birth for the export.",
    )
    return out.getvalue(), len(providers)
