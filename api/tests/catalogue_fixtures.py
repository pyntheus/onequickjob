"""Load the seeded catalogue and pricing v1 straight from seed/*.json (no database)."""

import json
from functools import cache

from app.models.categories import Category
from app.seed.paths import SEED_DIR


@cache
def categories() -> dict[str, Category]:
    data = json.loads((SEED_DIR / "catalogue.json").read_text())
    return {c["_id"]: Category.model_validate(c) for c in data["categories"]}


@cache
def pricing_v1_params() -> dict:
    return json.loads((SEED_DIR / "pricing_v1.json").read_text())["params"]
