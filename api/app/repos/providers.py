"""providers and tax_identities. Owner: L2. L3 verifies documents (a provider's and their
helpers') and suspends providers through set_document, set_helper_document, set_helper_status and
set_status; L1 updates ratings via apply_rating."""

from typing import Any

from app.core.db import DbSession
from app.core.errors import Conflict
from app.core.timeutil import utcnow
from app.models.providers import HelperStatus, Provider, ProviderDocument, ProviderStatus, TaxIdentity
from app.repos.base import Repo, idx


class Providers(Repo[Provider]):
    model = Provider
    indexes = [idx("user_id", unique=True), idx("skills"), idx("status"), idx("home.district")]

    async def by_user(self, user_id: str, *, session: DbSession | None = None) -> Provider | None:
        return await self.find_one({"user_id": user_id}, session=session)

    async def with_skill(
        self,
        category_id: str,
        statuses: tuple[ProviderStatus, ...] = ("active", "payouts_paused"),
        *,
        session: DbSession | None = None,
    ) -> list[Provider]:
        return await self.find({"skills": category_id, "status": {"$in": list(statuses)}}, session=session)

    async def set_document(
        self, provider_id: str, doc: ProviderDocument, *, session: DbSession | None = None
    ) -> Provider | None:
        """L3's verdict on one of the provider's documents: doc is the copy L3 read (verify or
        reject), changed. It replaces that copy (the one with the same file). A verified copy also
        supersedes the type's other checked or rejected copies, so a checked renewal replaces the
        old copy, while a newer upload still waiting stays; a rejected one replaces only itself, so
        rejecting a renewal leaves the verified copy counting. Waiting copies come first (L3 checks
        the first of a type), then the one that counts. If the copy L3 read isn't on record any
        more (the provider replaced it since), nothing changes: it raises Conflict document_changed,
        which undoes L3's transaction and answers 409."""
        p = await self.get(provider_id, session=session)
        if p is None:
            return None
        docs = with_verdict(p.documents, doc)
        return await self.update(
            provider_id, {"documents": [d.model_dump(mode="python") for d in docs]}, session=session
        )

    async def set_helper_document(
        self, provider_id: str, user_id: str, doc: ProviderDocument, *, session: DbSession | None = None
    ) -> Provider | None:
        """L3's verdict on one of a helper's documents (Provider.helpers[].documents), by the same rule
        as set_document. None if the provider doesn't list that helper (or has removed them)."""
        p = await self.get(provider_id, session=session)
        helper = next((h for h in p.helpers if h.user_id == user_id and h.status != "removed"), None) if p else None
        if helper is None:
            return None
        docs = with_verdict(helper.documents, doc)
        return await self.find_one_and_update(
            {"_id": provider_id, "helpers": {"$elemMatch": {"user_id": user_id, "status": helper.status}}},
            {
                "$set": {
                    "helpers.$.documents": [d.model_dump(mode="python") for d in docs],
                    "updated_at": utcnow(),
                }
            },
            session=session,
        )

    async def set_helper_status(
        self,
        provider_id: str,
        user_id: str,
        status: HelperStatus,
        *,
        expect: tuple[HelperStatus, ...],
        session: DbSession | None = None,
    ) -> Provider | None:
        """L3 marks a helper ready (guarded on the statuses it expects them to be in). None if the
        helper isn't listed in one of those statuses."""
        return await self.find_one_and_update(
            {"_id": provider_id, "helpers": {"$elemMatch": {"user_id": user_id, "status": {"$in": list(expect)}}}},
            {"$set": {"helpers.$.status": status, "updated_at": utcnow()}},
            session=session,
        )

    async def set_status(
        self, provider_id: str, status: ProviderStatus, reason: str | None = None, *, session: DbSession | None = None
    ) -> Provider | None:
        return await self.update(provider_id, {"status": status, "status_reason": reason}, session=session)

    async def apply_rating(self, provider_id: str, stars: int, *, session: DbSession | None = None) -> Provider | None:
        """Fold one new rating into the running average."""
        p = await self.get(provider_id, session=session)
        if p is None:
            return None
        n = p.stats.rating_count
        avg = ((p.stats.rating_avg or 0) * n + stars) / (n + 1)
        return await self.update(
            provider_id, {"stats.rating_avg": round(avg, 2), "stats.rating_count": n + 1}, session=session
        )

    async def patch(
        self, provider_id: str, fields: dict[str, Any], *, session: DbSession | None = None
    ) -> Provider | None:
        return await self.update(provider_id, fields, session=session)


def with_verdict(documents: list[ProviderDocument], doc: ProviderDocument) -> list[ProviderDocument]:
    """The document list after a verdict on doc (the copy L3 read, found by its file): see
    Providers.set_document. Raises Conflict document_changed if that copy isn't there any more."""
    same = [d for d in documents if d.type == doc.type]
    read = next((d for d in same if d.file_id == doc.file_id), None)
    if same and read is None:
        raise Conflict("document_changed", "That document has been replaced since you opened it. Have another look.")
    rest = [d for d in same if d is not read]
    if doc.status == "verified":
        rest = [d for d in rest if d.status == "pending"]
    first = {"pending": 0, "verified": 1}
    kept = sorted([*rest, doc], key=lambda d: first.get(d.status, 2))
    return [d for d in documents if d.type != doc.type] + kept


class TaxIdentities(Repo[TaxIdentity]):
    model = TaxIdentity
    touch_updated_at = False
    indexes = [idx("provider_id", unique=True)]

    async def upsert(
        self, provider_id: str, ni_sealed: str, dob_sealed: str, *, session: DbSession | None = None
    ) -> None:
        await self.coll.update_one(
            {"provider_id": provider_id},
            {
                "$set": {"ni_number_sealed": ni_sealed, "dob_sealed": dob_sealed, "updated_at": utcnow()},
                "$setOnInsert": {"_id": provider_id},
            },
            upsert=True,
            session=self.s(session),
        )
