"""Removing what a previous seed wrote, and the few things people created that would
clash with the demo data being written again (same phone, a booking for a seeded
request, a rating on a seeded visit...). Everything else people created is left alone."""

from typing import Any

from app.seed.context import SEED_FLAG, Ctx

NOT_SEEDED = {SEED_FLAG: {"$ne": True}}


async def clear_seeded(ctx: Ctx) -> dict[str, int]:
    """Delete every document flagged as seeded, in every collection."""
    removed: dict[str, int] = {}
    for name in await ctx.db.list_collection_names():
        if name.startswith("system."):
            continue
        res = await ctx.db[name].delete_many({SEED_FLAG: True})
        if res.deleted_count:
            removed[name] = res.deleted_count
    return removed


async def _delete(ctx: Ctx, collection: str, flt: dict[str, Any], why: str) -> None:
    res = await ctx.db[collection].delete_many({**flt, **NOT_SEEDED})
    if res.deleted_count:
        print(f"  removed {res.deleted_count} {collection} created since the last seed ({why})")


async def clear_clashing_people(ctx: Ctx) -> None:
    """Users created by signing in with a seeded phone or email, and profiles for seeded users."""
    users = list(ctx.users.values())
    phones = [u.phone for u in users if u.phone]
    emails = [u.email for u in users if u.email]
    ids = {u.id for u in users}
    clashing = [
        d["_id"]
        async for d in ctx.db["users"].find(
            {"$or": [{"phone": {"$in": phones}}, {"email": {"$in": emails}}], **NOT_SEEDED}
        )
        if d["_id"] not in ids
    ]
    if clashing:
        await _delete(ctx, "users", {"_id": {"$in": clashing}}, "same phone or email as a demo user")
        await _delete(ctx, "sessions", {"user_id": {"$in": clashing}}, "their sessions")
    all_user_ids = list(ids | set(clashing))
    await _delete(ctx, "customers", {"user_id": {"$in": all_user_ids}}, "profile for a demo user")
    await _delete(ctx, "providers", {"user_id": {"$in": all_user_ids}}, "profile for a demo user")


async def clear_children_of_requests(ctx: Ctx, request_ids: list[str]) -> None:
    """Bookings (and everything under them) and offers people made on seeded requests."""
    bookings = [d["_id"] async for d in ctx.db["bookings"].find({"request_id": {"$in": request_ids}, **NOT_SEEDED})]
    await clear_children_of_bookings(ctx, bookings)
    await _delete(ctx, "bookings", {"_id": {"$in": bookings}}, "booked from a demo request")
    await _delete(ctx, "offers", {"request_id": {"$in": request_ids}}, "made on a demo request")


async def clear_children_of_bookings(ctx: Ctx, booking_ids: list[str]) -> None:
    if not booking_ids:
        return
    series = [d["_id"] async for d in ctx.db["series"].find({"booking_id": {"$in": booking_ids}})]
    threads = [d["_id"] async for d in ctx.db["message_threads"].find({"booking_id": {"$in": booking_ids}})]
    await _delete(ctx, "visits", {"booking_id": {"$in": booking_ids}}, "under a cleared booking")
    await _delete(ctx, "series", {"_id": {"$in": series}}, "under a cleared booking")
    await _delete(ctx, "messages", {"thread_id": {"$in": threads}}, "under a cleared booking")
    await _delete(ctx, "message_threads", {"_id": {"$in": threads}}, "under a cleared booking")


async def clear_clashing_visit_children(
    ctx: Ctx, series_ids: list[str], visit_ids: list[str], mileage_days: list[tuple[str, str]]
) -> None:
    """Visits the horizon task added to seeded plans, and ratings, charges, disputes and
    mileage people recorded against seeded visits."""
    await _delete(ctx, "visits", {"series_id": {"$in": series_ids}}, "added to a demo plan")
    await _delete(ctx, "ratings", {"visit_id": {"$in": visit_ids}}, "on a demo visit")
    await _delete(ctx, "ledger_entries", {"visit_id": {"$in": visit_ids}}, "on a demo visit")
    await _delete(ctx, "disputes", {"visit_id": {"$in": visit_ids}}, "on a demo visit")
    for provider_id, day in mileage_days:
        await _delete(ctx, "mileage_logs", {"provider_id": provider_id, "local_date": day}, "on a demo day")
