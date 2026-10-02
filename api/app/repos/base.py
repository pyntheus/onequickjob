"""A thin typed repository over one collection. No ODM: Pydantic in, Pydantic out.

Each collection module subclasses Repo, sets `model` and `indexes`, and adds the
queries its callers need. Lanes needing a new read-only query on a collection they
don't own may write it in their own package using `repo.coll` (see lanes.md).
"""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pymongo import ASCENDING, IndexModel, ReturnDocument
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

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

    def _load(self, raw: Mapping[str, Any] | None) -> T | None:
        return None if raw is None else self.model.model_validate(raw)  # type: ignore[return-value]

    async def get(self, id_: str) -> T | None:
        return self._load(await self.coll.find_one({"_id": id_}))

    async def find_one(self, flt: Filter, sort: Sort | None = None) -> T | None:
        return self._load(await self.coll.find_one(flt, sort=list(sort) if sort else None))

    async def find(
        self, flt: Filter | None = None, *, sort: Sort | None = None, limit: int = 0, skip: int = 0
    ) -> list[T]:
        cursor = self.coll.find(flt or {}, sort=list(sort) if sort else None, limit=limit, skip=skip)
        return [self._load(raw) async for raw in cursor]  # type: ignore[misc]

    async def count(self, flt: Filter | None = None) -> int:
        return await self.coll.count_documents(flt or {})

    async def insert(self, doc: T) -> T:
        await self.coll.insert_one(doc.to_mongo())
        return doc

    async def replace(self, doc: T, *, upsert: bool = False) -> T:
        await self.coll.replace_one({"_id": doc.id}, doc.to_mongo(), upsert=upsert)
        return doc

    async def update(
        self,
        id_: str,
        set_: Mapping[str, Any],
        *,
        extra_filter: Filter | None = None,
        push: Mapping[str, Any] | None = None,
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
            return await self.get(id_)
        raw = await self.coll.find_one_and_update(
            {"_id": id_, **(extra_filter or {})}, update, return_document=ReturnDocument.AFTER
        )
        return self._load(raw)

    async def find_one_and_update(
        self, flt: Filter, update: Mapping[str, Any], *, sort: Sort | None = None
    ) -> T | None:
        """Atomic conditional update of a single document; returns it after the update."""
        raw = await self.coll.find_one_and_update(
            flt, dict(update), sort=list(sort) if sort else None, return_document=ReturnDocument.AFTER
        )
        return self._load(raw)

    async def delete(self, id_: str) -> bool:
        return (await self.coll.delete_one({"_id": id_})).deleted_count == 1


def idx(*keys: str | tuple[str, int], **kwargs: Any) -> IndexModel:
    spec = [(k, ASCENDING) if isinstance(k, str) else k for k in keys]
    return IndexModel(spec, **kwargs)
