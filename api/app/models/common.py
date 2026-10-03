"""Building blocks shared by every collection model.

Conventions (docs/spec/domain.md):
- `_id` is a 24-hex string; models expose it as `id`. References store the same string.
- Money is integer pence in fields ending `_pence`.
- Datetimes are timezone-aware UTC. Calendar dates (London) are ISO strings "2026-10-02".
- Phones are E.164.
"""

from datetime import date, datetime
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, PlainSerializer

from app.core.ids import new_id
from app.core.timeutil import utcnow

# A London calendar date, stored and sent as "YYYY-MM-DD" (BSON has no date type).
IsoDate = Annotated[date, PlainSerializer(lambda d: d.isoformat(), return_type=str)]
Pence = Annotated[int, Field(ge=0, description="Integer pence")]
SignedPence = Annotated[int, Field(description="Integer pence; negative for refunds and reversals")]
E164 = Annotated[str, Field(pattern=r"^\+44\d{9,10}$", description="UK phone in E.164")]

Role = Literal["customer", "provider", "admin"]
Channel = Literal["sms", "whatsapp", "email"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DocType = Literal["identity", "insurance", "waste_carrier", "ladder_cover", "dbs_basic", "pet_cover"]
BookingSource = Literal["platform", "own_customer"]
DaysPref = Literal["any", "weekdays", "weekends"]
TimePref = Literal["morning", "afternoon", "either"]


class Model(BaseModel):
    """Embedded value objects."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Doc(Model):
    """A document in a collection. Subclasses set COLLECTION."""

    COLLECTION: ClassVar[str] = ""

    id: str = Field(default_factory=new_id, validation_alias=AliasChoices("_id", "id"))

    def to_mongo(self) -> dict[str, Any]:
        body = self.model_dump(mode="python", exclude={"id"})
        return {"_id": self.id, **body}

    @classmethod
    def from_mongo(cls, raw: dict[str, Any] | None) -> Self | None:
        return None if raw is None else cls.model_validate(raw)


class Timestamped(Doc):
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Address(Model):
    """A UK address. UPRN is stored on every address (decisions.md)."""

    @property
    def area(self) -> str:
        """Where the job is, as providers see it before booking: Hazlemere."""
        return self.locality or self.town

    line1: str
    line2: str = ""
    locality: str = Field(default="", description="Village or area, e.g. Hazlemere (post town is High Wycombe)")
    town: str
    postcode: str
    district: str = Field(description="Outward code, e.g. HP15")
    uprn: str | None = Field(default=None, description="Unique Property Reference Number")
    lat: float
    lng: float
    label: str = Field(default="", description="One-line display form")


class GeoPoint(Model):
    lat: float
    lng: float


class Actor(Model):
    """Who did something: a user, or the system (tasks, seed, webhooks)."""

    kind: Literal["user", "system"] = "user"
    user_id: str | None = None
    role: Role | None = None
    name: str | None = None


class Related(Model):
    """Ids a record relates to. Used on outbox messages, files and audit entries."""

    user_id: str | None = None
    customer_id: str | None = None
    provider_id: str | None = None
    request_id: str | None = None
    offer_id: str | None = None
    booking_id: str | None = None
    series_id: str | None = None
    visit_id: str | None = None
    dispute_id: str | None = None
    invite_id: str | None = None
    thread_id: str | None = None
    time_off_id: str | None = None
