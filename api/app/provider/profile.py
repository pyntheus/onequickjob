"""Me: the profile, documents, skills, travel radius, working days and alert settings.

Documents: an upload is pending until an admin checks it (L3). Its expiry comes from the shared
rule, services.documents.expiry_for (a basic DBS check: 12 months from its issue date;
others: the stated expiry). A new copy uploaded while the current one is verified and in date
is kept alongside it as a pending renewal, so the provider can keep taking jobs while it's
checked; verifying it (Providers.set_document, L3) replaces both. A helper's documents are
kept on their entry in the provider's helper list.
"""

import re
from datetime import date

from fastapi import status

from app.core.db import Db
from app.core.errors import fail
from app.core.timeutil import london_today, utcnow
from app.models.categories import Category, DocumentType
from app.models.common import DocType
from app.models.providers import Provider, ProviderDocument
from app.provider.acting import Acting
from app.provider.common import categories, own_file
from app.provider.helpers import doc_labels, helper_out
from app.provider.schemas import DocumentIn, DocumentOut, ProfilePatch, ProviderProfile, RenewalOut
from app.repos.categories import DocumentTypes
from app.repos.files import Files
from app.repos.providers import Providers
from app.services.documents import DocumentDateError, due_for_reminder, expiry_for

WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _in_date(d: ProviderDocument, today: date) -> bool:
    return d.status == "verified" and (d.expires_on is None or d.expires_on >= today)


def missing_for_skills(provider: Provider, cats: dict[str, Category], today: date) -> list[DocType]:
    held = {d.type for d in provider.documents if _in_date(d, today)}
    needed: list[DocType] = ["identity"]
    for cid in provider.skills:
        c = cats.get(cid)
        if c and c.status == "live":
            needed += [t for t in c.requires if t not in needed]
    return [t for t in needed if t not in held]


async def _url(db: Db, file_id: str | None) -> str | None:
    if not file_id:
        return None
    f = await Files(db).get(file_id)
    return f.url if f else None


async def documents_out(
    db: Db, docs: list[ProviderDocument], skills: list[str], cats: dict[str, Category]
) -> list[DocumentOut]:
    """One row per document type the person holds or their jobs need, current copy first."""
    today = london_today()
    types = {t.id: t for t in await DocumentTypes(db).all()}
    live = [c for c in cats.values() if c.status == "live"]
    # Identity, and whatever every job needs (public liability insurance), even before any are chosen.
    every_job = [t for t in live[0].requires if all(t in c.requires for c in live)] if live else []
    wanted: list[str] = ["identity", *every_job]
    for cid in skills:
        c = cats.get(cid)
        if c and c.status == "live":
            wanted += [t for t in c.requires if t not in wanted]
    wanted += [d.type for d in docs if d.type not in wanted]
    out: list[DocumentOut] = []
    for t in sorted(wanted, key=lambda x: types[x].sort if x in types else 99):
        dt = types.get(t)
        if dt is None:
            continue
        mine = [d for d in docs if d.type == t]
        current = next((d for d in mine if d.status == "verified"), mine[-1] if mine else None)
        renewal = next((d for d in mine if d is not current and d.status == "pending"), None)
        state = current.status if current else "missing"
        if current and current.status == "verified" and current.expires_on and current.expires_on < today:
            state = "expired"
        needed_by = [cats[c].name for c in skills if c in cats and t in cats[c].requires]
        out.append(
            DocumentOut(
                type=t,  # type: ignore[arg-type]
                label=dt.label,
                status=state,  # type: ignore[arg-type]
                issued_on=current.issued_on if current else None,
                expires_on=current.expires_on if current else None,
                note=(current.note if current else None) or dt.note,
                file_url=await _url(db, current.file_id if current else None),
                expiring_soon=bool(current and due_for_reminder(current, today)),
                days_left=(current.expires_on - today).days if current and current.expires_on else None,
                required_for=needed_by,
                needs_issue_date=bool(dt.valid_months),
                needs_expiry_date=dt.expires and not dt.valid_months,
                renewal=RenewalOut(
                    status=renewal.status,
                    issued_on=renewal.issued_on,
                    expires_on=renewal.expires_on,
                    file_url=await _url(db, renewal.file_id),
                )
                if renewal
                else None,
            )
        )
    return out


async def profile(db: Db, provider: Provider) -> ProviderProfile:
    cats = await categories(db)
    labels = await doc_labels(db)
    acct = provider.payment_account
    return ProviderProfile(
        provider_id=provider.id,
        name=provider.name,
        short=provider.short,
        initials=provider.initials,
        area=provider.home.area,
        district=provider.home.district,
        joined_on=provider.joined_on,
        rating_avg=provider.stats.rating_avg,
        rating_count=provider.stats.rating_count,
        status=provider.status,
        skills=provider.skills,
        documents=await documents_out(db, provider.documents, provider.skills, cats),
        missing_for_skills=missing_for_skills(provider, cats, london_today()),
        travel_radius_miles=provider.travel_radius_miles,
        working_days=provider.working_days,
        alert_settings=provider.alert_settings,
        helpers=[helper_out(h, labels) for h in provider.helpers if h.status != "removed"],
        payment_account_status=acct.status if acct else "none",
        tax_complete=provider.tax.complete,
    )


async def update_profile(db: Db, provider: Provider, body: ProfilePatch) -> ProviderProfile:
    fields: dict = {}
    if body.skills is not None:
        live = {c.id for c in (await categories(db)).values() if c.status == "live"}
        unknown = [s for s in body.skills if s not in live]
        if unknown:
            fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_skill", "One of those jobs isn't one we list.")
        fields["skills"] = list(dict.fromkeys(body.skills))
    if body.travel_radius_miles is not None:
        fields["travel_radius_miles"] = body.travel_radius_miles
    if body.working_days is not None:
        fields["working_days"] = [d for d in WEEK if d in set(body.working_days)]
    if body.alert_settings is not None:
        a = body.alert_settings
        if not (HHMM.match(a.quiet_from) and HHMM.match(a.quiet_to)):
            fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_time", "Quiet hours need times like 20:00.")
        fields["alert_settings"] = a.model_dump()
    updated = await Providers(db).patch(provider.id, fields) if fields else provider
    assert updated is not None
    return await profile(db, updated)


def with_upload(docs: list[ProviderDocument], new: ProviderDocument, today: date) -> list[ProviderDocument]:
    """The document list after an upload: a verified, in-date copy stays (the upload waits
    beside it as its renewal); anything else of that type is replaced by the upload. The upload
    goes first, so an admin checking that type (L3 takes the first of a type) checks it."""
    keep = [d for d in docs if d.type != new.type or _in_date(d, today)]
    return [new, *keep]


async def upload_document(db: Db, a: Acting, body: DocumentIn) -> DocumentOut:
    today = london_today()
    dt: DocumentType | None = await DocumentTypes(db).get(body.type)
    if dt is None:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_document", "We don't ask for that document.")
    await own_file(db, body.file_id, a.user_id, ("document",))
    if body.issued_on and body.issued_on > today:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "issued_in_future", "The issue date can't be in the future.")
    try:
        expires = expiry_for(dt, body.issued_on, body.expires_on)
    except DocumentDateError as e:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "date_needed", f"{e}.")
    if expires is not None and expires < today:
        fail(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "already_expired",
            f"That {dt.label.lower()} has already run out. Please upload a current one.",
        )
    new = ProviderDocument(
        type=body.type,
        status="pending",
        issued_on=body.issued_on if dt.valid_months else None,
        expires_on=expires,
        file_id=body.file_id,
    )
    providers = Providers(db)
    for _ in range(3):  # compare-and-set on updated_at: an admin may verify something at the same moment
        provider = await providers.get(a.provider.id)
        assert provider is not None
        if a.helper:
            helper = next((h for h in provider.helpers if h.user_id == a.user_id), None)
            if helper is None:
                fail(status.HTTP_403_FORBIDDEN, "not_a_helper", "You're no longer on this provider's helper list.")
            docs = with_upload(helper.documents, new, today)
            changes = {"helpers.$.documents": [d.model_dump(mode="python") for d in docs], "updated_at": utcnow()}
            if helper.status == "invited":
                changes["helpers.$.status"] = "checking"
            raw = await providers.coll.find_one_and_update(
                {"_id": provider.id, "updated_at": provider.updated_at, "helpers.user_id": a.user_id},
                {"$set": changes},
            )
            if raw is not None:
                rows = await documents_out(db, docs, provider.skills, await categories(db))
                return next(d for d in rows if d.type == body.type)
        else:
            docs = with_upload(provider.documents, new, today)
            updated = await providers.update(
                provider.id,
                {"documents": [d.model_dump(mode="python") for d in docs]},
                extra_filter={"updated_at": provider.updated_at},
            )
            if updated is not None:
                rows = await documents_out(db, updated.documents, updated.skills, await categories(db))
                return next(d for d in rows if d.type == body.type)
    fail(status.HTTP_409_CONFLICT, "try_again", "Your documents were changing just then. Please try again.")


async def list_documents(db: Db, a: Acting) -> list[DocumentOut]:
    if a.helper:
        helper = next((h for h in a.provider.helpers if h.user_id == a.user_id), None)
        docs = helper.documents if helper else []
        return await documents_out(db, docs, a.provider.skills, await categories(db))
    return await documents_out(db, a.provider.documents, a.provider.skills, await categories(db))
