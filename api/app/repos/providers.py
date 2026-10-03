"""providers and tax_identities. Owner: L2. L3 verifies documents and suspends
providers through set_document and set_status; L1 updates ratings via apply_rating."""

from typing import Any

from fastapi import status

from app.core.db import DbSession
from app.core.errors import fail
from app.core.timeutil import utcnow
from app.models.providers import Provider, ProviderDocument, ProviderStatus, TaxIdentity
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
        more (the provider replaced it since), nothing changes: 409, which undoes L3's transaction."""
        p = await self.get(provider_id, session=session)
        if p is None:
            return None
        same = [d for d in p.documents if d.type == doc.type]
        read = next((d for d in same if d.file_id == doc.file_id), None)
        if same and read is None:
            fail(
                status.HTTP_409_CONFLICT,
                "document_changed",
                "That document has been replaced since you opened it. Have another look.",
            )
        rest = [d for d in same if d is not read]
        if doc.status == "verified":
            rest = [d for d in rest if d.status == "pending"]
        first = {"pending": 0, "verified": 1}
        kept = sorted([*rest, doc], key=lambda d: first.get(d.status, 2))
        docs = [d for d in p.documents if d.type != doc.type] + kept
        return await self.update(
            provider_id, {"documents": [d.model_dump(mode="python") for d in docs]}, session=session
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
