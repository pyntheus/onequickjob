"""One-off jobs booked over the next fortnight around the area, so the admin map's booked layer
covers more than Dave's round (A35). They go to providers the journeys don't use (Kasia, Lorna,
Steve, Ray, Hannah, Alan), priced by the engine, at customers from the pool."""

from datetime import date, timedelta

from app.core.timeutil import weekday_key
from app.pricing.answers import defaults_for
from app.pricing.engine import params_for, price
from app.seed.context import Ctx
from app.seed.history import Diary
from app.seed.jobs import add_booking, add_visit


def next_working_day(ctx: Ctx, provider: str, day: date) -> date:
    """The first day on or after `day` that the provider works."""
    for _ in range(7):
        if weekday_key(day) in ctx.providers[provider].working_days:
            return day
        day += timedelta(days=1)
    return day


async def seed_upcoming(ctx: Ctx, diary: Diary) -> None:
    for job in ctx.scenario["upcoming_jobs"]:
        cat = ctx.cats[job["category"]]
        answers = {**defaults_for(cat), **job["answers"]}
        est = price(cat, answers, params_for(ctx.pricing.params, cat.id), job.get("area_m2"))
        day = next_working_day(ctx, job["provider"], ctx.today + timedelta(days=job["in_days"]))
        slot = diary.free_slot(job["provider"], day, est.mins)
        if slot is None:
            continue
        key = f"upcoming:{job['key']}"
        booking = add_booking(
            ctx,
            key=key,
            customer=job["customer"],
            provider=job["provider"],
            category_id=cat.id,
            source="platform",
            via="guide",
            price_pence=est.price_pence,
            created_at=ctx.ago(days=2),
            status="active",
            answers=job["answers"],
        )
        add_visit(ctx, key=key, booking=booking, day=day, hhmm=slot, est_mins=est.mins)
        ctx.w.add(booking)
        diary.book(job["provider"], day, slot, est.mins)
