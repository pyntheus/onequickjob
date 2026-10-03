"""categories, category_groups, document_types, excluded_jobs: the catalogue. Seeded by F;
owner L3 (viewing only in the prototype). One module because they are read together."""

from app.core.db import DbSession
from app.models.categories import Category, CategoryGroup, DocumentType, ExcludedJob
from app.repos.base import Repo, idx


class Categories(Repo[Category]):
    model = Category
    indexes = [idx("group", "sort"), idx("status")]

    async def live(self, *, session: DbSession | None = None) -> list[Category]:
        return await self.find({"status": "live"}, sort=[("sort", 1)], session=session)

    async def all(self, *, session: DbSession | None = None) -> list[Category]:
        return await self.find({}, sort=[("sort", 1)], session=session)


class CategoryGroups(Repo[CategoryGroup]):
    model = CategoryGroup

    async def all(self, *, session: DbSession | None = None) -> list[CategoryGroup]:
        return await self.find({}, sort=[("sort", 1)], session=session)


class DocumentTypes(Repo[DocumentType]):
    model = DocumentType

    async def all(self, *, session: DbSession | None = None) -> list[DocumentType]:
        return await self.find({}, sort=[("sort", 1)], session=session)


class ExcludedJobs(Repo[ExcludedJob]):
    model = ExcludedJob

    async def all(self, *, session: DbSession | None = None) -> list[ExcludedJob]:
        return await self.find({}, sort=[("sort", 1)], session=session)
