"""Scheduling rulings: first free slot after the round, recurrence, pauses, horizon."""

import itertools
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
    local = to_london(sat_only)
    assert local.date() == mon + timedelta(days=1) and local.strftime("%H:%M") == "09:00", (
        "no day suits both: the provider's first working day, never one they don't work"
    )


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


def _visit(provider, day: date, hhmm: str, mins: int) -> Visit:
    hh, mm = (int(x) for x in hhmm.split(":"))
    return Visit(
        booking_id="b",
        customer_id="c",
        provider_id=provider.id,
        category_id="cleaning",
        source="platform",
        performer=Performer(provider_id=provider.id, user_id=provider.user_id, name=provider.short),
        local_date=day,
        scheduled_start=london_datetime(day, time(hh, mm)),
        price_pence=6600,
        est_mins=mins,
    )


async def test_a_first_visit_longer_than_its_window_starts_at_the_window_start(db):
    """A14: a first regular clean is four hours and the morning three. It starts at 9:00 on the
    first weekday with room for all of it, and runs past noon."""
    lorna = await make_provider(
        db, "Lorna Baxter", "+447700900203", ["cleaning"], days=["mon", "tue", "wed", "thu", "fri"]
    )
    mon = next_weekday(london_today(), 0)
    slot = to_london(await schedule.first_slot(db, lorna, "weekdays", "morning", 240, from_day=mon))
    assert slot.date() == mon and slot.strftime("%H:%M") == "09:00"
    # Monday has a visit at 11:00 and Tuesday one at 13:00: four hours from 9:00 (plus travel)
    # would run into both, so Wednesday.
    await Visits(db).insert(_visit(lorna, mon, "11:00", 60))
    await Visits(db).insert(_visit(lorna, mon + timedelta(days=1), "13:00", 60))
    slot = to_london(await schedule.first_slot(db, lorna, "weekdays", "morning", 240, from_day=mon))
    assert slot.date() == mon + timedelta(days=2) and slot.strftime("%H:%M") == "09:00"
    # A visit that fits its window still has to end by the window's end.
    slot = to_london(await schedule.first_slot(db, lorna, "weekdays", "morning", 90, from_day=mon))
    assert slot.date() == mon and slot.strftime("%H:%M") == "09:00"


async def test_a_long_visit_only_starts_at_the_window_start(db):
    """After an earlier visit, a visit longer than its window can't start late in the window."""
    lorna = await make_provider(db, "Lorna Baxter", "+447700900203", ["cleaning"], days=["mon", "tue"])
    mon = next_weekday(london_today(), 0)
    await Visits(db).insert(_visit(lorna, mon, "09:00", 30))
    slot = to_london(await schedule.first_slot(db, lorna, "any", "morning", 240, from_day=mon))
    assert slot.date() == mon + timedelta(days=1) and slot.strftime("%H:%M") == "09:00"
    # A shorter one still goes straight after it.
    slot = to_london(await schedule.first_slot(db, lorna, "any", "morning", 60, from_day=mon))
    assert slot.date() == mon and slot.strftime("%H:%M") == "10:00"


async def test_the_first_visit_keeps_to_working_days_and_time_off_beyond_four_weeks(db):
    """No day free for four weeks: the search carries on to the next day that genuinely fits,
    still on a working day, outside time off."""
    from app.models.provider_ops import TimeOff
    from app.repos import TimeOffRepo

    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"], days=["mon", "tue", "wed", "thu", "fri"])
    mon = next_weekday(london_today(), 0)
    await TimeOffRepo(db).insert(
        TimeOff(provider_id=dave.id, from_date=mon, to_date=mon + timedelta(days=34), status="planned")
    )
    slot = to_london(await schedule.first_slot(db, dave, "weekdays", "morning", 240, from_day=mon))
    assert slot.date() == mon + timedelta(days=35) and slot.weekday() == 0 and slot.strftime("%H:%M") == "09:00"
    # Customer weekends only, provider weekdays only: the provider's first working day after
    # their time off (they rearrange by message), never a Saturday or Sunday.
    slot = to_london(await schedule.first_slot(db, dave, "weekends", "afternoon", 60, from_day=mon))
    assert slot.date() == mon + timedelta(days=35) and slot.strftime("%H:%M") == "13:00"


async def test_weekday_only_cleaning_and_flatpack_bookings_get_a_weekday_first_visit(db, catalogue):
    """The L1 walk-through's bug: weekday-only providers were booked for a Sunday because the
    first visit was longer than its window and the fallback ignored working days."""
    from app.services import marketplace
    from tests.conftest import make_settings
    from tests.factories import make_customer, make_request

    lorna = await make_provider(
        db, "Lorna Baxter", "+447700900203", ["cleaning", "flatpack"], days=["mon", "tue", "wed", "thu", "fri"]
    )
    customer = await make_customer(db)
    tomorrow = london_today() + timedelta(days=1)
    first_weekday = next(tomorrow + timedelta(days=k) for k in range(7) if (tomorrow + timedelta(days=k)).weekday() < 5)
    for category_id in ("cleaning", "flatpack"):
        req = await make_request(db, customer, category_id)  # weekdays, morning
        out = await marketplace.accept_at_guide(db, make_settings(), req.ref, lorna)
        start = to_london(out.first_visit.scheduled_start)
        assert (req.first_mins or req.mins) > 180 or category_id == "flatpack"
        assert start.weekday() < 5, f"{category_id}: {start:%A}"
        assert start.strftime("%H:%M") == "09:00"
        if category_id == "cleaning":
            assert start.date() == first_weekday
        else:  # the clean's first visit fills that morning, so the flat-pack goes to the next weekday
            assert start.date() > first_weekday


async def _weekly_plan(db):
    from app.services import marketplace
    from tests.conftest import make_settings
    from tests.factories import make_customer, make_request

    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    customer = await make_customer(db)
    req = await make_request(db, customer, "mowing", answers={"frequency": "weekly"})
    out = await marketplace.accept_at_guide(db, make_settings(), req.ref, dave)
    from app.repos import SeriesRepo

    series = await SeriesRepo(db).find_one({"booking_id": out.booking.id})
    assert series is not None and series.frequency == "weekly"
    return series


async def test_the_horizon_top_up_rereads_a_plan_changed_while_it_runs(db, catalogue, monkeypatch):
    """A13 (contract-changes L1 item 19): a change of frequency and price that commits after the
    top-up read the plan never leaves visits at the old cadence or price: the top-up's write to
    the plan conflicts and it runs again on the plan as changed."""
    from app.core.timeutil import utcnow
    from app.repos.bookings import Bookings

    series = await _weekly_plan(db)
    before = {v.id for v in await Visits(db).find({"series_id": series.id})}
    real_get = Bookings.get
    changed = False

    async def get_then_change(self, id_, *, session=None):
        nonlocal changed
        if not changed:  # the plan has been read: a change of frequency commits now
            changed = True
            await db["series"].update_one(
                {"_id": series.id}, {"$set": {"frequency": "fortnightly", "price_pence": 2500, "updated_at": utcnow()}}
            )
        return await real_get(self, id_, session=session)

    monkeypatch.setattr(Bookings, "get", get_then_change)
    made = await schedule.top_up(db, series.id, today=london_today() + timedelta(days=42))
    added = [v for v in await Visits(db).find({"series_id": series.id}, sort=[("local_date", 1)]) if v.id not in before]
    assert changed and made and len(added) == len(made)
    assert {v.price_pence for v in added} == {2500}
    gaps = {(b.local_date - a.local_date).days for a, b in itertools.pairwise(added)}
    assert gaps <= {14}
    assert all((v.local_date - series.anchor_date).days % 14 == 0 for v in added)


async def test_the_horizon_top_up_adds_nothing_to_a_plan_cancelled_while_it_runs(db, catalogue, monkeypatch):
    from app.core.timeutil import utcnow
    from app.repos.bookings import Bookings

    series = await _weekly_plan(db)
    count = await Visits(db).count({"series_id": series.id})
    real_get = Bookings.get

    async def get_then_cancel(self, id_, *, session=None):
        await db["series"].update_one({"_id": series.id}, {"$set": {"status": "cancelled", "updated_at": utcnow()}})
        return await real_get(self, id_, session=session)

    monkeypatch.setattr(Bookings, "get", get_then_cancel)
    assert await schedule.top_up(db, series.id, today=london_today() + timedelta(days=42)) == []
    assert await Visits(db).count({"series_id": series.id}) == count


async def test_ensure_horizon_from_a_given_day(db, catalogue):
    """With from_day (after a change of frequency) every plan date after it is made, and a date
    an earlier change cancelled comes back at the plan's price."""
    from app.repos import Providers, SeriesRepo

    series = await _weekly_plan(db)
    dave = await Providers(db).get(series.provider_id)
    visits = await Visits(db).find({"series_id": series.id}, sort=[("local_date", 1)])
    third = visits[2]
    await Visits(db).update(third.id, {"status": "cancelled", "skipped_reason": "plan_change"})
    # Without from_day nothing changes: it only adds after the plan's latest visit.
    assert await schedule.ensure_horizon(db, series, dave) == []
    fresh = await SeriesRepo(db).update(series.id, {"price_pence": 2700})
    made = await schedule.ensure_horizon(db, fresh, dave, from_day=visits[0].local_date)
    assert [v.id for v in made] == [third.id]
    back = await Visits(db).get(third.id)
    assert back.status == "scheduled" and back.skipped_reason is None and back.price_pence == 2700
