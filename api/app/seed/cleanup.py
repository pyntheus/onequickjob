"""Resetting the demo (decisions.md A21). `make seed` first removes everything demo runs created,
in every collection (requests, bookings, visits, ledger entries, mileage, time off, cover requests,
plan changes, payment attempts, events and refunds, messages, the outbox, the fake gateway's
records, uploads, sign-ups...), and the previous run's seeded documents; then the seed writes its
documents again, so every re-seed starts from the same state.

Kept, because they aren't demo state:
- the catalogue (written again from the seed JSON) and the address look-up cache;
- pricing versions admins drafted or approved, with their audit entries (R14: re-seeding never
  makes version 1 live again once something else is);
- seeded providers' sealed tax identities (sealing isn't deterministic, so people.py keeps one that
  still unseals to the same values);
- admins who aren't in the seed (demo runs can't create them), and the sessions of everyone who
  remains, so a signed-in browser stays signed in (finish_reset).
"""

from typing import Any

from app.seed.context import SEED_FLAG, Ctx, sid

KEEP = {"categories", "category_groups", "document_types", "excluded_jobs", "pricing_versions", "address_cache"}
NOT_SEEDED = {SEED_FLAG: {"$ne": True}}


async def reset_demo(ctx: Ctx) -> dict[str, int]:
    """Delete what demo runs created and what the last seed wrote. Returns, per collection, how
    many documents demo runs had created (the seed's own aren't counted)."""
    seeded_providers = [sid("provider", p["key"]) for p in ctx.people["providers"]]
    kept: dict[str, dict[str, Any]] = {
        "audit_log": {"action": {"$regex": r"^pricing\."}},
        "users": {"roles": "admin"},
        "tax_identities": {"provider_id": {"$in": seeded_providers}},
    }
    removed: dict[str, int] = {}
    for name in sorted(await ctx.db.list_collection_names()):
        if name.startswith("system.") or name in KEEP or name == "sessions":  # sessions: finish_reset
            continue
        keep = kept.get(name)
        made = await ctx.db[name].delete_many({**NOT_SEEDED, "$nor": [keep]} if keep else NOT_SEEDED)
        if made.deleted_count:
            removed[name] = made.deleted_count
        await ctx.db[name].delete_many({SEED_FLAG: True})
    return removed


async def finish_reset(ctx: Ctx) -> int:
    """After the seed is written: sessions of users who no longer exist go. Returns how many."""
    users = {d["_id"] async for d in ctx.db["users"].find({}, {"_id": 1})}
    res = await ctx.db["sessions"].delete_many({"user_id": {"$nin": sorted(users)}})
    return res.deleted_count
