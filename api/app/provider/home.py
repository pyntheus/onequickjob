"""The Jobs tab's header: greeting, this week's earnings, rating, the limit and coming up."""

from datetime import timedelta

from app.core.config import Settings
from app.core.db import Db
from app.core.timeutil import london_today, to_london, utcnow, week_start
from app.provider.acting import Acting
from app.provider.common import categories
from app.provider.jobs import list_jobs
from app.provider.limit import get_limit
from app.provider.schemas import ProviderHome, UpcomingVisit
from app.provider.threads import unread_total
from app.repos.bookings import Bookings
from app.repos.ledger_entries import LedgerEntries
from app.repos.visits import Visits
from app.services import wording

COMING_UP = 4


def greeting(name: str) -> str:
    hour = to_london(utcnow()).hour
    part = "Morning" if hour < 12 else "Afternoon" if hour < 17 else "Evening"
    return f"{part}, {wording.first_name(name)}"


async def home(db: Db, s: Settings, a: Acting) -> ProviderHome:
    p = a.provider
    today = london_today()
    mine = {"performer.kind": "helper", "performer.user_id": a.user_id} if a.helper else {"provider_id": p.id}
    upcoming = await Visits(db).find(
        {**mine, "status": "scheduled", "local_date": {"$gte": today.isoformat()}},
        sort=[("scheduled_start", 1)],
        limit=COMING_UP,
    )
    ids = list({v.booking_id for v in upcoming})
    areas = {b.id: b.address.area for b in await Bookings(db).find({"_id": {"$in": ids}})} if ids else {}
    cats = await categories(db)
    coming = [
        UpcomingVisit(
            visit_id=v.id,
            local_date=v.local_date,
            dow=f"{v.local_date:%a}",
            day=v.local_date.day,
            start_time=wording.time_text(v.scheduled_start),
            category_name=cats[v.category_id].name,
            area=areas.get(v.booking_id, ""),
            price_pence=v.price_pence,
        )
        for v in upcoming
    ]
    start = week_start(today)
    week = await LedgerEntries(db).find(
        {
            "provider_id": p.id,
            "local_date": {"$gte": start.isoformat(), "$lte": (start + timedelta(days=6)).isoformat()},
        }
    )
    return ProviderHome(
        greeting=greeting(a.cu.user.name if a.helper else p.name),
        today_text=wording.day_text(today),
        week_earned_pence=0 if a.helper else sum(e.net_pence for e in week),
        week_jobs=0 if a.helper else sum(1 for e in week if e.kind == "charge"),
        rating_avg=p.stats.rating_avg,
        rating_count=p.stats.rating_count,
        limit=await get_limit(db, p, today),
        new_jobs=[] if a.helper else await list_jobs(db, s, p, today),
        coming_up=coming,
        status=p.status,
        helper=a.helper,
        unread_messages=0 if a.helper else await unread_total(db, p.user_id),
    )
