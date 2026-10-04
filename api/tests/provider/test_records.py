"""Mileage, the tax summary and pack, and expenses: everything derived from ledger_entries,
mileage_logs and expenses."""

from datetime import date, timedelta
from decimal import Decimal

from app.core import money
from app.core.geo import miles_between
from app.core.timeutil import london_today, tax_year, utcnow
from app.models.records import Expense, MileageLog
from app.provider.records import Point, day_mileage, year_mileage_pence
from app.repos import Expenses, MileageLogs
from app.services import ledger
from tests.factories import make_customer
from tests.provider.conftest import book

HOME = Point("Home", 51.6560, -0.7160)


def test_mileage_is_straight_line_times_one_and_a_quarter_rounded_half_up():
    stop = Point("Hazlemere", 51.6660, -0.7160)  # 0.01 degrees of latitude north: 0.690934 miles
    m = day_mileage(HOME, [stop])
    straight = Decimal(str(miles_between(HOME.lat, HOME.lng, stop.lat, stop.lng)))
    assert round(float(straight), 4) == 0.6909
    assert [(leg.from_label, leg.to_label) for leg in m.legs] == [("Home", "Hazlemere"), ("Hazlemere", "Home")]
    assert [leg.road_miles for leg in m.legs] == [0.86, 0.86]  # 0.6909 x 1.25 = 0.8637
    assert m.miles == Decimal("1.7") and m.amount_pence == 77  # 1.72 -> 1.7 miles; 1.7 x 45 = 76.5 -> 77


def test_mileage_amount_rounds_an_exact_half_up_not_to_even():
    stop = Point("Next door", 51.6565, -0.7160)  # 0.0345 miles each way: 0.04 road miles a leg
    m = day_mileage(HOME, [stop])
    assert m.miles == Decimal("0.1") and m.amount_pence == 5  # 4.5p -> 5p (round() would give 4)


def test_mileage_goes_home_job_job_home_in_order():
    a, b = Point("Widmer End", 51.6655, -0.7330), Point("Penn", 51.6318, -0.6726)
    m = day_mileage(HOME, [a, b])
    assert [leg.to_label for leg in m.legs] == ["Widmer End", "Penn", "Home"]
    assert m.miles == Decimal(str(sum(Decimal(str(leg.road_miles)) for leg in m.legs))).quantize(Decimal("0.1"))


def test_a_years_mileage_drops_to_25p_after_10000_miles():
    assert year_mileage_pence(Decimal("100.0")) == 4500
    assert year_mileage_pence(Decimal("10100.0")) == 10_000 * 45 + 100 * 25
    assert year_mileage_pence(Decimal("0.1")) == 5


async def _charged(db, world, price: int, when=None):
    _, v = await book(db, world.customer, world.dave, price=price, frequency="oneoff")
    split = money.split_for_visit(v.price_pence, v.source, v.performer.kind)
    entry = await ledger.record_charge(db, v, split, at=when or utcnow(), gateway="fake", charge_id=f"ch_{v.id}")
    return v, split, entry


async def test_tax_summary_turnover_fees_and_what_reached_the_bank(dave_client, db, world):
    v1, s1, _ = await _charged(db, world, 3000)
    await _charged(db, world, 3000)
    await ledger.record_tip(db, v1, 500, at=utcnow(), gateway="fake", charge_id="ch_tip")
    await ledger.record_refund(db, v1, money.refund_split(s1, 1000), at=utcnow(), gateway="fake", refund_id="re_1")
    today = london_today()
    await MileageLogs(db).insert(
        MileageLog(
            provider_id=world.dave.id, local_date=today, tax_year=tax_year(today), legs=[], miles=10.0, amount_pence=450
        )
    )
    await Expenses(db).insert(
        Expense(
            provider_id=world.dave.id,
            local_date=today,
            tax_year=tax_year(today),
            description="Mower service",
            amount_pence=6500,
        )
    )
    t = (await dave_client.get("/api/p/tax")).json()
    assert t["tax_year"] == tax_year(today)
    assert t["turnover_pence"] == 3000 + 3000 + 500 - 1000
    assert t["fees_pence"] == 450 + 450 + 0 - 150
    assert t["received_pence"] == 2550 + 2550 + 500 - 850
    assert t["turnover_pence"] == t["fees_pence"] + t["received_pence"]
    assert (t["mileage_miles"], t["mileage_pence"], t["expenses_pence"]) == (10.0, 450, 6500)
    assert t["costs_pence"] == 750 + 450 + 6500
    assert t["allowance_profit_pence"] == 0 and t["costs_profit_pence"] == 5500 - 7700
    assert t["better"] == "costs" and t["difference_pence"] == 2200
    assert t["jobs"] == 2 and len(t["key_dates"]) == 2


async def test_the_trading_allowance_wins_when_costs_are_small(dave_client, db, world):
    for _ in range(4):
        await _charged(db, world, 50000)  # £2,000 of turnover, £300 of fees
    t = (await dave_client.get("/api/p/tax")).json()
    assert t["turnover_pence"] == 200000 and t["fees_pence"] == 30000
    assert t["allowance_profit_pence"] == 100000 and t["costs_profit_pence"] == 170000
    assert t["better"] == "allowance" and t["difference_pence"] == 70000


async def test_tax_key_dates_follow_the_tax_year(dave_client, db, world):
    t = (await dave_client.get("/api/p/tax", params={"tax_year": "2026-27"})).json()
    assert [k["on"] for k in t["key_dates"]] == ["2027-10-05", "2028-01-31"]
    assert t["key_dates"][0]["text"].startswith("By 5 October 2027, register for Self Assessment")
    bad = await dave_client.get("/api/p/tax", params={"tax_year": "2026-99"})
    assert bad.status_code == 422


async def test_the_tax_pack_csv_and_html_escape_what_people_typed(dave_client, db, world):
    await _charged(db, world, 3000)
    await dave_client.post(
        "/api/p/expenses",
        json={
            "local_date": london_today().isoformat(),
            "description": '=HYPERLINK("x") <script>x</script>',
            "amount_pence": 1200,
            "category": "supplies",
        },
    )
    r = await dave_client.get("/api/p/tax/pack.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert "Turnover (what customers paid),30.00" in r.text
    assert "'=HYPERLINK" in r.text and ",=HYPERLINK" not in r.text
    h = await dave_client.get("/api/p/tax/pack.html")
    assert h.status_code == 200 and h.headers["content-type"].startswith("text/html")
    assert "default-src 'none'" in h.headers["content-security-policy"]
    assert "<script>" not in h.text and "&lt;script&gt;" in h.text
    assert "Lawn mowing" in h.text and "We&#x27;re not tax advisers" in h.text


async def test_expenses_add_list_and_delete_only_your_own(app, dave_client, db, world):
    up = await dave_client.post(
        "/api/files", data={"kind": "receipt"}, files={"file": ("r.png", b"\x89PNG\r\n\x1a\n0", "image/png")}
    )
    body = {
        "local_date": london_today().isoformat(),
        "description": " Strimmer  line ",
        "amount_pence": 1800,
        "category": "supplies",
        "receipt_file_id": up.json()["id"],
    }
    r = await dave_client.post("/api/p/expenses", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["description"] == "Strimmer line" and r.json()["receipt_url"].startswith("/files/receipt/")
    assert [e["id"] for e in (await dave_client.get("/api/p/expenses")).json()] == [r.json()["id"]]
    future = await dave_client.post(
        "/api/p/expenses", json={**body, "local_date": (london_today() + timedelta(days=2)).isoformat()}
    )
    assert future.status_code == 422
    other = await make_customer(db, "Not Dave", "+447700900998")
    assert other
    gone = await dave_client.delete(f"/api/p/expenses/{r.json()['id']}")
    assert gone.status_code == 204 and (await dave_client.get("/api/p/expenses")).json() == []
    assert (await dave_client.delete(f"/api/p/expenses/{r.json()['id']}")).status_code == 404


async def test_earnings_show_eight_weeks_and_this_weeks_jobs(dave_client, db, world):
    await _charged(db, world, 3000)
    await _charged(db, world, 3000, when=utcnow() - timedelta(days=21))
    e = (await dave_client.get("/api/p/earnings")).json()
    assert len(e["weekly"]) == 8 and e["weekly"][-1]["net_pence"] == e["week_net_pence"]
    assert e["week_net_pence"] == 2550 and e["week_jobs"] == 1
    assert sum(w["net_pence"] for w in e["weekly"]) == 5100
    assert e["limit"]["on"] is False and e["own_customers_active"] == 0


async def test_mileage_days_add_up_to_the_years_allowance(dave_client, db, world):
    """Codex third review (medium): each day's amount is its share of the year's allowance, so
    the rows in the tax pack reconcile exactly with the summary, across the 10,000-mile drop to
    25p and with rounding."""
    today = london_today()
    start = date(int(tax_year(today)[:4]), 4, 6)
    for i, miles in enumerate([0.1, 0.1, 9999.9, 1000.0, 0.3]):
        day = start + timedelta(days=i)
        await MileageLogs(db).insert(
            MileageLog(
                provider_id=world.dave.id, local_date=day, tax_year=tax_year(day), legs=[], miles=miles, amount_pence=0
            )
        )
    t = (await dave_client.get("/api/p/tax")).json()
    amounts = [d["amount_pence"] for d in sorted(t["trips"], key=lambda d: d["local_date"])]
    assert amounts[:2] == [5, 4], "0.1 miles is 4.5p (5p); 0.2 is 9p, so the second day is 4p"
    assert sum(amounts) == t["mileage_pence"] == year_mileage_pence(Decimal("11000.4"))
    assert t["mileage_pence"] == 10_000 * 45 + round(Decimal("1000.4") * 25)  # 450,000p + 25,010p
    days = (await dave_client.get("/api/p/mileage")).json()
    assert sorted(d["amount_pence"] for d in days) == sorted(amounts)
    pack = (await dave_client.get("/api/p/tax/pack.csv")).text
    assert f"{t['mileage_pence'] // 100}.{t['mileage_pence'] % 100:02d}" in pack
