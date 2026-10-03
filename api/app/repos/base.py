"""A thin typed repository over one collection. No ODM: Pydantic in, Pydantic out.

Each collection module subclasses Repo, sets `model` and `indexes`, and adds the
queries its callers need. Lanes needing a new read-only query on a collection they
don't own may write it in their own package using `repo.coll` (see lanes.md).

Every method takes an optional `session`: pass the open transaction's session when the call
is part of a write spanning several collections (CLAUDE.md, "Writing to several
collections"). Helpers that use `self.coll` directly pass `session=self.s(session)`.
"""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pymongo import ASCENDING, IndexModel, ReturnDocument
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.db import DbSession, check_session
from app.core.timeutil import utcnow
from app.models.common import Doc

type Filter = Mapping[str, Any]
type Sort = Sequence[tuple[str, int]]


class Repo[T: Doc]:
    model: ClassVar[type[Doc]]
    indexes: ClassVar[list[IndexModel]] = []
    touch_updated_at: ClassVar[bool] = True

    def __init__(self, db: AsyncDatabase):
        self.db = db
        self.coll: AsyncCollection = db[self.model.COLLECTION]

    @staticmethod
    def s(session: DbSession | None) -> DbSession | None:
        """The session to hand to the driver (checked: see app.core.db.check_session)."""
        return check_session(session)

    def _load(self, raw: Mapping[str, Any] | None) -> T | None:
        return None if raw is None else self.model.model_validate(raw)  # type: ignore[return-value]

    async def get(self, id_: str, *, session: DbSession | None = None) -> T | None:
        return self._load(await self.coll.find_one({"_id": id_}, session=self.s(session)))

    async def find_one(self, flt: Filter, sort: Sort | None = None, *, session: DbSession | None = None) -> T | None:
        return self._load(await self.coll.find_one(flt, sort=list(sort) if sort else None, session=self.s(session)))

    async def find(
        self,
        flt: Filter | None = None,
        *,
        sort: Sort | None = None,
        limit: int = 0,
        skip: int = 0,
        session: DbSession | None = None,
    ) -> list[T]:
        cursor = self.coll.find(
            flt or {}, sort=list(sort) if sort else None, limit=limit, skip=skip, session=self.s(session)
        )
        return [self._load(raw) async for raw in cursor]  # type: ignore[misc]

    async def count(self, flt: Filter | None = None, *, session: DbSession | None = None) -> int:
        return await self.coll.count_documents(flt or {}, session=self.s(session))

    async def insert(self, doc: T, *, session: DbSession | None = None) -> T:
        await self.coll.insert_one(doc.to_mongo(), session=self.s(session))
        return doc

    async def insert_once(self, doc: T, key: Filter, *, session: DbSession | None = None) -> T:
        """Insert doc unless a document matching key (a unique index's fields) is already
        stored, and return whichever is stored. Safe concurrently and inside a transaction:
        it's an upsert, so there's no duplicate-key error to catch (one would abort the
        transaction; a concurrent transaction's insert is a write conflict, which the driver
        retries)."""
        try:
            raw = await self.coll.find_one_and_update(
                dict(key),
                {"$setOnInsert": doc.to_mongo()},
                upsert=True,
                return_document=ReturnDocument.AFTER,
                session=self.s(session),
            )
        except DuplicateKeyError:
            if session is not None:
                raise
            raw = await self.coll.find_one(dict(key))  # a concurrent upsert won the race
        return self._load(raw)  # type: ignore[return-value]

    async def replace(self, doc: T, *, upsert: bool = False, session: DbSession | None = None) -> T:
        await self.coll.replace_one({"_id": doc.id}, doc.to_mongo(), upsert=upsert, session=self.s(session))
        return doc

    async def update(
        self,
        id_: str,
        set_: Mapping[str, Any],
        *,
        extra_filter: Filter | None = None,
        push: Mapping[str, Any] | None = None,
        session: DbSession | None = None,
    ) -> T | None:
        """$set (and optionally $push) on one document, returning it afterwards, or None if
        the filter didn't match. extra_filter makes it a guarded (compare-and-set) update."""
        fields = dict(set_)
        if self.touch_updated_at:
            fields.setdefault("updated_at", utcnow())
        update: dict[str, Any] = {"$set": fields} if fields else {}
        if push:
            update["$push"] = dict(push)
        if not update:
            return await self.get(id_, session=session)
        raw = await self.coll.find_one_and_update(
            {"_id": id_, **(extra_filter or {})},
            update,
            return_document=ReturnDocument.AFTER,
            session=self.s(session),
        )
        return self._load(raw)

    async def find_one_and_update(
        self, flt: Filter, update: Mapping[str, Any], *, sort: Sort | None = None, session: DbSession | None = None
    ) -> T | None:
        """Atomic conditional update of a single document; returns it after the update."""
        raw = await self.coll.find_one_and_update(
            flt,
            dict(update),
            sort=list(sort) if sort else None,
            return_document=ReturnDocument.AFTER,
            session=self.s(session),
        )
        return self._load(raw)

    async def delete(self, id_: str, *, session: DbSession | None = None) -> bool:
        return (await self.coll.delete_one({"_id": id_}, session=self.s(session))).deleted_count == 1


def idx(*keys: str | tuple[str, int], **kwargs: Any) -> IndexModel:
    spec = [(k, ASCENDING) if isinstance(k, str) else k for k in keys]
    return IndexModel(spec, **kwargs)
