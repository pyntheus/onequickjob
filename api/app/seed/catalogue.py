"""Load the catalogue (seed/catalogue.json) and pricing version 1 (seed/pricing_v1.json)."""

import json

from app.core.db import Db
from app.core.ids import seed_id
from app.core.timeutil import utcnow
from app.models.categories import Category, CategoryGroup, DocumentType, ExcludedJob
from app.models.pricing_versions import PricingVersion
from app.repos.categories import Categories, CategoryGroups, DocumentTypes, ExcludedJobs
from app.repos.pricing_versions import PricingVersions
from app.seed.paths import SEED_DIR

PRICING_V1_ID = seed_id("pricing_versions:v1")


def read_json(name: str) -> dict:
    return json.loads((SEED_DIR / name).read_text())


async def load_catalogue(db: Db) -> dict[str, Category]:
    """Upsert every group, document type, category and excluded job. Idempotent."""
    data = read_json("catalogue.json")
    for model, repo, key in (
        (CategoryGroup, CategoryGroups(db), "category_groups"),
        (DocumentType, DocumentTypes(db), "document_types"),
        (Category, Categories(db), "categories"),
        (ExcludedJob, ExcludedJobs(db), "excluded_jobs"),
    ):
        for raw in data[key]:
            await repo.replace(model.model_validate(raw), upsert=True)
    return {c.id: c for c in await Categories(db).all()}


async def load_pricing_v1(db: Db) -> PricingVersion:
    """Insert pricing version 1 once. It goes live only if nothing else is live, so re-seeding
    never undoes a version an admin has approved since."""
    repo = PricingVersions(db)
    existing = await repo.get(PRICING_V1_ID)
    if existing:
        return existing
    data = read_json("pricing_v1.json")
    live = await repo.live()
    v1 = PricingVersion(
        id=PRICING_V1_ID,
        version=1,
        status="retired" if live else "live",
        params=data["params"],
        notes=data["notes"],
        created_by="seed",
        created_at=utcnow(),
        approved_by="seed",
        approved_at=utcnow(),
    )
    await repo.insert(v1)
    return v1
