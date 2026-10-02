"""Scheduling rulings: first free slot after the round, recurrence, pauses, horizon."""

from datetime import date, time, timedelta

from app.core.timeutil import london_datetime, london_today, to_london
from app.models.bookings import Series
from app.models.visits import Performer, Visit
from app.repos import Visits
from app.services import schedule
from tests.factories import make_provider


def next_weekday(d: date, weekday: int) -> date:
    return d + timedelta(days=(weekday - d.weekday()) % 7 or 7)


async def test_first_slot_goes_straight_after_the_previous_visit(db):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"], days=["tue"])
    tue = next_weekday(london_today(), 1)
    await Visits(db).insert(
        Visit(
            booking_id="b",
            customer_id="c",
            provider_id=dave.id,
            category_id="mowing",
            source="platform",
            performer=Performer(provider_id=dave.id, user_id=dave.user_id, name="Dave H."),
            local_date=tue,
            scheduled_start=london_datetime(tue, time(9, 0)),
            price_pence=3200,
            est_mins=38,
        )
    )
    slot = await schedule.first_slot(db, dave, "weekdays", "morning", 38, from_day=tue)
    assert to_london(slot).date() == tue and to_london(slot).strftime("%H:%M") == "10:30"


async def test_first_slot_skips_non_working_days_and_full_windows(db):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"], days=["tue"])
    mon = next_weekday(london_today(), 0)
    slot = await schedule.first_slot(db, dave, "any", "afternoon", 200, from_day=mon)
    local = to_london(slot)
    assert local.weekday() == 1 and local.strftime("%H:%M") == "13:00"
    sat_only = await schedule.first_slot(db, dave, "weekends", "morning", 30, from_day=mon)
    assert to_london(sat_only).date() == mon, "no suitable day in four weeks: fall back to the first day"


def _series(freq: str, anchor: date, **kw) -> Series:
    return Series(
        booking_id="b",
        customer_id="c",
        provider_id="p",
        category_id="mowing",
        frequency=freq,
        days=schedule.series_days(freq, anchor),
        start_time="09:00",
        anchor_date=anchor,
        price_pence=3000,
        est_mins=38,
        **kw,
    )


def test_occurrences_by_frequency():
    anchor = date(2026, 10, 6)
    fortnight = schedule.occurrences(_series("fortnightly", anchor), anchor, anchor + timedelta(days=42))
    assert fortnight == [anchor + timedelta(days=14 * k) for k in (1, 2, 3)]
    monthly = schedule.occurrences(_series("threemonthly", date(2026, 1, 31)), date(2026, 1, 31), date(2026, 12, 31))
    assert monthly == [date(2026, 4, 30), date(2026, 7, 31), date(2026, 10, 31)]
    walks = schedule.occurrences(_series("weekdays", anchor), anchor, anchor + timedelta(days=6))
    assert [d.weekday() for d in walks] == [2, 3, 4, 0]  # strictly after the Tuesday anchor


def test_winter_and_away_pauses():
    anchor = date(2026, 10, 6)
    s = _series("weekly", anchor, pause={"winter": True})
    dates = schedule.occurrences(s, anchor, date(2027, 3, 31))
    assert all(d.month not in (11, 12, 1, 2) for d in dates) and dates[-1].month == 3
    s = _series("weekly", anchor, pause={"away_from": date(2026, 10, 12), "away_to": date(2026, 10, 18)})
    assert date(2026, 10, 13) not in schedule.occurrences(s, anchor, date(2026, 10, 31))


async def test_horizon_is_idempotent(db):
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    s = _series("weekly", london_today())
    await db["series"].insert_one(s.to_mongo())
    first = await schedule.ensure_horizon(db, s, dave)
    again = await schedule.ensure_horizon(db, s, dave)
    assert len(first) >= 5 and again == []
    assert await Visits(db).count({"series_id": s.id}) == len(first)
