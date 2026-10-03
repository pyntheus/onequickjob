"""pricing_versions: the params every pricing model reads. Owner: L3.

Exactly one version is live (unique partial index). A draft is created by one admin
and approved by a different admin, at which point it goes live and the previous live
version is retired. Every quote records the version it used.
"""

from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import Field

from app.models.common import Doc, Model


class ParamChange(Model):
    category_id: str
    path: str = Field(description="Dotted path inside that category's params, e.g. growth.overgrown")
    before: Any = None
    after: Any


class PricingVersion(Doc):
    COLLECTION: ClassVar[str] = "pricing_versions"

    version: int
    status: Literal["draft", "live", "retired"]
    params: dict[str, dict[str, Any]] = Field(description="category id -> params for its pricing model")
    notes: str = ""
    changes: list[ParamChange] = Field(default_factory=list, description="What changed from based_on")
    based_on: str | None = Field(default=None, description="Version id this draft was copied from")
    created_by: str = Field(description="User id, or 'seed'")
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    retired_at: datetime | None = None
