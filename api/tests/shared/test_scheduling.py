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


async def test_no_working_day_with_room_in_six_months_books_nothing(db, catalogue):
    """Codex review (high): with no working days, time off throughout, or every working morning
    full, there's no slot to give, so first_slot refuses (no_free_day) instead of inventing one;
    the acceptance's transaction is undone and the request stays open."""
    import pytest

    from app.core.errors import Conflict
    from app.models.provider_ops import TimeOff
    from app.repos import JobRequests, Providers, TimeOffRepo
    from app.services import marketplace
    from tests.conftest import make_settings
    from tests.factories import make_customer, make_request

    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"], days=["mon"])
    mon = next_weekday(london_today(), 0)
    nobody = dave.model_copy(update={"working_days": []})
    with pytest.raises(Conflict) as e:
        await schedule.first_slot(db, nobody, "any", "morning", 40, from_day=mon)
    assert e.value.code == "no_free_day" and "Dave H. has no free day" in e.value.message
    # Every Monday morning for six months already full.
    for k in range(schedule.SEARCH_DAYS // 7 + 1):
        await Visits(db).insert(_visit(dave, mon + timedelta(days=7 * k), "09:00", 180))
    with pytest.raises(Conflict):
        await schedule.first_slot(db, dave, "any", "morning", 40, from_day=mon)
    assert to_london(await schedule.first_slot(db, dave, "any", "afternoon", 40, from_day=mon)).date() == mon
    # Away for the whole horizon: a guide acceptance is refused and nothing is booked.
    await db["visits"].delete_many({})
    await TimeOffRepo(db).insert(
        TimeOff(provider_id=dave.id, from_date=london_today(), to_date=london_today() + timedelta(days=200))
    )
    req = await make_request(db, await make_customer(db))
    with pytest.raises(Conflict):
        await marketplace.accept_at_guide(db, make_settings(), req.ref, dave)
    assert (await JobRequests(db).get(req.id)).status == "open" and await db["bookings"].count_documents({}) == 0
    assert (await Providers(db).get(dave.id)).last_booked_at is None, "the whole acceptance was undone"


async def test_a_first_visit_beyond_the_horizon_avoids_a_regulars_later_dates(db, catalogue):
    """Codex re-check (high): regular plans are only made six weeks ahead, so the search also
    counts their later dates as taken. A first visit eight weeks out doesn't land on a regular's
    Monday morning, and the later top-up that makes that Monday's visit can't overlap it."""
    from app.repos import Providers, SeriesRepo

    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"], days=["mon", "tue"])
    mon = next_weekday(london_today(), 0)
    regular = _series("weekly", mon).model_copy(update={"provider_id": dave.id, "est_mins": 180})
    await SeriesRepo(db).insert(regular)
    await schedule.ensure_horizon(db, regular, dave)  # six weeks of Mondays, 09:00 to 12:00
    eight_weeks = mon + timedelta(days=56)
    assert await Visits(db).count({"series_id": regular.id, "local_date": eight_weeks.isoformat()}) == 0
    slot = to_london(await schedule.first_slot(db, dave, "any", "morning", 60, from_day=eight_weeks))
    assert slot.date() == eight_weeks + timedelta(days=1), "the Tuesday: Monday morning is the regular's"
    # Later, the top-up makes that Monday's visit; nothing overlaps the first visit.
    the_day_before = eight_weeks - timedelta(days=1)
    await schedule.ensure_horizon(db, await SeriesRepo(db).get(regular.id), dave, today=the_day_before)
    monday = await Visits(db).find_one({"series_id": regular.id, "local_date": eight_weeks.isoformat()})
    assert monday is not None and to_london(monday.scheduled_start).strftime("%H:%M") == "09:00"
    assert to_london(monday.scheduled_start).date() != slot.date()
    # An afternoon job can still go on that Monday.
    pm = to_london(await schedule.first_slot(db, dave, "any", "afternoon", 60, from_day=eight_weeks))
    assert pm.date() == eight_weeks and pm.strftime("%H:%M") == "13:00"
    assert (await Providers(db).get(dave.id)).working_days == ["mon", "tue"]


async def test_a_first_visit_avoids_a_regulars_dates_left_unmade_by_a_change_of_frequency(db, catalogue):
    """Codex third review (high): visits made months ahead (time off looks ahead), then a change to
    weekly fills only six weeks, leaving the odd weeks unmade before the later fortnightly visits.
    Every plan date counts as taken unless a visit is stored for it, so a first visit doesn't take
    such a Monday, and the fill that later makes it can't overlap."""
    from app.repos import SeriesRepo

    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"], days=["mon", "tue"])
    mon = next_weekday(london_today(), 0)
    plan = _series("fortnightly", mon).model_copy(update={"provider_id": dave.id, "est_mins": 180})
    await SeriesRepo(db).insert(plan)
    for weeks in (0, 6, 12):  # made about four months ahead
        fresh = await SeriesRepo(db).get(plan.id)
        await schedule.ensure_horizon(db, fresh, dave, today=london_today() + timedelta(weeks=weeks))
    weekly = await SeriesRepo(db).update(plan.id, {"frequency": "weekly", "days": ["mon"]})
    await schedule.ensure_horizon(db, weekly, dave, from_day=mon)  # six weeks of weekly dates
    gap = mon + timedelta(weeks=9)  # an odd week: not made, but later fortnightly visits are
    assert await Visits(db).count({"series_id": plan.id, "local_date": gap.isoformat()}) == 0
    assert await Visits(db).count({"series_id": plan.id, "local_date": {"$gt": gap.isoformat()}}) > 0
    slot = to_london(await schedule.first_slot(db, dave, "any", "morning", 60, from_day=gap))
    assert slot.date() == gap + timedelta(days=1), "the Tuesday: that Monday morning is the regular's"
    await schedule.ensure_horizon(db, weekly, dave, today=gap - timedelta(days=1), from_day=mon)
    made = await Visits(db).find_one({"series_id": plan.id, "local_date": gap.isoformat()})
    assert made is not None and to_london(made.scheduled_start).date() != slot.date()
    # A date whose stored visit was cancelled is free again.
    await Visits(db).update(made.id, {"status": "cancelled", "skipped_reason": "plan_change"})
    freed = to_london(await schedule.first_slot(db, dave, "any", "morning", 60, from_day=gap))
    assert freed.date() == gap and freed.strftime("%H:%M") == "09:00"


async def test_a_change_of_frequency_cant_double_book_the_provider(db, catalogue):
    """Codex review of A22 (and A10's accept, which shares it): two fortnightly plans on alternate
    Mondays at 9:00; making one weekly would put it on top of the other. The change is refused
    (409 time_taken) and nothing moves; at a time that's free it goes ahead."""
    import pytest
    from fastapi import HTTPException

    from app.core.db import transaction
    from app.customer import account
    from app.models.bookings import Booking
    from app.repos import SeriesRepo
    from tests.factories import HAZLEMERE

    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"], days=["mon", "tue", "wed", "thu", "fri"])
    mon = next_weekday(london_today(), 0)
    plans = []
    for k, anchor in enumerate((mon, mon + timedelta(days=7))):
        plan = _series("fortnightly", anchor).model_copy(
            update={"provider_id": dave.id, "est_mins": 120, "booking_id": f"b{k}"}
        )
        await SeriesRepo(db).insert(plan)
        await schedule.ensure_horizon(db, plan, dave)
        plans.append(plan)
    first = plans[0]
    booking = Booking(
        id="b0", ref="B-1101", source="own_customer", customer_id="c", provider_id=dave.id, category_id="mowing",
        via="invite", price_pence=3000, unit="a visit", recurring=True, frequency="fortnightly", address=HAZLEMERE,
        series_id=first.id,
    )  # fmt: skip

    async def weekly(session):
        fresh = await SeriesRepo(db).get(first.id, session=session)
        return await account.apply_frequency_change(db, fresh, booking, dave, "weekly", 2800, session=session)

    with pytest.raises(HTTPException) as e:
        await transaction(db, weekly)
    assert e.value.status_code == 409 and e.value.detail["code"] == "time_taken"
    assert "clash with another visit at 09:00 on" in e.value.detail["message"]
    after = await SeriesRepo(db).get(first.id)
    assert (after.frequency, after.price_pence) == ("fortnightly", 3000), "nothing moved"
    # Once the other plan is in the afternoon, the change goes ahead without overlapping it.
    await SeriesRepo(db).update(plans[1].id, {"start_time": "14:00"})
    await db["visits"].delete_many({"series_id": plans[1].id})
    await transaction(db, weekly)
    assert (await SeriesRepo(db).get(first.id)).frequency == "weekly"


async def test_a_change_of_frequency_checks_the_new_anchor_day_too(db, catalogue):
    """Codex re-check (high): with every upcoming visit skipped by the customer, the changed plan
    starts tomorrow. That day is checked like the rest: another visit at 9:00 tomorrow refuses the
    change, and nothing is written (plan, visits, messages)."""
    import pytest
    from fastapi import HTTPException

    from app.core.db import transaction
    from app.customer import account
    from app.models.bookings import Booking
    from app.repos import SeriesRepo
    from tests.factories import HAZLEMERE

    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"])
    tomorrow = london_today() + timedelta(days=1)
    # The plan's own day is three days on, so tomorrow isn't one of its (skipped) dates.
    plan = _series("fortnightly", tomorrow + timedelta(days=2)).model_copy(
        update={"provider_id": dave.id, "est_mins": 60, "booking_id": "b0"}
    )
    await SeriesRepo(db).insert(plan)
    await schedule.ensure_horizon(db, plan, dave)
    skip = {"$set": {"status": "skipped", "skipped_reason": "customer"}}
    await db["visits"].update_many({"series_id": plan.id}, skip)
    await Visits(db).insert(_visit(dave, tomorrow, "09:00", 60))  # another customer's visit
    before = await db["visits"].count_documents({})
    booking = Booking(
        id="b0", ref="B-1101", source="own_customer", customer_id="c", provider_id=dave.id, category_id="mowing",
        via="invite", price_pence=3000, unit="a visit", recurring=True, frequency="fortnightly", address=HAZLEMERE,
        series_id=plan.id,
    )  # fmt: skip

    async def weekly(session):
        fresh = await SeriesRepo(db).get(plan.id, session=session)
        return await account.apply_frequency_change(db, fresh, booking, dave, "weekly", 2800, session=session)

    with pytest.raises(HTTPException) as e:
        await transaction(db, weekly)
    assert e.value.status_code == 409 and e.value.detail["code"] == "time_taken"
    assert (await SeriesRepo(db).get(plan.id)).frequency == "fortnightly"
    assert await db["visits"].count_documents({}) == before and await db["outbox"].count_documents({}) == 0


async def test_a_change_of_frequency_checks_dates_made_past_a_long_pause(db, catalogue):
    """Codex third review (high): a plan paused for six months gets its next two dates made past the
    pause (beyond the six-month window). A change of frequency checks every date its fill makes, so
    an existing visit on the first weekly date after the pause refuses it, and nothing is written."""
    import pytest
    from fastapi import HTTPException

    from app.core.db import transaction
    from app.customer import account
    from app.models.bookings import Booking, Pause
    from app.repos import SeriesRepo
    from tests.factories import HAZLEMERE

    every_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    dave = await make_provider(db, "Dave Hughes", "+447700900201", ["mowing"], days=every_day)
    today = london_today()
    pause = Pause(away_from=today + timedelta(days=1), away_to=today + timedelta(days=180))
    plan = _series("threeweekly", today + timedelta(days=3)).model_copy(
        update={"provider_id": dave.id, "est_mins": 60, "booking_id": "b0", "pause": pause}
    )
    await SeriesRepo(db).insert(plan)
    await schedule.ensure_horizon(db, plan, dave)  # its next two dates, past the pause
    skip = {"$set": {"status": "skipped", "skipped_reason": "customer"}}
    await db["visits"].update_many({"series_id": plan.id}, skip)
    first_weekly = today + timedelta(days=1 + 7 * 26)  # the first weekly date after the pause: day 183
    assert first_weekly > today + timedelta(days=schedule.SEARCH_DAYS)
    await Visits(db).insert(_visit(dave, first_weekly, "09:00", 60))  # another customer's visit
    before = await db["visits"].count_documents({})
    booking = Booking(
        id="b0", ref="B-1101", source="own_customer", customer_id="c", provider_id=dave.id, category_id="mowing",
        via="invite", price_pence=3000, unit="a visit", recurring=True, frequency="threeweekly", address=HAZLEMERE,
        series_id=plan.id,
    )  # fmt: skip

    async def weekly(session):
        fresh = await SeriesRepo(db).get(plan.id, session=session)
        return await account.apply_frequency_change(db, fresh, booking, dave, "weekly", 2800, session=session)

    with pytest.raises(HTTPException) as e:
        await transaction(db, weekly)
    assert e.value.status_code == 409 and e.value.detail["code"] == "time_taken"
    assert (await SeriesRepo(db).get(plan.id)).frequency == "threeweekly"
    assert await db["visits"].count_documents({}) == before and await db["outbox"].count_documents({}) == 0
