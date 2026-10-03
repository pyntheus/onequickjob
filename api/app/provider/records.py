"""Earnings, tax and records, derived only from ledger_entries, mileage_logs and expenses.

- Turnover is what customers paid (gross); our fee is a business cost; what reached the
  bank is net. gross == fee + net in every ledger entry (services.ledger).
- Mileage is a calculated estimate, worked out when a visit is finished: home, each job in
  the order they were started, home; straight-line distance x 1.25 for roads; legs to 2
  decimal places and the day to 1, halves up; HMRC's approved rate of 45p a mile (25p after
  10,000 business miles in a tax year, applied to the year's total).
- The trading allowance (£1,000) or actual costs (fees, mileage, expenses): whichever leaves
  less taxable profit. We're not tax advisers, and the copy says so.
"""

import csv
import html
import io
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal
from itertools import pairwise

from fastapi import status
from pymongo import ReturnDocument

from app.adapters.payments.base import PaymentGateway
from app.core.db import Db, DbSession
from app.core.errors import fail, not_found
from app.core.geo import ROAD_FACTOR, miles_between
from app.core.ids import new_id
from app.core.rounding import D, round_half_up, round_half_up_to
from app.core.timeutil import london_datetime, london_today, tax_year, tax_year_bounds, utcnow, week_start
from app.models.providers import Provider
from app.models.records import Expense, MileageLeg, MileageLog
from app.provider.common import categories, own_file, short_name
from app.provider.limit import get_limit
from app.provider.schemas import (
    EarningsOut,
    ExpenseIn,
    ExpenseOut,
    KeyDate,
    MileageDay,
    TaxSummary,
    WeekBar,
)
from app.repos.bookings import Bookings
from app.repos.customers import Customers
from app.repos.expenses import Expenses
from app.repos.files import Files
from app.repos.ledger_entries import LedgerEntries
from app.repos.mileage_logs import MileageLogs
from app.repos.providers import Providers
from app.repos.visits import Visits
from app.services import wording

MILEAGE_RATE_PENCE = 45  # HMRC approved mileage allowance, cars and vans, first 10,000 business miles
MILEAGE_RATE_AFTER_PENCE = 25
MILEAGE_THRESHOLD = 10_000
TRADING_ALLOWANCE_PENCE = 100_000  # £1,000
WEEKS_SHOWN = 8
MTD_THRESHOLD_PENCE = 2_000_000  # £20,000


# ------------------------------------------------------------------ mileage


@dataclass(frozen=True)
class Point:
    label: str
    lat: float
    lng: float


@dataclass(frozen=True)
class DayMileage:
    legs: list[MileageLeg]
    miles: Decimal
    amount_pence: int


def day_mileage(home: Point, stops: list[Point], rate_pence: int = MILEAGE_RATE_PENCE) -> DayMileage:
    """Home -> each stop in order -> home. Each leg is straight-line miles x 1.25 (the road
    factor), to 2 decimal places; the day's total is the legs' sum to 1 decimal place; the
    amount is that x the rate, to the penny. All halves round up (Decimal, never round())."""
    legs: list[MileageLeg] = []
    total = Decimal(0)
    for a, b in pairwise([home, *stops, home]):
        straight = D(miles_between(a.lat, a.lng, b.lat, b.lng))
        road = round_half_up_to(straight * D(ROAD_FACTOR), "0.01")
        legs.append(
            MileageLeg(
                from_label=a.label,
                to_label=b.label,
                straight_miles=float(round_half_up_to(straight, "0.01")),
                road_miles=float(road),
            )
        )
        total += road
    miles = round_half_up_to(total, "0.1")
    return DayMileage(legs=legs, miles=miles, amount_pence=round_half_up(miles * rate_pence))


def _allowance(miles: Decimal) -> Decimal:
    first = min(miles, Decimal(MILEAGE_THRESHOLD))
    rest = max(Decimal(0), miles - MILEAGE_THRESHOLD)
    return first * MILEAGE_RATE_PENCE + rest * MILEAGE_RATE_AFTER_PENCE


def year_mileage_pence(miles: Decimal) -> int:
    """HMRC's rate for a tax year's business miles: 45p for the first 10,000, 25p after."""
    return round_half_up(_allowance(miles))


def allowance_by_day(logs: list[MileageLog]) -> dict[date, int]:
    """Each day's share of the tax year's mileage allowance, in date order: the allowance on the
    year's running total after that day (rounded half-up) less what the days before it already
    had. So the days add up exactly to year_mileage_pence of the year's miles, and the rate drops
    to 25p from the 10,001st mile."""
    out: dict[date, int] = {}
    running, given = Decimal(0), 0
    for log in sorted(logs, key=lambda x: x.local_date):
        running += D(log.miles)
        total = year_mileage_pence(running)
        out[log.local_date] = total - given
        given = total
    return out


async def record_mileage_day(db: Db, provider_id: str, day: date, *, session: DbSession) -> MileageLog | None:
    """Work out (again) the provider's mileage for a London day from the visits they finished
    that day themselves (a helper's travel isn't theirs). Idempotent: one log per day."""
    provider = await Providers(db).get(provider_id, session=session)
    if provider is None:
        return None
    start = london_datetime(day, time(0, 0))
    end = london_datetime(day + timedelta(days=1), time(0, 0))
    visits = await Visits(db).find(
        {
            "provider_id": provider_id,
            "status": "finished",
            "performer.kind": {"$ne": "helper"},
            "finished_at": {"$gte": start, "$lt": end},
        },
        sort=[("started_at", 1), ("finished_at", 1)],
        session=session,
    )
    if not visits:
        return None
    ids = list({v.booking_id for v in visits})
    addresses = {b.id: b.address for b in await Bookings(db).find({"_id": {"$in": ids}}, session=session)}
    stops = [
        Point(addresses[v.booking_id].area, addresses[v.booking_id].lat, addresses[v.booking_id].lng)
        for v in visits
        if v.booking_id in addresses
    ]
    loc = provider.home.location
    m = day_mileage(Point("Home", loc.lat, loc.lng), stops)
    now = utcnow()
    raw = await MileageLogs(db).coll.find_one_and_update(
        {"provider_id": provider_id, "local_date": day.isoformat()},
        {
            "$set": {
                "tax_year": tax_year(day),
                "legs": [leg.model_dump() for leg in m.legs],
                "miles": float(m.miles),
                "rate_pence_per_mile": MILEAGE_RATE_PENCE,
                "amount_pence": m.amount_pence,
                "method": "calculated_estimate",
                "visit_ids": [v.id for v in visits],
                "updated_at": now,
            },
            "$setOnInsert": {"_id": new_id(), "created_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
        session=MileageLogs.s(session),
    )
    return MileageLog.model_validate(raw)


def route_text(log: MileageLog) -> str:
    """Home, Widmer End, Hazlemere, home."""
    if not log.legs:
        return ""
    names = [log.legs[0].from_label] + [leg.to_label for leg in log.legs]
    names[-1] = names[-1].lower() if names[-1] == "Home" else names[-1]
    return ", ".join(names)


def mileage_day(log: MileageLog, amount_pence: int) -> MileageDay:
    """One day's trip, with its share of the year's allowance (allowance_by_day)."""
    return MileageDay(local_date=log.local_date, route_text=route_text(log), miles=log.miles, amount_pence=amount_pence)


async def mileage(db: Db, provider: Provider, label: str | None = None) -> list[MileageDay]:
    label = label or tax_year(london_today())
    logs = await MileageLogs(db).find({"provider_id": provider.id, "tax_year": label}, sort=[("local_date", -1)])
    amounts = allowance_by_day(logs)
    return [mileage_day(log, amounts[log.local_date]) for log in logs]


# ------------------------------------------------------------------ earnings


def week_label(d: date, previous: date | None) -> str:
    """3 Aug, 10, 17, 24, 31, 7 Sep: the month only where it changes."""
    return f"{d.day} {d:%b}" if previous is None or previous.month != d.month else str(d.day)


async def earnings(db: Db, gateway: PaymentGateway, provider: Provider) -> EarningsOut:
    today = london_today()
    this_week = week_start(today)
    weeks = [this_week - timedelta(weeks=WEEKS_SHOWN - 1 - i) for i in range(WEEKS_SHOWN)]
    entries = await LedgerEntries(db).find(
        {"provider_id": provider.id, "local_date": {"$gte": weeks[0].isoformat(), "$lte": today.isoformat()}}
    )
    net = {w: 0 for w in weeks}
    jobs = 0
    for e in entries:
        net[week_start(e.local_date)] = net.get(week_start(e.local_date), 0) + e.net_pence
        if e.kind == "charge" and e.local_date >= this_week:
            jobs += 1
    bars = [
        WeekBar(week_start=w, label=week_label(w, weeks[i - 1] if i else None), net_pence=net[w])
        for i, w in enumerate(weeks)
    ]
    payouts, next_date, pending, last4 = [], None, 0, None
    if provider.payment_account is not None:
        last4 = provider.payment_account.bank_last4
        try:
            summary = await gateway.payout_summary(provider.payment_account.account_id, limit=8)
            payouts, next_date, pending = summary.payouts, summary.next_payout_date, summary.pending_pence
            last4 = next((p.bank_last4 for p in payouts if p.bank_last4), last4)
        except Exception:
            payouts = []
    own = await Bookings(db).count({"provider_id": provider.id, "source": "own_customer", "status": "active"})
    return EarningsOut(
        week_net_pence=net[this_week],
        week_jobs=jobs,
        weekly=bars,
        payouts=payouts,
        next_payout_date=next_date,
        limit=await get_limit(db, provider, today),
        own_customers_active=own,
        bank_last4=last4,
        pending_pence=pending,
    )


# ------------------------------------------------------------------ tax


def key_dates(label: str) -> list[KeyDate]:
    _, last = tax_year_bounds(label)
    register = date(last.year, 10, 5)
    ret = date(last.year + 1, 1, 31)
    return [
        KeyDate(
            on=register,
            text=f"By {wording.day_text(register).split(' ', 1)[1]} {register.year}, register for Self Assessment "
            "if this is your first year working for yourself.",
        ),
        KeyDate(
            on=ret,
            text=f"By {wording.day_text(ret).split(' ', 1)[1]} {ret.year}, send your return and pay any tax due.",
        ),
    ]


def mtd_note(turnover_pence: int) -> str:
    base = "Making Tax Digital for Income Tax is due to reach turnover over £20,000 from April 2028."
    if turnover_pence < MTD_THRESHOLD_PENCE // 2:
        return f"{base} Your OneQuickJob turnover is well under that."
    if turnover_pence < MTD_THRESHOLD_PENCE:
        return f"{base} Your OneQuickJob turnover is under that so far."
    return f"{base} Your OneQuickJob turnover is over that, so it's worth asking an accountant."


async def tax_years(db: Db, provider: Provider) -> list[str]:
    years = {tax_year(london_today())}
    for repo in (LedgerEntries(db), MileageLogs(db), Expenses(db)):
        years |= set(await repo.coll.distinct("tax_year", {"provider_id": provider.id}))
    return sorted(years, reverse=True)


async def expense_out(db: Db, e: Expense) -> ExpenseOut:
    url = None
    if e.receipt_file_id:
        f = await Files(db).get(e.receipt_file_id)
        url = f.url if f else None
    return ExpenseOut(
        id=e.id,
        local_date=e.local_date,
        description=e.description,
        category=e.category,
        amount_pence=e.amount_pence,
        receipt_url=url,
    )


async def tax_summary(db: Db, provider: Provider, label: str | None = None) -> TaxSummary:
    label = label or tax_year(london_today())
    starts, ends = tax_year_bounds(label)
    entries = await LedgerEntries(db).find({"provider_id": provider.id, "tax_year": label})
    turnover = sum(e.gross_pence for e in entries)
    fees = sum(e.fee_pence for e in entries)
    received = sum(e.net_pence for e in entries)
    logs = await MileageLogs(db).find({"provider_id": provider.id, "tax_year": label}, sort=[("local_date", -1)])
    miles_total = sum((D(log.miles) for log in logs), Decimal(0))
    mileage_pence = year_mileage_pence(miles_total)
    amounts = allowance_by_day(logs)
    expenses = await Expenses(db).find({"provider_id": provider.id, "tax_year": label}, sort=[("local_date", -1)])
    expenses_pence = sum(e.amount_pence for e in expenses)
    costs = fees + mileage_pence + expenses_pence
    allowance_profit = max(0, turnover - TRADING_ALLOWANCE_PENCE)
    costs_profit = turnover - costs
    better = "allowance" if allowance_profit <= costs_profit else "costs"
    rate = f"{MILEAGE_RATE_PENCE}p a mile"
    if miles_total > MILEAGE_THRESHOLD:
        rate += f" for the first {MILEAGE_THRESHOLD:,} miles, then {MILEAGE_RATE_AFTER_PENCE}p"
    return TaxSummary(
        tax_year=label,
        starts_on=starts,
        turnover_pence=turnover,
        fees_pence=fees,
        received_pence=received,
        mileage_miles=float(miles_total),
        mileage_pence=mileage_pence,
        expenses_pence=expenses_pence,
        costs_pence=costs,
        allowance_pence=TRADING_ALLOWANCE_PENCE,
        allowance_profit_pence=allowance_profit,
        costs_profit_pence=costs_profit,
        better=better,
        difference_pence=abs(allowance_profit - costs_profit),
        trips=[mileage_day(log, amounts[log.local_date]) for log in logs],
        expenses=[await expense_out(db, e) for e in expenses],
        key_dates=key_dates(label),
        ends_on=ends,
        tax_years=await tax_years(db, provider),
        mileage_rate_text=rate,
        mtd_note=mtd_note(turnover),
        jobs=sum(1 for e in entries if e.kind == "charge"),
    )


# ------------------------------------------------------------------ the tax pack


def pounds(pence: int) -> str:
    """12345 -> 123.45 (spreadsheet-friendly; negative for refunds)."""
    sign = "-" if pence < 0 else ""
    p = abs(pence)
    return f"{sign}{p // 100}.{p % 100:02d}"


def safe_cell(value: str) -> str:
    """Text a spreadsheet won't run as a formula (CSV injection)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


KIND_WORDS = {"charge": "Visit", "tip": "Tip", "refund": "Refund", "adjustment": "Adjustment"}
DISCLAIMER = (
    "Laid out in the order of HMRC's self-employment pages. The trading allowance covers all your "
    "self-employed income, not just OneQuickJob. We're not tax advisers: check anything you're unsure "
    "about with HMRC or an accountant."
)


@dataclass(frozen=True)
class PackRow:
    on: date
    job: str
    customer: str
    kind: str
    gross: int
    fee: int
    net: int


async def _pack_rows(db: Db, provider: Provider, label: str) -> list[PackRow]:
    entries = await LedgerEntries(db).find({"provider_id": provider.id, "tax_year": label}, sort=[("occurred_at", 1)])
    cats = await categories(db)
    visit_ids = [e.visit_id for e in entries if e.visit_id]
    visits = {v.id: v for v in await Visits(db).find({"_id": {"$in": visit_ids}})} if visit_ids else {}
    cust_ids = list({e.customer_id for e in entries})
    names = {c.id: c.name for c in await Customers(db).find({"_id": {"$in": cust_ids}})} if cust_ids else {}
    rows = []
    for e in entries:
        v = visits.get(e.visit_id or "")
        job = cats[v.category_id].name if v and v.category_id in cats else ""
        rows.append(
            PackRow(
                on=e.local_date,
                job=job,
                customer=short_name(names.get(e.customer_id, "")),
                kind=KIND_WORDS[e.kind] + (" (own customer)" if e.source == "own_customer" else ""),
                gross=e.gross_pence,
                fee=e.fee_pence,
                net=e.net_pence,
            )
        )
    return rows


async def tax_pack_csv(db: Db, provider: Provider, label: str | None = None) -> tuple[str, str]:
    t = await tax_summary(db, provider, label)
    rows = await _pack_rows(db, provider, t.tax_year)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["OneQuickJob tax pack"])
    w.writerow(["Name", safe_cell(provider.name)])
    w.writerow(
        [
            "Tax year",
            f"{t.tax_year} ({wording.day_text(t.starts_on)} {t.starts_on.year} to "
            f"{wording.day_text(t.ends_on)} {t.ends_on.year})",
        ]
    )
    w.writerow(["Made on", london_today().isoformat()])
    w.writerow(["Note", DISCLAIMER])
    w.writerow([])
    w.writerow(["Summary", "Pounds"])
    w.writerow(["Turnover (what customers paid)", pounds(t.turnover_pence)])
    w.writerow(["OneQuickJob fees", pounds(t.fees_pence)])
    w.writerow(["Reached your bank", pounds(t.received_pence)])
    w.writerow([f"Mileage ({t.mileage_miles:g} miles at {t.mileage_rate_text})", pounds(t.mileage_pence)])
    w.writerow(["Kit, supplies and other costs", pounds(t.expenses_pence)])
    w.writerow(["Total costs (fees, mileage and the rest)", pounds(t.costs_pence)])
    w.writerow(["Taxable profit with the £1,000 trading allowance", pounds(t.allowance_profit_pence)])
    w.writerow(["Taxable profit claiming actual costs", pounds(t.costs_profit_pence)])
    better = "The trading allowance" if t.better == "allowance" else "Claiming actual costs"
    w.writerow(["Works out better so far", f"{better}, by {pounds(t.difference_pence)} of profit"])
    w.writerow([])
    w.writerow(["Income"])
    w.writerow(["Date", "Job", "Customer", "Kind", "Customer paid", "OneQuickJob fee", "Reached your bank"])
    for r in rows:
        w.writerow(
            [
                r.on.isoformat(),
                safe_cell(r.job),
                safe_cell(r.customer),
                r.kind,
                pounds(r.gross),
                pounds(r.fee),
                pounds(r.net),
            ]
        )
    w.writerow([])
    w.writerow(["Mileage (a calculated estimate: straight-line distance x 1.25 for roads)"])
    w.writerow(["Date", "Route", "Miles", "Allowance"])
    for d in reversed(t.trips):
        w.writerow([d.local_date.isoformat(), safe_cell(d.route_text), f"{d.miles:g}", pounds(d.amount_pence)])
    w.writerow([])
    w.writerow(["Expenses"])
    w.writerow(["Date", "Description", "Category", "Amount", "Receipt"])
    for e in reversed(t.expenses):
        w.writerow(
            [
                e.local_date.isoformat(),
                safe_cell(e.description),
                e.category,
                pounds(e.amount_pence),
                "Yes" if e.receipt_url else "No",
            ]
        )
    return f"oqj-tax-pack-{t.tax_year}.csv", buf.getvalue()


PACK_CSS = """
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#18261e;background:#fff;margin:0 auto;
  max-width:860px;padding:28px 20px;font-size:16px;line-height:1.45}
h1{font-size:28px;margin:0 0 4px}
h2{font-size:20px;margin:28px 0 8px;border-bottom:2px solid #1e4b38;padding-bottom:4px}
.muted{color:#4f5d54}
table{width:100%;border-collapse:collapse;font-size:14.5px}
td,th{text-align:left;padding:6px 8px;border-bottom:1px solid #d9ded6;vertical-align:top}
td:nth-child(n+5),th:nth-child(n+5){text-align:right}
.sum td:last-child{text-align:right;font-weight:600}
.total td{font-weight:700;border-top:2px solid #18261e}
.note{background:#f2f4ee;padding:12px 14px;border-radius:8px;font-size:14.5px}
@media print{body{padding:0;font-size:12pt}.noprint{display:none}h2{break-after:avoid}tr{break-inside:avoid}}
"""


def _money(pence: int) -> str:
    return html.escape(("−" if pence < 0 else "") + wording.money(abs(pence)))


async def tax_pack_html(db: Db, provider: Provider, label: str | None = None) -> str:
    """A printable page (Print, or Save as PDF, from the browser). Everything is escaped."""
    t = await tax_summary(db, provider, label)
    rows = await _pack_rows(db, provider, t.tax_year)
    e = html.escape
    period = (
        f"{e(wording.day_text(t.starts_on))} {t.starts_on.year} to {e(wording.day_text(t.ends_on))} {t.ends_on.year}"
    )
    better = "The trading allowance" if t.better == "allowance" else "Claiming your actual costs"

    def tr(*cells: str, cls: str = "") -> str:
        return f"<tr{f' class={cls!r}' if cls else ''}>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    income = "".join(
        tr(
            e(r.on.strftime("%d %b %Y")),
            e(r.job),
            e(r.customer),
            e(r.kind),
            _money(r.gross),
            _money(r.fee),
            _money(r.net),
        )
        for r in rows
    ) or tr("No income recorded yet.", "", "", "", "", "", "")
    trips = "".join(
        tr(e(d.local_date.strftime("%d %b %Y")), e(d.route_text), f"{d.miles:g}", _money(d.amount_pence))
        for d in reversed(t.trips)
    ) or tr("No mileage logged yet.", "", "", "")
    costs = "".join(
        tr(
            e(x.local_date.strftime("%d %b %Y")),
            e(x.description),
            e(x.category.title()),
            _money(x.amount_pence),
            "Yes" if x.receipt_url else "No",
        )
        for x in reversed(t.expenses)
    ) or tr("No expenses recorded yet.", "", "", "", "")
    dates = "".join(f"<li>{e(k.text)}</li>" for k in t.key_dates)
    made = f"{e(wording.day_text(london_today()))} {london_today().year}"
    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Tax pack {e(t.tax_year)}: {e(provider.name)}</title>
<style>{PACK_CSS}</style></head><body>
<h1>Tax pack, {e(t.tax_year)}</h1>
<p class="muted">{e(provider.name)}. Tax year {period}. Made on {made}.</p>
<p class="note noprint">To keep a copy, use your browser's Print and choose Save as PDF.</p>
<h2>Summary</h2>
<table class="sum">
{tr("Turnover: what customers paid you", _money(t.turnover_pence))}
{tr("OneQuickJob fees", "−" + _money(t.fees_pence))}
{tr("Reached your bank", _money(t.received_pence))}
{tr(f"Mileage: {t.mileage_miles:g} miles at {e(t.mileage_rate_text)}", _money(t.mileage_pence))}
{tr("Kit, supplies and other costs", _money(t.expenses_pence))}
{tr("Total costs: fees, mileage and the rest", _money(t.costs_pence), cls="total")}
{tr("Taxable profit with the £1,000 trading allowance", _money(t.allowance_profit_pence))}
{tr("Taxable profit claiming actual costs", _money(t.costs_profit_pence))}
</table>
<p><b>{e(better)} works out better so far</b>, by {_money(t.difference_pence)} of profit. You can take the trading
allowance or claim your actual costs, but not both.</p>
<h2>Income</h2>
<table><tr><th>Date</th><th>Job</th><th>Customer</th><th>Kind</th><th>Customer paid</th><th>Our fee</th>
<th>To your bank</th></tr>{income}</table>
<h2>Mileage</h2>
<p class="muted">A calculated estimate from your jobs: home, each job, home, straight-line distance x 1.25 for roads.
It only counts if you claim actual costs.</p>
<table><tr><th>Date</th><th>Route</th><th>Miles</th><th>Amount</th></tr>{trips}</table>
<h2>Kit, supplies and other costs</h2>
<table><tr><th>Date</th><th>What</th><th>Kind</th><th>Amount</th><th>Receipt</th></tr>{costs}</table>
<h2>Key dates</h2><ul>{dates}</ul>
<p class="note">{e(DISCLAIMER)}</p>
</body></html>"""


# ------------------------------------------------------------------ expenses


async def list_expenses(db: Db, provider: Provider, label: str | None = None) -> list[ExpenseOut]:
    label = label or tax_year(london_today())
    rows = await Expenses(db).find({"provider_id": provider.id, "tax_year": label}, sort=[("local_date", -1)])
    return [await expense_out(db, e) for e in rows]


async def add_expense(db: Db, provider: Provider, body: ExpenseIn) -> ExpenseOut:
    today = london_today()
    if body.local_date > today:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "future_date", "That date hasn't happened yet.")
    if body.local_date < tax_year_bounds(tax_year(today))[0] - timedelta(days=366):
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_old", "That's before last tax year.")
    if body.receipt_file_id:
        await own_file(db, body.receipt_file_id, provider.user_id, ("receipt",))
    e = Expense(
        provider_id=provider.id,
        local_date=body.local_date,
        tax_year=tax_year(body.local_date),
        description=" ".join(body.description.split()),
        category=body.category,
        amount_pence=body.amount_pence,
        receipt_file_id=body.receipt_file_id,
    )
    await Expenses(db).insert(e)
    return await expense_out(db, e)


async def delete_expense(db: Db, provider: Provider, expense_id: str) -> None:
    e = await Expenses(db).get(expense_id)
    if e is None or e.provider_id != provider.id:
        not_found("That expense")
    await Expenses(db).delete(e.id)
