"""A provider's lifecycle: signing up, then active once every required check is done (decisions.md
A19). Admins can still suspend and reinstate (L3).

The checks: identity and insurance verified and in date, tax details given, a payment account
the gateway has enabled, at least one job type chosen (A24), and a basic DBS check verified and in
date if any category they've chosen needs one. Whoever completes the last of them (an admin
verifying a document, the provider giving their tax details, finishing payout set-up or choosing
their jobs, the gateway confirming the account) calls activate_if_ready inside the
transaction that wrote it, so the provider becomes active, is texted and the change is
audit-logged in the same commit.
"""

from datetime import date

from app.core.config import Settings
from app.core.db import Db, DbSession
from app.core.timeutil import london_today
from app.models.common import Actor, Related
from app.models.providers import Provider
from app.repos.categories import Categories
from app.repos.providers import Providers
from app.repos.users import Users
from app.services.audit import audit
from app.services.notify import link, notify, recipient_for

CHECK_WORDS = {
    "identity": "ID check",
    "insurance": "insurance",
    "dbs_basic": "basic DBS check",
    "tax": "tax details",
    "payouts": "payout account",
    "jobs": "the jobs they do",
}


async def missing_checks(
    db: Db, provider: Provider, *, today: date | None = None, session: DbSession | None = None
) -> list[str]:
    """The checks still to do before the provider can be active (keys of CHECK_WORDS), in order."""
    today = today or london_today()
    held = {
        d.type for d in provider.documents if d.status == "verified" and (d.expires_on is None or d.expires_on >= today)
    }
    needed = ["identity", "insurance"]
    if provider.skills:
        cats = await Categories(db).find({"_id": {"$in": provider.skills}}, session=session)
        if any("dbs_basic" in c.requires for c in cats):
            needed.append("dbs_basic")
    missing = [t for t in needed if t not in held]
    if not provider.tax.complete:
        missing.append("tax")
    if provider.payment_account is None or provider.payment_account.status != "enabled":
        missing.append("payouts")
    if not provider.skills:
        missing.append("jobs")
    return missing


async def activate_if_ready(
    db: Db, s: Settings, provider_id: str, *, actor: Actor, session: DbSession
) -> Provider | None:
    """Inside the caller's transaction, after it has written one of the checks: a provider still
    signing up with nothing left to check becomes active (guarded on signing_up, so a suspension
    committing meanwhile conflicts), is texted provider_activated, and the change is audit-logged.
    Returns the activated provider, or None if nothing changed."""
    provider = await Providers(db).get(provider_id, session=session)
    if provider is None or provider.status != "signing_up":
        return None
    if await missing_checks(db, provider, session=session):
        return None
    activated = await Providers(db).update(
        provider.id, {"status": "active", "status_reason": None}, extra_filter={"status": "signing_up"}, session=session
    )
    if activated is None:
        return None
    user = await Users(db).get(provider.user_id, session=session)
    if user and user.phone:
        await notify(
            db,
            "provider_activated",
            to=recipient_for(user),
            data={"first": provider.name.split(" ")[0], "link": link("/p", s)},
            related=Related(provider_id=provider.id, user_id=user.id),
            idempotency_key=f"provider:{provider.id}:activated",
            settings=s,
            session=session,
        )
    await audit(
        db,
        actor,
        "provider.activated",
        Related(provider_id=provider.id),
        before={"status": "signing_up"},
        after={"status": "active"},
        note="Every required check is done",
        session=session,
    )
    return activated
