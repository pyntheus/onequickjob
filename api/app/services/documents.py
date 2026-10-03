"""Provider documents: when they expire, and the reminder 30 days before.

Rulings after F review: a basic DBS check is valid for 12 months from its issue date
(document_types.valid_months); other documents run to their stated expiry. Every verified
document with an expiry gets the same reminder 30 days before it lapses. An expired document
is not held, so the provider isn't eligible for categories that require it
(services.eligibility.can_take).
"""

from datetime import date, timedelta

from app.core.db import Db
from app.core.timeutil import add_months, london_today
from app.models.categories import DocumentType
from app.models.common import Related
from app.models.providers import Provider, ProviderDocument
from app.repos.categories import Categories, DocumentTypes
from app.repos.providers import Providers
from app.repos.users import Users
from app.services import wording
from app.services.notify import link, notify, recipient_for

REMINDER_DAYS = 30


class DocumentDateError(ValueError):
    pass


def expiry_for(doc_type: DocumentType, issued_on: date | None, expires_on: date | None) -> date | None:
    """The last valid day of a document. L2 calls this on upload, L3 on verification."""
    if doc_type.valid_months:
        if issued_on is None:
            raise DocumentDateError(f"{doc_type.label} needs its issue date")
        return add_months(issued_on, doc_type.valid_months)
    if doc_type.expires and expires_on is None:
        raise DocumentDateError(f"{doc_type.label} needs its expiry date")
    return expires_on if doc_type.expires else None


def due_for_reminder(doc: ProviderDocument, today: date) -> bool:
    return (
        doc.status == "verified"
        and doc.expires_on is not None
        and today <= doc.expires_on <= today + timedelta(days=REMINDER_DAYS)
    )


async def send_expiry_reminders(db: Db, today: date | None = None) -> int:
    """Remind each provider once per expiring document (idempotent per expiry date)."""
    today = today or london_today()
    labels = {t.id: t.label for t in await DocumentTypes(db).all()}
    categories = await Categories(db).live()
    sent = 0
    for provider in await Providers(db).find({"status": {"$in": ["active", "payouts_paused", "suspended"]}}):
        for doc in provider.documents:
            if due_for_reminder(doc, today):
                sent += await _remind(db, provider, doc, labels, categories)
    return sent


async def _remind(db: Db, provider: Provider, doc: ProviderDocument, labels: dict, categories: list) -> int:
    user = await Users(db).get(provider.user_id)
    if user is None or not user.phone:
        return 0
    needing = [c.name.lower() for c in categories if doc.type in c.requires and c.id in provider.skills]
    jobs = (", ".join(needing[:-1]) + " and " + needing[-1] if len(needing) > 1 else needing[0]) if needing else ""
    await notify(
        db,
        "document_expiring",
        to=recipient_for(user),
        data={
            "document": labels.get(doc.type, doc.type).lower(),
            "date": wording.day_text(doc.expires_on),
            "jobs": f"{jobs} jobs" if jobs else "jobs",
            "link": link("/p/me"),
        },
        related=Related(provider_id=provider.id, user_id=user.id),
        idempotency_key=f"doc:{provider.id}:{doc.type}:{doc.expires_on}:{REMINDER_DAYS}d",
    )
    return 1
