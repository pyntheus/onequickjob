"""The demo data, in order. See app/seed/__main__.py for the command line."""

from datetime import datetime
from typing import Any

from app.core.config import Settings
from app.core.db import Db
from app.core.phone import to_national
from app.core.timeutil import utcnow
from app.repos import ensure_indexes
from app.repos.pricing_versions import PricingVersions
from app.seed.calibration import seed_calibration
from app.seed.catalogue import load_catalogue, load_pricing_v1
from app.seed.cleanup import clear_clashing_visit_children, clear_seeded
from app.seed.context import Ctx, Writer, read
from app.seed.disputes import seed_disputes
from app.seed.history import Diary, seed_dave_fill, seed_dave_records, seed_history
from app.seed.outbox import seed_invites, seed_messages
from app.seed.people import seed_people
from app.seed.requests import seed_requests

SUMMARY_COLLECTIONS = [
    "users",
    "customers",
    "providers",
    "tax_identities",
    "categories",
    "pricing_versions",
    "quotes",
    "job_requests",
    "offers",
    "bookings",
    "series",
    "visits",
    "ratings",
    "disputes",
    "message_threads",
    "messages",
    "ledger_entries",
    "mileage_logs",
    "expenses",
    "own_customer_invites",
    "files",
    "outbox",
    "magic_links",
    "fake_gateway",
]


async def seed(db: Db, s: Settings, now: datetime | None = None) -> dict[str, Any]:
    """Write the demo data. Idempotent: the previous run's seeded documents are replaced."""
    ctx = Ctx(db=db, s=s, now=now or utcnow(), w=Writer(db), people=read("people.json"), scenario=read("scenario.json"))
    await ensure_indexes(db)
    ctx.cats = await load_catalogue(db)
    await load_pricing_v1(db)
    ctx.pricing = await PricingVersions(db).live()
    assert ctx.pricing is not None, "no live pricing version"

    removed = await clear_seeded(ctx)
    await seed_people(ctx)

    diary = Diary()
    await seed_history(ctx, diary)
    await seed_disputes(ctx, diary)
    await seed_dave_fill(ctx, diary)
    await seed_calibration(ctx, diary)
    mileage_days = await seed_dave_records(ctx)
    await clear_clashing_visit_children(ctx, sorted(ctx.w.ids["series"]), sorted(ctx.w.ids["visits"]), mileage_days)
    await ctx.w.flush()

    requests = await seed_requests(ctx)
    await seed_messages(ctx, requests)
    await seed_invites(ctx)

    counts = {name: await db[name].count_documents({}) for name in SUMMARY_COLLECTIONS}
    demo = [
        (u.demo_key, u.name, to_national(u.phone) if u.phone else "", ", ".join(u.roles) or "helper")
        for u in sorted(ctx.users.values(), key=lambda u: u.demo_key or "")
        if u.demo_key
    ]
    return {"removed": removed, "counts": counts, "demo_users": demo, "today": ctx.today.isoformat()}


def format_summary(summary: dict[str, Any]) -> str:
    lines = [f"Seeded for {summary['today']} (London)."]
    lines.append("Documents: " + ", ".join(f"{k} {v}" for k, v in summary["counts"].items()))
    lines.append("Demo users (Switch user, or sign in with the phone and the code from the Outbox):")
    lines += [f"  {key:<10} {name:<18} {phone:<14} {roles}" for key, name, phone, roles in summary["demo_users"]]
    return "\n".join(lines)
