"""Providers: the table, a provider's page, document checks, suspension and reminders.

Writes to providers go through the repo functions domain.md lists for L3 (set_document,
set_status; patch for the payment account), each in one transaction with its message and
audit entry.
"""

from datetime import date, timedelta
from typing import Literal

from fastapi import status

from app.adapters.payments.base import PaymentGateway, ProviderRef
from app.admin.overview import attention_for
from app.admin.schemas import (
    AdminDocument,
    AdminHelper,
    InsuranceState,
    NudgeIn,
    OnboardingLinkOut,
    ProviderDetail,
    ProviderRow,
    RecentRating,
)
from app.admin.views import counting_doc, doc_of, doc_state, long_date, renewal_waiting, short_name
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.core.phone import to_national
from app.core.timeutil import london_today, utcnow
from app.models.categories import DocumentType
from app.models.common import Actor, DocType, Related
from app.models.providers import Helper, PaymentAccount, Provider, ProviderDocument, ProviderStatus
from app.models.system import OutboxMessage
from app.repos import (
    AuditLog,
    Categories,
    Customers,
    DocumentTypes,
    Files,
    LedgerEntries,
    Providers,
    Ratings,
    Users,
    Visits,
)
from app.services import documents, lifecycle
from app.services.audit import audit
from app.services.notify import link, notify, recipient_for
from app.shared.schemas import OutboxItem

type Filter = Literal["all", "attention", "signup"]


def insurance_state(p: Provider, today: date) -> InsuranceState:
    """From the copy that counts, so a renewal waiting for a check shows beside an in-date copy
    ("renewal waiting"), not as "missing"; with no checked copy in date, an upload waiting for a
    check shows as "renewal"."""
    doc = counting_doc(p.documents, "insurance")
    state = doc_state(doc, today)
    waiting = any(d.type == "insurance" and d.status == "pending" for d in p.documents)
    if doc is not None and state in ("ok", "warn"):
        return InsuranceState(status=state, expires_on=doc.expires_on, renewal_waiting=waiting)  # type: ignore[arg-type]
    return InsuranceState(status="renewal" if waiting else "missing", expires_on=doc.expires_on if doc else None)


def needs_attention(p: Provider, today: date) -> bool:
    """The prototype's rule: insurance not fine, or HMRC details missing; and a renewal to check."""
    ins = insurance_state(p, today)
    return ins.status != "ok" or ins.renewal_waiting or not p.tax.complete


async def _jobs_30d(db: Db, provider_ids: list[str]) -> dict[str, int]:
    since = (london_today() - timedelta(days=30)).isoformat()
    rows = await (
        await Visits(db).coll.aggregate(
            [
                {
                    "$match": {
                        "status": "finished",
                        "local_date": {"$gte": since},
                        "performer.provider_id": {"$in": provider_ids},
                    }
                },
                {"$group": {"_id": "$performer.provider_id", "n": {"$sum": 1}}},
            ]
        )
    ).to_list()
    return {r["_id"]: r["n"] for r in rows}


def row(p: Provider, today: date, jobs: dict[str, int]) -> ProviderRow:
    return ProviderRow(
        id=p.id,
        name=p.name,
        short=p.short,
        initials=p.initials,
        area=p.home.area,
        district=p.home.district,
        skills=p.skills,
        rating_avg=p.stats.rating_avg,
        rating_count=p.stats.rating_count,
        jobs_30d=jobs.get(p.id, 0),
        accept_rate=p.stats.accept_rate,
        insurance=insurance_state(p, today),
        hmrc_complete=p.tax.complete,
        status=p.status,
    )


async def provider_rows(db: Db, which: Filter) -> list[ProviderRow]:
    today = london_today()
    providers = await Providers(db).find({}, sort=[("name", 1)])
    if which == "attention":
        providers = [p for p in providers if p.status != "signing_up" and needs_attention(p, today)]
    elif which == "signup":
        providers = [p for p in providers if p.status == "signing_up"]
    jobs = await _jobs_30d(db, [p.id for p in providers])
    return [row(p, today, jobs) for p in providers]


async def get_provider(db: Db, provider_id: str, session: DbSession | None = None) -> Provider:
    p = await Providers(db).get(provider_id, session=session)
    if p is None:
        not_found("That provider")
    return p


async def detail(db: Db, provider_id: str) -> ProviderDetail:
    p = await get_provider(db, provider_id)
    today = london_today()
    user = await Users(db).get(p.user_id)
    types = await DocumentTypes(db).all()
    labels = {t.id: t.label for t in types}
    cats = await Categories(db).find({"_id": {"$in": p.skills}})
    needed = {"identity"} | {d for c in cats for d in c.requires}
    file_ids = [d.file_id for d in [*p.documents, *(d for h in p.helpers for d in h.documents)] if d.file_id]
    files = {f.id: f.url for f in await Files(db).find({"_id": {"$in": file_ids}})}
    docs = document_rows(p.documents, types, needed, files)
    ratings = await Ratings(db).find({"provider_id": p.id}, sort=[("created_at", -1)], limit=10)
    customers = {c.id: c.name for c in await Customers(db).find({"_id": {"$in": [r.customer_id for r in ratings]}})}
    account = p.payment_account
    issues = [i.issue for i in attention_for(p, labels | {"insurance": "Insurance"}, today)]
    missing = [labels.get(t, t) for t in sorted(needed) if not held_in_date(p.documents, t, today)]
    if missing:
        issues.append("Not yet checked: " + ", ".join(missing))
    if p.status == "signing_up":
        left = await lifecycle.missing_checks(db, p, today=today)
        if left:
            words = [lifecycle.CHECK_WORDS[c] for c in left]
            issues.append("Becomes active automatically once these are done: " + ", ".join(words))
    helper_users = {u.id: u for u in await Users(db).find({"_id": {"$in": [h.user_id for h in p.helpers]}})}
    jobs = await _jobs_30d(db, [p.id])
    return ProviderDetail(
        **row(p, today, jobs).model_dump(),
        phone=to_national(user.phone) if user and user.phone else None,
        email=user.email if user else None,
        travel_radius_miles=p.travel_radius_miles,
        working_days=list(p.working_days),
        documents=docs,
        ledger=await LedgerEntries(db).find({"provider_id": p.id}, sort=[("occurred_at", -1)], limit=20),
        ratings=[
            RecentRating(
                visit_id=r.visit_id,
                stars=r.stars,
                tags=r.tags,
                customer_name=short_name(customers.get(r.customer_id, "A customer")),
                created_at=r.created_at,
            )
            for r in ratings
        ],
        helpers=[h.name for h in p.helpers if h.status != "removed"],
        helper_checks=[
            AdminHelper(
                user_id=h.user_id,
                name=h.name,
                relationship=h.relationship,
                status=h.status,  # type: ignore[arg-type]
                phone=to_national(u.phone) if (u := helper_users.get(h.user_id)) and u.phone else None,
                documents=document_rows(h.documents, types, needed, files),
                can_mark_ready=h.status != "ready" and held_in_date(h.documents, "identity", today),
            )
            for h in p.helpers
            if h.status != "removed"
        ],
        payout_account_status=account.status if account else "none",
        payout_account_id=account.account_id if account else None,
        payout_account_gateway=account.gateway if account else None,
        status_reason=p.status_reason,
        issues=issues,
    )


def held_in_date(docs: list[ProviderDocument], doc_type: str, today: date) -> bool:
    return doc_state(counting_doc(docs, doc_type), today) in ("ok", "warn")


def document_rows(
    held: list[ProviderDocument], types: list[DocumentType], needed: set[str], files: dict[str, str]
) -> list[AdminDocument]:
    """One row per document type held or needed: the copy to check next (a waiting renewal comes
    first, so Verify checks it), with the checked copy's expiry beside a renewal."""
    rows = []
    for t in types:
        d = next((x for x in held if x.type == t.id), None)
        if d is None and t.id not in needed:
            continue
        current = counting_doc(held, t.id) if d is not None and renewal_waiting(held, t.id) else None
        rows.append(
            AdminDocument(
                type=t.id,  # type: ignore[arg-type]
                label=t.label,
                status=d.status if d else "missing",
                issued_on=d.issued_on if d else None,
                expires_on=d.expires_on if d else None,
                file_url=files.get(d.file_id) if d and d.file_id else None,
                verified_by=d.verified_by if d else None,
                verified_at=d.verified_at if d else None,
                note=d.note if d else None,
                current_expires_on=current.expires_on if current else None,
            )
        )
    return rows


async def _provider_user(db: Db, p: Provider, session: DbSession):
    user = await Users(db).get(p.user_id, session=session)
    if user is None or not user.phone:
        fail(status.HTTP_409_CONFLICT, "no_phone", f"{p.short} has no mobile number on file to text.")
    return user


async def verify_document(
    db: Db,
    s: Settings,
    provider_id: str,
    doc_type: DocType,
    issued_on: date | None,
    expires_on: date | None,
    actor: Actor,
) -> None:
    p = await get_provider(db, provider_id)
    doc = doc_of(p, doc_type)
    if doc is None or doc.status == "missing":
        fail(status.HTTP_404_NOT_FOUND, "no_document", f"{p.short} hasn't uploaded that document yet.")
    dt = await DocumentTypes(db).get(doc_type)
    assert dt is not None
    issued = issued_on or doc.issued_on
    try:
        # A basic DBS check: 12 months from its issue date (A3). Others: their stated expiry.
        expiry = documents.expiry_for(dt, issued, expires_on or doc.expires_on)
    except documents.DocumentDateError as e:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "dates_needed", f"{e}.")
    if expiry is not None and expiry < london_today():
        fail(status.HTTP_409_CONFLICT, "expired", f"That {dt.label.lower()} ran out on {long_date(expiry)}.")
    checked = doc.model_copy(
        update={
            "status": "verified",
            "issued_on": issued,
            "expires_on": expiry,
            "verified_by": actor.user_id,
            "verified_at": utcnow(),
            "note": None,
        }
    )

    async def apply(session: DbSession) -> None:
        await Providers(db).set_document(p.id, checked, session=session)
        user = await Users(db).get(p.user_id, session=session)
        if user and user.phone:
            await notify(
                db,
                "document_verified",
                to=recipient_for(user),
                data={
                    "document": dt.label[:1].lower() + dt.label[1:],
                    "until_text": f" until {long_date(expiry)}" if expiry else "",
                },
                related=Related(provider_id=p.id, user_id=user.id),
                settings=s,
                session=session,
            )
        await audit(
            db,
            actor,
            "provider.document_verified",
            Related(provider_id=p.id),
            before=doc.model_dump(mode="json"),
            after=checked.model_dump(mode="json"),
            session=session,
        )
        await lifecycle.activate_if_ready(db, s, p.id, actor=actor, session=session)

    await transaction(db, apply)


def sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


async def reject_document(db: Db, s: Settings, provider_id: str, doc_type: DocType, reason: str, actor: Actor) -> None:
    p = await get_provider(db, provider_id)
    doc = doc_of(p, doc_type)
    if doc is None or doc.status == "missing":
        fail(status.HTTP_404_NOT_FOUND, "no_document", f"{p.short} hasn't uploaded that document yet.")
    dt = await DocumentTypes(db).get(doc_type)
    assert dt is not None
    rejected = doc.model_copy(update={"status": "rejected", "note": reason, "verified_by": None, "verified_at": None})

    async def apply(session: DbSession) -> None:
        await Providers(db).set_document(p.id, rejected, session=session)
        user = await Users(db).get(p.user_id, session=session)
        if user and user.phone:
            await notify(
                db,
                "document_rejected",
                to=recipient_for(user),
                data={
                    "document": dt.label[:1].lower() + dt.label[1:],
                    "reason": sentence(reason),
                    "link": link("/p/me", s),
                },
                related=Related(provider_id=p.id, user_id=user.id),
                settings=s,
                session=session,
            )
        await audit(
            db,
            actor,
            "provider.document_rejected",
            Related(provider_id=p.id),
            before=doc.model_dump(mode="json"),
            after=rejected.model_dump(mode="json"),
            note=reason,
            session=session,
        )

    await transaction(db, apply)


# ------------------------------------------------------------------ helpers' checks (Session S)


def _helper(p: Provider, user_id: str) -> Helper:
    helper = next((h for h in p.helpers if h.user_id == user_id and h.status != "removed"), None)
    if helper is None:
        not_found("That helper")
    return helper


async def _helper_doc(db: Db, helper: Helper, doc_type: DocType) -> tuple[ProviderDocument, DocumentType]:
    doc = next((d for d in helper.documents if d.type == doc_type), None)  # the copy to check next
    if doc is None or doc.status == "missing":
        fail(
            status.HTTP_404_NOT_FOUND, "no_document", f"{helper.name.split(' ')[0]} hasn't uploaded that document yet."
        )
    dt = await DocumentTypes(db).get(doc_type)
    assert dt is not None
    return doc, dt


async def _text_helper(db: Db, s: Settings, p: Provider, helper: Helper, template: str, data: dict, session) -> None:
    user = await Users(db).get(helper.user_id, session=session)
    if user and user.phone:
        await notify(
            db,
            template,
            to=recipient_for(user),
            data=data,
            related=Related(provider_id=p.id, user_id=user.id),
            settings=s,
            session=session,
        )


async def verify_helper_document(
    db: Db,
    s: Settings,
    provider_id: str,
    user_id: str,
    doc_type: DocType,
    issued_on: date | None,
    expires_on: date | None,
    actor: Actor,
) -> None:
    """A helper's document, checked as a provider's is (services.documents.expiry_for); the helper
    is texted. Marking them ready is a separate step (mark_helper_ready)."""
    p = await get_provider(db, provider_id)
    helper = _helper(p, user_id)
    doc, dt = await _helper_doc(db, helper, doc_type)
    issued = issued_on or doc.issued_on
    try:
        expiry = documents.expiry_for(dt, issued, expires_on or doc.expires_on)
    except documents.DocumentDateError as e:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "dates_needed", f"{e}.")
    if expiry is not None and expiry < london_today():
        fail(status.HTTP_409_CONFLICT, "expired", f"That {dt.label.lower()} ran out on {long_date(expiry)}.")
    checked = doc.model_copy(
        update={
            "status": "verified",
            "issued_on": issued,
            "expires_on": expiry,
            "verified_by": actor.user_id,
            "verified_at": utcnow(),
            "note": None,
        }
    )

    async def apply(session: DbSession) -> None:
        if await Providers(db).set_helper_document(p.id, helper.user_id, checked, session=session) is None:
            fail(status.HTTP_409_CONFLICT, "helper_changed", "This helper has just changed. Have another look.")
        data = {
            "document": dt.label[:1].lower() + dt.label[1:],
            "until_text": f" until {long_date(expiry)}" if expiry else "",
        }
        await _text_helper(db, s, p, helper, "document_verified", data, session)
        await audit(
            db,
            actor,
            "provider.helper_document_verified",
            Related(provider_id=p.id, user_id=helper.user_id),
            before=doc.model_dump(mode="json"),
            after=checked.model_dump(mode="json"),
            session=session,
        )

    await transaction(db, apply)


async def reject_helper_document(
    db: Db, s: Settings, provider_id: str, user_id: str, doc_type: DocType, reason: str, actor: Actor
) -> None:
    p = await get_provider(db, provider_id)
    helper = _helper(p, user_id)
    doc, dt = await _helper_doc(db, helper, doc_type)
    rejected = doc.model_copy(update={"status": "rejected", "note": reason, "verified_by": None, "verified_at": None})

    async def apply(session: DbSession) -> None:
        if await Providers(db).set_helper_document(p.id, helper.user_id, rejected, session=session) is None:
            fail(status.HTTP_409_CONFLICT, "helper_changed", "This helper has just changed. Have another look.")
        data = {
            "document": dt.label[:1].lower() + dt.label[1:],
            "reason": sentence(reason),
            "link": link("/p/me", s),
        }
        await _text_helper(db, s, p, helper, "document_rejected", data, session)
        await audit(
            db,
            actor,
            "provider.helper_document_rejected",
            Related(provider_id=p.id, user_id=helper.user_id),
            before=doc.model_dump(mode="json"),
            after=rejected.model_dump(mode="json"),
            note=reason,
            session=session,
        )

    await transaction(db, apply)


async def mark_helper_ready(db: Db, s: Settings, provider_id: str, user_id: str, actor: Actor) -> None:
    """The helper can be sent to visits (each still needs the documents its job needs:
    app.provider.helpers.ready_helper). Their ID must have been checked. The provider is texted."""
    p = await get_provider(db, provider_id)
    helper = _helper(p, user_id)
    if helper.status == "ready":
        fail(status.HTTP_409_CONFLICT, "already_ready", f"{helper.name} is already ready.")
    if not held_in_date(helper.documents, "identity", london_today()):
        fail(status.HTTP_409_CONFLICT, "identity_not_checked", f"Check {helper.name.split(' ')[0]}'s ID first.")

    async def apply(session: DbSession) -> None:
        ready = await Providers(db).set_helper_status(
            p.id, helper.user_id, "ready", expect=(helper.status,), session=session
        )
        if ready is None:
            fail(status.HTTP_409_CONFLICT, "helper_changed", "This helper has just changed. Have another look.")
        boss = await Users(db).get(p.user_id, session=session)
        if boss and boss.phone:
            await notify(
                db,
                "helper_ready",
                to=recipient_for(boss),
                data={"helper": helper.name.split(" ")[0], "link": link("/p/today", s)},
                related=Related(provider_id=p.id, user_id=helper.user_id),
                idempotency_key=f"helper:{p.id}:{helper.user_id}:ready",
                settings=s,
                session=session,
            )
        await audit(
            db,
            actor,
            "provider.helper_ready",
            Related(provider_id=p.id, user_id=helper.user_id),
            before={"status": helper.status},
            after={"status": "ready"},
            session=session,
        )

    await transaction(db, apply)


async def suspend(db: Db, s: Settings, provider_id: str, reason: str, actor: Actor) -> None:
    """Suspended providers can't take jobs (eligibility) but can still sign in to see their
    earnings and records. Bookings they already have aren't moved automatically."""
    p = await get_provider(db, provider_id)
    if p.status == "suspended":
        fail(status.HTTP_409_CONFLICT, "already_suspended", f"{p.short} is already suspended.")

    async def apply(session: DbSession) -> None:
        if (
            await Providers(db).update(
                p.id,
                {"status": "suspended", "status_reason": reason},
                extra_filter={"status": p.status},
                session=session,
            )
            is None
        ):
            fail(status.HTTP_409_CONFLICT, "provider_changed", "This provider has just changed. Have another look.")
        user = await Users(db).get(p.user_id, session=session)
        if user and user.phone:
            await notify(
                db,
                "account_suspended",
                to=recipient_for(user),
                data={"reason": sentence(reason)},
                related=Related(provider_id=p.id, user_id=user.id),
                settings=s,
                session=session,
            )
        await audit(
            db,
            actor,
            "provider.suspended",
            Related(provider_id=p.id),
            before={"status": p.status},
            after={"status": "suspended", "reason": reason},
            note=reason,
            session=session,
        )

    await transaction(db, apply)


async def reinstate(db: Db, s: Settings, provider_id: str, actor: Actor) -> None:
    """Back to the status they had before the suspension (from its audit entry)."""
    p = await get_provider(db, provider_id)
    if p.status != "suspended":
        fail(status.HTTP_409_CONFLICT, "not_suspended", f"{p.short} isn't suspended.")
    last = await AuditLog(db).find_one({"action": "provider.suspended", "target.provider_id": p.id}, sort=[("at", -1)])
    previous: ProviderStatus = (last.before or {}).get("status", "active") if last else "active"  # type: ignore[assignment]
    if previous == "suspended":
        previous = "active"

    async def apply(session: DbSession) -> None:
        if (
            await Providers(db).update(
                p.id, {"status": previous, "status_reason": None}, extra_filter={"status": "suspended"}, session=session
            )
            is None
        ):
            fail(status.HTTP_409_CONFLICT, "provider_changed", "This provider has just changed. Have another look.")
        user = await Users(db).get(p.user_id, session=session)
        if user and user.phone:
            await notify(
                db,
                "account_reinstated",
                to=recipient_for(user),
                data={},
                related=Related(provider_id=p.id, user_id=user.id),
                settings=s,
                session=session,
            )
        await audit(
            db,
            actor,
            "provider.reinstated",
            Related(provider_id=p.id),
            before={"status": "suspended", "reason": p.status_reason},
            after={"status": previous},
            session=session,
        )

    await transaction(db, apply)


async def _nudge_message(db: Db, p: Provider, body: NudgeIn) -> tuple[str, str]:
    """(message, link path) for a reminder; the admin's note replaces the standard words."""
    if body.kind == "tax_details":
        default = (
            "we still need your tax details (National Insurance number and date of birth) before we can pay "
            "you. It takes two minutes:"
        )
        path = "/p/signup"
    elif body.kind == "signup_help":
        default = "you're nearly set up. If anything's holding you up, reply to this text and we'll help:"
        path = "/p/signup"
    else:
        labels = {t.id: t.label for t in await DocumentTypes(db).all()}
        today = london_today()
        urgent = sorted(
            (d for d in p.documents if doc_state(d, today) in ("warn", "expired") and d.expires_on),
            key=lambda d: d.expires_on or today,
        )
        if urgent:
            d = urgent[0]
            label = labels.get(d.type, d.type)
            label = label[:1].lower() + label[1:]
            verb = "runs out" if doc_state(d, today) == "warn" else "ran out"
            default = (
                f"your {label} {verb} on {long_date(d.expires_on)}. Please upload the new one so jobs keep coming:"  # type: ignore[arg-type]
            )
        else:
            default = "please upload your insurance certificate so jobs keep coming:"
        path = "/p/me"
    return (body.note.strip() or default), path


async def nudge(db: Db, s: Settings, provider_id: str, body: NudgeIn, actor: Actor) -> OutboxItem:
    p = await get_provider(db, provider_id)
    message, path = await _nudge_message(db, p, body)

    async def apply(session: DbSession) -> OutboxMessage:
        user = await _provider_user(db, p, session)
        msg = await notify(
            db,
            "provider_nudge",
            to=recipient_for(user),
            data={"message": message, "link": link(path, s)},
            related=Related(provider_id=p.id, user_id=user.id),
            settings=s,
            session=session,
        )
        await audit(
            db,
            actor,
            "provider.nudged",
            Related(provider_id=p.id),
            after={"kind": body.kind},
            note=message,
            session=session,
        )
        return msg

    msg = await transaction(db, apply)
    return OutboxItem(
        id=msg.id,
        channel=msg.channel,
        recipient=msg.recipient,
        template_id=msg.template_id,
        subject=msg.subject,
        body=msg.body,
        related=msg.related,
        created_at=msg.created_at,
        not_before=msg.not_before,
    )


async def payment_account_link(
    db: Db, s: Settings, gateway: PaymentGateway, provider_id: str, actor: Actor
) -> OnboardingLinkOut:
    """Create the provider's connected account if they have none with this gateway, and return
    the gateway's hosted onboarding link (Stripe: Express onboarding; test values in payments.md)."""
    p = await get_provider(db, provider_id)
    account = p.payment_account
    if account is None or account.gateway != gateway.name:
        user = await Users(db).get(p.user_id)
        created = await gateway.create_provider_account(
            ProviderRef(
                provider_id=p.id, name=p.name, email=user.email if user else None, phone=user.phone if user else None
            )
        )
        account = PaymentAccount(
            gateway=gateway.name,
            account_id=created.account_id,
            status=created.status,
            payouts_enabled=created.payouts_enabled,
            bank_last4=created.bank_last4,
        )

        async def save(session: DbSession) -> None:
            await Providers(db).patch(p.id, {"payment_account": account.model_dump(mode="python")}, session=session)
            await audit(
                db,
                actor,
                "provider.payment_account_created",
                Related(provider_id=p.id),
                before=p.payment_account.model_dump(mode="json") if p.payment_account else None,
                after=account.model_dump(mode="json"),
                session=session,
            )
            await lifecycle.activate_if_ready(db, s, p.id, actor=actor, session=session)

        await transaction(db, save)
    back = f"/admin/providers/{p.id}"
    url = await gateway.onboarding_link(
        account.account_id,
        return_url=link(f"{back}?onboarding=done", s),
        refresh_url=link(f"{back}?onboarding=again", s),
    )
    return OnboardingLinkOut(account_id=account.account_id, url=url, status=account.status)


async def sync_payment_account(db: Db, s: Settings, gateway: PaymentGateway, provider_id: str, actor: Actor) -> None:
    p = await get_provider(db, provider_id)
    if p.payment_account is None or p.payment_account.gateway != gateway.name:
        fail(status.HTTP_409_CONFLICT, "no_account", f"{p.short} has no {gateway.name} payment account yet.")
    state = await gateway.account_status(p.payment_account.account_id)
    after = p.payment_account.model_copy(
        update={
            "status": state.status,
            "payouts_enabled": state.payouts_enabled,
            "bank_last4": state.bank_last4 or p.payment_account.bank_last4,
        }
    )
    if after == p.payment_account:
        return

    async def save(session: DbSession) -> None:
        await Providers(db).patch(p.id, {"payment_account": after.model_dump(mode="python")}, session=session)
        await audit(
            db,
            actor,
            "provider.payment_account_synced",
            Related(provider_id=p.id),
            before=p.payment_account.model_dump(mode="json") if p.payment_account else None,
            after=after.model_dump(mode="json"),
            session=session,
        )
        await lifecycle.activate_if_ready(db, s, p.id, actor=actor, session=session)

    await transaction(db, save)
