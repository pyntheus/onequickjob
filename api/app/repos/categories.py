"""categories, category_groups, document_types, excluded_jobs: the catalogue. Seeded by F;
owner L3 (viewing only in the prototype). One module because they are read together."""

from app.models.categories import Category, CategoryGroup, DocumentType, ExcludedJob
from app.repos.base import Repo, idx


class Categories(Repo[Category]):
    model = Category
    indexes = [idx("group", "sort"), idx("status")]

    async def live(self) -> list[Category]:
        return await self.find({"status": "live"}, sort=[("sort", 1)])

    async def all(self) -> list[Category]:
        return await self.find({}, sort=[("sort", 1)])


class CategoryGroups(Repo[CategoryGroup]):
    model = CategoryGroup

    async def all(self) -> list[CategoryGroup]:
        return await self.find({}, sort=[("sort", 1)])


class DocumentTypes(Repo[DocumentType]):
    model = DocumentType

    async def all(self) -> list[DocumentType]:
        return await self.find({}, sort=[("sort", 1)])


class ExcludedJobs(Repo[ExcludedJob]):
    model = ExcludedJob

    async def all(self) -> list[ExcludedJob]:
        return await self.find({}, sort=[("sort", 1)])
