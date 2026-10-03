"""Categories: the grouped list with how many providers can take each, and the record viewer.
Viewing only in the prototype (editing is out of scope)."""

from app.admin.schemas import CategoryAdminRow, CategoryRecord
from app.core.db import Db
from app.core.errors import fail, not_found
from app.core.timeutil import london_today
from app.repos import Categories, DocumentTypes, PricingVersions, Providers
from app.services.eligibility import can_take


async def rows(db: Db) -> list[CategoryAdminRow]:
    labels = {t.id: t.label for t in await DocumentTypes(db).all()}
    providers = await Providers(db).find({"status": {"$in": ["active", "payouts_paused"]}})
    today = london_today()
    return [
        CategoryAdminRow(
            category=c,
            # Providers who could take it today: the skill and every document it needs, checked.
            provider_count=sum(1 for p in providers if can_take(p, c, today).ok),
            extra_documents=[labels.get(d, d) for d in c.requires if d != "insurance"],
        )
        for c in await Categories(db).all()
    ]


async def record(db: Db, category_id: str) -> CategoryRecord:
    cat = await Categories(db).get(category_id)
    if cat is None:
        not_found("That category")
    live = await PricingVersions(db).live()
    if live is None:
        fail(409, "no_live_version", "There's no live pricing version.")
    return CategoryRecord(category=cat, pricing_version=live.version, pricing_params=live.params.get(cat.id, {}))
