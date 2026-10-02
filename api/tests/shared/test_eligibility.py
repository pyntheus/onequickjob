"""Who may take a job, who gets alerted, and the earnings limit."""

from datetime import date, timedelta

from app.core import money
from app.core.timeutil import london_today, tax_year, utcnow, week_start
from app.models.common import GeoPoint
from app.models.providers import EarningsLimit
from app.models.records import LedgerEntry
from app.repos import LedgerEntries, Providers
from app.services import eligibility
from tests.factories import make_customer, make_provider, make_request


async def test_can_take_needs_skill_documents_in_date_and_active_status(db, catalogue):
    cats = catalogue
    p = await make_provider(db, "Dave Hughes", "+447700900201", ["gutters"], docs=["insurance"])
    e = eligibility.can_take(p, cats["gutters"])
    assert not e.ok and e.missing_documents == ["ladder_cover"]
    p = await make_provider(db, "Sue Palmer", "+447700900208", ["gutters"], docs=["insurance", "ladder_cover"])
    assert eligibility.can_take(p, cats["gutters"]).ok
    assert not eligibility.can_take(p, cats["mowing"]).ok, "not a skill"
    assert not eligibility.can_take(p, cats["gutters"], today=date(2030, 1, 2)).ok, "documents expired"
    p.status = "suspended"
    assert not eligibility.can_take(p, cats["gutters"]).ok
    p.status = "payouts_paused"
    assert eligibility.can_take(p, cats["gutters"]).ok, "payouts paused can still work"


async def test_alert_targets_radius_days_alerts_and_limit(db, catalogue):
    customer = await make_customer(db)
    near = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    far = await make_provider(db, "Alan Pryce", "+447700900210", ["mowing"])
    await Providers(db).patch(far.id, {"home.location": GeoPoint(lat=51.571, lng=-0.776).model_dump()})  # Marlow
    weekends = await make_provider(db, "Ken Ashworth", "+447700900212", ["mowing"], days=["sat", "sun"])
    muted = await make_provider(db, "Jan Kowalski", "+447700900211", ["mowing"])
    await Providers(db).patch(muted.id, {"alert_settings.sms": False, "alert_settings.whatsapp": False})
    req = await make_request(db, customer)  # weekdays, Hazlemere
    targets = await eligibility.alert_targets(db, req, catalogue["mowing"])
    assert [t.provider.id for t in targets] == [near.id]
    assert weekends.id not in [t.provider.id for t in targets]

    await Providers(db).patch(
        near.id, {"earnings_limit": EarningsLimit(on=True, period="week", amount_pence=5000).model_dump()}
    )
    today = london_today()
    entry = LedgerEntry(
        provider_id=near.id,
        customer_id=customer.id,
        visit_id="v1",
        booking_id="b1",
        kind="charge",
        source="platform",
        gross_pence=6000,
        fee_pence=900,
        net_pence=5100,
        occurred_at=utcnow(),
        local_date=today,
        tax_year=tax_year(today),
        gateway="fake",
    )
    await LedgerEntries(db).insert(entry)
    status = await eligibility.limit_status(db, await Providers(db).get(near.id))
    assert status.reached and status.remaining_pence == 0 and status.earned_pence == 5100
    assert status.resumes_on == week_start(today) + timedelta(days=7)
    assert await eligibility.alert_targets(db, req, catalogue["mowing"]) == [], "no alerts once the limit is reached"


async def test_over_limit_uses_the_providers_share():
    status = eligibility.LimitStatus(
        on=True,
        period="week",
        amount_pence=25000,
        earned_pence=21250,
        remaining_pence=3750,
        reached=False,
        period_start=date(2026, 9, 28),
        resumes_on=date(2026, 10, 5),
    )
    assert not eligibility.over_limit(status, 3000)  # you get £25.50
    assert eligibility.over_limit(status, 6100)  # you get £51.85
    assert money.split(6100).provider_pence == 5185
    off = eligibility.LimitStatus(
        on=False,
        period="week",
        amount_pence=0,
        earned_pence=0,
        remaining_pence=None,
        reached=False,
        period_start=date(2026, 9, 28),
        resumes_on=date(2026, 10, 5),
    )
    assert not eligibility.over_limit(off, 100000)
