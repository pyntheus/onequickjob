"""categories, category_groups, document_types, excluded_jobs: the catalogue as data.

Ported from CATEGORIES, GROUPS, DOCS and EXCLUDED in the prototype (seed/catalogue.json).
Adding a job type means adding a record; only a new way of pricing needs code
(a function in app/pricing/models.py). Pricing params are not here: they live in the
live pricing version, keyed by category id.
"""

from typing import Any, ClassVar, Literal

from pydantic import Field

from app.models.common import Doc, DocType, Model

IntakeType = Literal["choice", "chips", "multi", "number", "counts", "text", "photos"]


class IntakeOption(Model):
    value: str
    label: str
    hint: str | None = None


class CountItem(Model):
    key: str
    label: str
    hint: str | None = None


class IntakeField(Model):
    """One question in the quote flow, rendered generically by the web (L1)."""

    key: str
    type: IntakeType
    label: str
    hint: str | None = None
    placeholder: str | None = None
    options: list[IntakeOption] | None = None
    items: list[CountItem] | None = Field(default=None, description="For counts: the things being counted")
    unit: str | None = Field(default=None, description="For number: plural unit, e.g. bedrooms")
    unit1: str | None = Field(default=None, description="For number: singular unit, e.g. bedroom")
    min: int | None = None
    max: int | None = None
    step: int | None = None
    max_photos: int | None = Field(default=None, description="For photos: most files accepted")
    default: Any = Field(description="Default answer: str, list[str], int, dict[str, int] or [] for photos")


class Category(Doc):
    COLLECTION: ClassVar[str] = "categories"

    name: str
    short: str
    group: Literal["outside", "inside", "help"]
    status: Literal["live", "planned"] = Field(description="Only live categories are bookable")
    skill: str = Field(description="Provider skill tag, e.g. garden.mowing")
    pricing_model: str = Field(description="Key into PRICING_MODELS")
    measure: Literal["lawn"] | None = Field(default=None, description="lawn: the quote flow has a lawn-size step")
    recurring: bool
    from_price_pence: int
    requires: list[DocType] = Field(description="Documents a provider must hold (verified, unexpired)")
    intake: list[IntakeField]
    icon: str = Field(description="lucide-react icon name used by the web")
    sort: int = 0


class CategoryGroup(Doc):
    COLLECTION: ClassVar[str] = "category_groups"

    name: str
    tab: str = Field(description="Short tab label on the quote starter")
    sort: int = 0


class DocumentType(Doc):
    COLLECTION: ClassVar[str] = "document_types"

    label: str
    expires: bool = True
    valid_months: int | None = Field(
        default=None, description="Valid this many months from the issue date (basic DBS: 12); else the stated expiry"
    )
    note: str | None = None
    sort: int = 0


class ExcludedJob(Doc):
    """Jobs we never list, shown to customers with who to use instead."""

    COLLECTION: ClassVar[str] = "excluded_jobs"

    name: str
    instead: str
    why: str
    sort: int = 0
