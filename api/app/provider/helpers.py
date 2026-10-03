"""Helpers: linked user accounts who do visits in the provider's place. The provider is paid
and the customer is always told who's coming. A helper signs in with their own phone; the
app then shows them only the visits they've been sent to."""

from datetime import date

from fastapi import status
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail
from app.core.phone import InvalidPhone, is_mobile, to_e164
from app.core.timeutil import london_today
from app.models.categories import Category
from app.models.common import Related
from app.models.providers import Helper, Provider
from app.models.users import User
from app.provider.common import short_name
from app.provider.schemas import HelperNew, HelperOut
from app.repos.categories import DocumentTypes
from app.repos.providers import Providers
from app.repos.users import Users
from app.services.auth import create_magic_link
from app.services.notify import link, notify, recipient_for

STATUS_TEXT = {
    "invited": "Invite sent. They set up with the link in their text.",
    "checking": "We're checking their documents.",
    "ready": "Ready to send.",
    "removed": "No longer helping.",
}


def initials(name: str) -> str:
    return "".join(w[0] for w in name.split()[:2]).upper()


def helper_badges(helper: Helper, labels: dict[str, str]) -> list[str]:
    """What the customer can be told about them: checked documents that are in date."""
    today = london_today()
    held = [d for d in helper.documents if d.status == "verified" and (d.expires_on is None or d.expires_on >= today)]
    badges = ["ID checked"] if helper.status == "ready" or any(d.type == "identity" for d in held) else []
    for d in held:
        if d.type == "identity":
            continue
        if d.type == "insurance" and d.expires_on:
            badges.append(f"Insured to {d.expires_on:%b %Y}")
        elif d.type == "dbs_basic":
            badges.append("Basic DBS")
        else:
            badges.append(labels.get(d.type, d.type))
    return badges


def helper_out(helper: Helper, labels: dict[str, str]) -> HelperOut:
    rel = helper.relationship.strip()
    text = STATUS_TEXT[helper.status]
    return HelperOut(
        user_id=helper.user_id,
        name=helper.name,
        initials=initials(helper.name),
        relationship=rel,
        status=helper.status,
        badges=helper_badges(helper, labels),
        status_text=f"{rel}. {text}" if rel else text,
    )


async def doc_labels(db: Db) -> dict[str, str]:
    return {t.id: t.label for t in await DocumentTypes(db).all()}


async def list_helpers(db: Db, provider: Provider) -> list[HelperOut]:
    labels = await doc_labels(db)
    return [helper_out(h, labels) for h in provider.helpers if h.status != "removed"]


def helper_missing(helper: Helper, category: Category, today: date | None = None) -> list[str]:
    """Document types the helper doesn't hold (verified and in date) for this kind of job: the
    same rule as eligibility.can_take, on the helper's own documents. No documents on record means
    every one is missing."""
    today = today or london_today()
    held = {
        d.type for d in helper.documents if d.status == "verified" and (d.expires_on is None or d.expires_on >= today)
    }
    return [t for t in ["identity", *category.requires] if t not in held]


def ready_helper(provider: Provider, user_id: str, category: Category | None = None) -> Helper:
    """The helper, if they can be sent to a visit (of this category): ready, and holding the
    documents the job needs."""
    helper = next((h for h in provider.helpers if h.user_id == user_id), None)
    if helper is None or helper.status == "removed":
        fail(status.HTTP_404_NOT_FOUND, "not_your_helper", "That helper isn't on your list.")
    first = helper.name.split(" ")[0]
    if helper.status != "ready":
        fail(status.HTTP_409_CONFLICT, "helper_not_ready", f"{first} can do visits once we've checked their documents.")
    if category is not None and helper_missing(helper, category):
        fail(
            status.HTTP_409_CONFLICT,
            "helper_missing_documents",
            f"{first} can't do {category.name.lower()} at the moment: some documents it needs aren't checked "
            "or have run out.",
        )
    return helper


async def add_helper(db: Db, s: Settings, provider: Provider, body: HelperNew) -> HelperOut:
    """A new helper is a user of their own, invited by text with a single-use sign-in link. They
    have no roles; helper_of links them to this provider, which lets the provider send them to
    visits and nothing more (A17: app.core.deps.current_provider refuses them, so they can't accept
    jobs or suggest prices for the provider). A number that already has an account can't be a
    helper."""
    try:
        phone = to_e164(body.phone)
    except InvalidPhone as e:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_phone", str(e))
    if not is_mobile(phone):
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_a_mobile", "Enter a mobile number, so we can text them.")
    if await Users(db).by_phone(phone):
        fail(
            status.HTTP_409_CONFLICT,
            "number_in_use",
            "That number already has a OneQuickJob account, so it can't be added as a helper. "
            "Ring us and we'll sort it out.",
        )
    name = " ".join(body.name.split())
    helper_user = User(name=name, phone=phone, roles=[], helper_of=provider.id)
    helper = Helper(user_id=helper_user.id, name=name, relationship=body.relationship.strip(), status="invited")

    async def add(session: DbSession) -> None:
        await Users(db).insert(helper_user, session=session)
        added = await Providers(db).update(
            provider.id, {}, push={"helpers": helper.model_dump(mode="python")}, session=session
        )
        assert added is not None
        token = await create_magic_link(db, s, helper_user.id, "helper_signup", "/p/me", session=session)
        await notify(
            db,
            "helper_invite",
            to=recipient_for(helper_user),
            data={"provider": short_name(provider.name), "link": link(f"/p/me?t={token}", s)},
            related=Related(provider_id=provider.id, user_id=helper_user.id),
            settings=s,
            session=session,
        )

    try:
        await transaction(db, add)
    except DuplicateKeyError:  # the same number added twice at once
        fail(status.HTTP_409_CONFLICT, "number_in_use", "That number has just been added.")
    return helper_out(helper, await doc_labels(db))
