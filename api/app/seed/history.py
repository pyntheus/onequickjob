"""Dave's round (regulars, own customers), past jobs for Sarah and Anita, Dave's one-off
work that makes his earnings look like the prototype's, his mileage and expenses."""

from collections import defaultdict
from datetime import date, timedelta
from itertools import pairwise

from app.core import money
from app.core.geo import ROAD_FACTOR, miles_between
from app.core.rounding import D, round_half_up
from app.core.timeutil import tax_year, week_start, weekday_key
from app.models.bookings import Series
from app.models.provider_ops import OwnCustomerInvite
from app.models.ratings import Rating
from app.models.records import Expense, MileageLeg, MileageLog
from app.pricing.answers import defaults_for
from app.pricing.engine import params_for, price
from app.seed.context import Ctx, mulberry32, sid
from app.seed.jobs import add_after_photo, add_booking, add_thread, add_visit, minutes_near

WEEKDAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
HISTORY_DAYS = 120
HORIZON_DAYS = 42
SLOTS = ["09:00", "10:30", "12:00", "14:00", "15:30"]


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class Diary:
    """Which times a provider is busy on each day, so seeded visits don't overlap."""

    def __init__(self) -> None:
        self.busy: dict[tuple[str, date], list[tuple[int, int]]] = defaultdict(list)

    def book(self, provider: str, day: date, hhmm: str, mins: int) -> None:
        self.busy[(provider, day)].append((_mins(hhmm), _mins(hhmm) + mins))

    def free_slot(self, provider: str, day: date, mins: int) -> str | None:
        for slot in SLOTS:
            start = _mins(slot)
            if all(start + mins + 30 <= a or start >= b + 30 for a, b in self.busy[(provider, day)]):
                return slot
        return None


def regular_dates(ctx: Ctx, reg: dict) -> list[date]:
    """Fortnightly: anchored on the next such weekday (today included), so the round always
    has something coming up. Every 3 months: the weekday after next, and 13 weeks before."""
    today = ctx.today
    wd = WEEKDAY_INDEX[reg["weekday"]]
    if reg["frequency"] == "fortnightly":
        anchor = today + timedelta(days=(wd - today.weekday()) % 7)
        dates = [anchor + timedelta(days=14 * k) for k in range(-12, 6)]
        return [d for d in dates if today - timedelta(days=HISTORY_DAYS) <= d <= today + timedelta(days=HORIZON_DAYS)]
    nxt = today + timedelta(days=(wd - today.weekday()) % 7 or 7) + timedelta(days=7)
    return [nxt - timedelta(weeks=13), nxt]


def working_day(ctx: Ctx, provider: str, day: date) -> date:
    """The latest day on or before `day` that the provider works."""
    for _ in range(7):
        if weekday_key(day) in ctx.providers[provider].working_days:
            return day
        day -= timedelta(days=1)
    return day


async def seed_history(ctx: Ctx, diary: Diary) -> None:
    rnd = mulberry32(20261)
    dave = ctx.providers["dave"]

    # ---------------------------------------------------------------- regulars
    for reg in ctx.scenario["regulars"]:
        key = reg["key"]
        dates = regular_dates(ctx, reg)
        customer = ctx.customers[reg["customer"]]
        own = reg["source"] == "own_customer"
        invite_id = sid("invite", key) if own else None
        booking = add_booking(
            ctx,
            key=f"regular:{key}",
            customer=reg["customer"],
            provider=reg["provider"],
            category_id=reg["category"],
            source=reg["source"],
            via="invite" if own else "guide",
            price_pence=reg["price_pence"],
            created_at=customer.created_at + timedelta(hours=1),
            recurring=True,
            frequency=reg["frequency"],
            status="active",
            answers=reg["answers"],
            when=reg["window"],
            invite_id=invite_id,
        )
        series = Series(
            id=sid("series", key),
            booking_id=booking.id,
            customer_id=customer.id,
            provider_id=dave.id,
            category_id=reg["category"],
            frequency=reg["frequency"],
            days=[reg["weekday"]],
            start_time=reg["time"],
            anchor_date=min(dates) if reg["frequency"] == "fortnightly" else max(dates),
            price_pence=reg["price_pence"],
            est_mins=reg["est_mins"],
            window=reg["window"],
            horizon_until=max(dates),
            **ctx.timestamps(booking.created_at),
        )
        booking.series_id = series.id
        ctx.w.add(series)
        for d in dates:
            done = d < ctx.today
            add_visit(
                ctx,
                key=f"regular:{key}:{d.isoformat()}",
                booking=booking,
                day=d,
                hhmm=reg["time"],
                est_mins=reg["est_mins"],
                actual_mins=minutes_near(reg["est_mins"], rnd) if done else None,
                window=reg["window"],
            )
            diary.book(reg["provider"], d, reg["time"], reg["est_mins"])
        add_thread(ctx, f"regular:{key}", booking)
        ctx.w.add(booking)
        if own:
            ctx.w.add(
                OwnCustomerInvite(
                    id=invite_id,
                    provider_id=dave.id,
                    name=customer.name,
                    phone=ctx.users[reg["customer"]].phone,
                    category_id=reg["category"],
                    price_pence=reg["price_pence"],
                    frequency=reg["frequency"],
                    status="accepted",
                    customer_id=customer.id,
                    booking_id=booking.id,
                    accepted_at=booking.created_at,
                    **ctx.timestamps(booking.created_at - timedelta(days=1)),
                )
            )

    # ---------------------------------------------------------------- past one-off jobs (Sarah, Anita)
    for job in ctx.scenario["past_jobs"]:
        key = job["key"]
        day = working_day(ctx, job["provider"], ctx.day(job["days_ago"]))
        booking = add_booking(
            ctx,
            key=f"past:{key}",
            customer=job["customer"],
            provider=job["provider"],
            category_id=job["category"],
            source="platform",
            via="guide",
            price_pence=job["price_pence"],
            created_at=ctx.at(day - timedelta(days=4), "19:20"),
        )
        visit_id = sid("visit", f"past:{key}")
        finished_at = ctx.at(day, job["time"]) + timedelta(minutes=4 + job["actual_mins"])
        photos = []
        if job.get("after_photo"):
            owner = ctx.users[job["provider"]].id
            photos.append(add_after_photo(ctx, f"past:{key}", owner, finished_at, visit_id))
        visit = add_visit(
            ctx,
            key=f"past:{key}",
            booking=booking,
            day=day,
            hhmm=job["time"],
            est_mins=job["est_mins"],
            actual_mins=job["actual_mins"],
            photos_after=photos,
        )
        diary.book(job["provider"], day, job["time"], job["est_mins"])
        if r := job.get("rating"):
            rating = Rating(
                id=sid("rating", key),
                visit_id=visit.id,
                booking_id=booking.id,
                customer_id=booking.customer_id,
                provider_id=booking.provider_id,
                stars=r["stars"],
                tags=r["tags"],
                **ctx.timestamps(finished_at + timedelta(hours=3)),
            )
            visit.rating_id = rating.id
            ctx.w.add(rating)
        if thread_key := job.get("thread"):
            start = ctx.at(day, job["time"])
            msgs = [
                (m["from"], m["text"], start - timedelta(minutes=m["minutes_before_visit"]))
                for m in ctx.scenario["threads"][thread_key]
            ]
            add_thread(ctx, f"past:{key}", booking, msgs)
        ctx.w.add(booking)


def _price(ctx: Ctx, entry: dict) -> tuple[int, int]:
    cat = ctx.cats[entry["category"]]
    answers = {**defaults_for(cat), **entry["answers"]}
    est = price(cat, answers, params_for(ctx.pricing.params, cat.id), entry.get("area_m2"))
    return est.price_pence, est.mins


async def seed_dave_fill(ctx: Ctx, diary: Diary) -> None:
    """One-off jobs for Dave so his weekly earnings follow the prototype's chart (about
    £150-£240 a week lately) and the tax year to date is in the region of £2,800."""
    rnd = mulberry32(4217)
    dave = ctx.providers["dave"]
    menu = [(e, *_price(ctx, e)) for e in ctx.scenario["dave_one_off_menu"]]
    pool = [c["key"] for c in ctx.people["pool"]]
    net_by_week: dict[date, int] = defaultdict(int)
    for v in ctx.visits:
        if v.provider_id == dave.id and v.charge.status == "succeeded":
            net_by_week[week_start(v.local_date)] += v.charge.provider_pence

    targets = ctx.scenario["dave_earlier_weekly_net_pence"] + ctx.scenario["dave_weekly_net_pence"]
    this_week = week_start(ctx.today)
    weeks = [this_week - timedelta(weeks=len(targets) - 1 - i) for i in range(len(targets))]
    n = 0
    for week, target in zip(weeks, targets, strict=True):
        days = [week + timedelta(days=i) for i in range(7)]
        days = [
            d
            for d in days
            if d < ctx.today and weekday_key(d) in dave.working_days and d >= ctx.today - timedelta(days=HISTORY_DAYS)
        ]
        if week == this_week:
            target = target * min(5, len(days)) // 5
        remaining = target - net_by_week[week]
        tries = 0
        while days and remaining > 1500 and tries < 30:
            tries += 1
            options = [m for m in menu if money.split(m[1]).provider_pence <= remaining + 1200]
            if not options:
                break
            entry, price_pence, est = options[int(rnd() * len(options))]
            day = days[int(rnd() * len(days))]
            slot = diary.free_slot("dave", day, est)
            if slot is None:
                continue
            n += 1
            customer = pool[int(rnd() * len(pool))]
            key = f"dave_oneoff:{n}"
            booking = add_booking(
                ctx,
                key=key,
                customer=customer,
                provider="dave",
                category_id=entry["category"],
                source="platform",
                via="guide",
                price_pence=price_pence,
                created_at=ctx.at(day - timedelta(days=3), "18:40"),
                answers=entry["answers"],
            )
            v = add_visit(
                ctx, key=key, booking=booking, day=day, hhmm=slot, est_mins=est, actual_mins=minutes_near(est, rnd)
            )
            ctx.w.add(booking)
            diary.book("dave", day, slot, est)
            remaining -= v.charge.provider_pence


async def seed_dave_records(ctx: Ctx) -> list[tuple[str, str]]:
    """Mileage (last three weeks of working days) and the three expenses. Returns the
    (provider_id, date) pairs used, for clash clean-up."""
    dave = ctx.providers["dave"]
    home = dave.home.location
    by_day: dict[date, list] = defaultdict(list)
    for v in ctx.visits:
        if (
            v.performer.provider_id == dave.id
            and v.status == "finished"
            and ctx.today - timedelta(days=21) <= v.local_date < ctx.today
        ):
            by_day[v.local_date].append(v)
    used: list[tuple[str, str]] = []
    for day, visits in sorted(by_day.items()):
        visits.sort(key=lambda v: v.scheduled_start)
        stops = [("Home", home.lat, home.lng)]
        for v in visits:
            a = ctx.visit_address[v.id]
            stops.append((a.area, a.lat, a.lng))
        stops.append(("Home", home.lat, home.lng))
        legs = []
        for (fl, flat, flng), (tl, tlat, tlng) in pairwise(stops):
            straight = miles_between(flat, flng, tlat, tlng)
            legs.append(
                MileageLeg(
                    from_label=fl,
                    to_label=tl,
                    straight_miles=round(straight, 2),
                    road_miles=round(straight * ROAD_FACTOR, 2),
                )
            )
        miles = round(sum(leg.road_miles for leg in legs), 1)
        at = max(v.finished_at for v in visits) + timedelta(minutes=30)
        ctx.w.add(
            MileageLog(
                id=sid("mileage", "dave", day.isoformat()),
                provider_id=dave.id,
                local_date=day,
                tax_year=tax_year(day),
                legs=legs,
                miles=miles,
                rate_pence_per_mile=45,
                amount_pence=round_half_up(D(miles) * 45),
                method="calculated_estimate",
                visit_ids=[v.id for v in visits],
                **ctx.timestamps(at),
            )
        )
        used.append((dave.id, day.isoformat()))
    for e in ctx.scenario["expenses"]:
        day = ctx.day(e["days_ago"])
        ctx.w.add(
            Expense(
                id=sid("expense", e["key"]),
                provider_id=dave.id,
                local_date=day,
                tax_year=tax_year(day),
                description=e["description"],
                category=e["category"],
                amount_pence=e["amount_pence"],
                **ctx.timestamps(ctx.at(day, "17:45")),
            )
        )
    return used
