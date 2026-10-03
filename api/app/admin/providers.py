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
    InsuranceState,
    NudgeIn,
    OnboardingLinkOut,
    ProviderDetail,
    ProviderRow,
    RecentRating,
)
from app.admin.views import doc_of, doc_state, long_date, short_name
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.core.phone import to_national
from app.core.timeutil import london_today, utcnow
from app.models.common import Actor, DocType, Related
from app.models.providers import PaymentAccount, Provider, ProviderStatus
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
from app.services import documents
from app.services.audit import audit
from app.services.notify import link, notify, recipient_for
from app.shared.schemas import OutboxItem

type Filter = Literal["all", "attention", "signup"]


def insurance_state(p: Provider, today: date) -> InsuranceState:
    doc = doc_of(p, "insurance")
    state = doc_state(doc, today)
    return InsuranceState(
        status="ok" if state == "ok" else "warn" if state == "warn" else "missing",
        expires_on=doc.expires_on if doc else None,
    )


def needs_attention(p: Provider, today: date) -> bool:
    """The prototype's rule: insurance not fine, or HMRC details missing."""
    return insurance_state(p, today).status != "ok" or not p.tax.complete


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
    needed = {"identity"} | {d for c in await Categories(db).find({"_id": {"$in": p.skills}}) for d in c.requires}
    files = {f.id: f.url for f in await Files(db).find({"_id": {"$in": [d.file_id for d in p.documents if d.file_id]}})}
    docs = []
    for t in types:
        d = doc_of(p, t.id)
        if d is None and t.id not in needed:
            continue
        docs.append(
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
            )
        )
    ratings = await Ratings(db).find({"provider_id": p.id}, sort=[("created_at", -1)], limit=10)
    customers = {c.id: c.name for c in await Customers(db).find({"_id": {"$in": [r.customer_id for r in ratings]}})}
    account = p.payment_account
    issues = [i.issue for i in attention_for(p, labels | {"insurance": "Insurance"}, today)]
    missing = [labels.get(t, t) for t in sorted(needed) if doc_state(doc_of(p, t), today) in ("missing", "expired")]
    if missing:
        issues.append("Not yet checked: " + ", ".join(missing))
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
        payout_account_status=account.status if account else "none",
        payout_account_id=account.account_id if account else None,
        payout_account_gateway=account.gateway if account else None,
        status_reason=p.status_reason,
        issues=issues,
    )


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

        await transaction(db, save)
    back = f"/admin/providers/{p.id}"
    url = await gateway.onboarding_link(
        account.account_id,
        return_url=link(f"{back}?onboarding=done", s),
        refresh_url=link(f"{back}?onboarding=again", s),
    )
    return OnboardingLinkOut(account_id=account.account_id, url=url, status=account.status)


async def sync_payment_account(db: Db, gateway: PaymentGateway, provider_id: str, actor: Actor) -> None:
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

    await transaction(db, save)
