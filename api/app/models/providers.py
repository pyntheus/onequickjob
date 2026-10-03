"""providers and tax_identities. Owner: L2 (self-service). L3 writes document
verification and suspension through app.repos.providers functions."""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.common import Doc, DocType, GeoPoint, IsoDate, Model, Pence, Timestamped, Weekday

DocStatus = Literal["missing", "pending", "verified", "rejected", "expired"]
ProviderStatus = Literal["signing_up", "active", "payouts_paused", "suspended"]


class ProviderDocument(Model):
    type: DocType
    status: DocStatus
    issued_on: IsoDate | None = Field(default=None, description="Issue date (a basic DBS check runs 12 months from it)")
    expires_on: IsoDate | None = Field(
        default=None, description="Last valid day; use services.documents.expiry_for to work it out"
    )
    file_id: str | None = None
    verified_by: str | None = None
    verified_at: datetime | None = None
    note: str | None = None


class Home(Model):
    postcode: str
    district: str
    area: str = Field(description="Locality shown to customers, e.g. Hazlemere")
    location: GeoPoint


class AlertSettings(Model):
    sms: bool = True
    whatsapp: bool = False
    quiet_hours: bool = True
    quiet_from: str = "20:00"
    quiet_to: str = "08:00"


class EarningsLimit(Model):
    """The limit only. The benefits answer that suggests one is never stored."""

    on: bool = False
    period: Literal["week", "month"] = "week"
    amount_pence: Pence = 25000


class Helper(Model):
    user_id: str
    name: str
    relationship: str = ""
    status: Literal["invited", "checking", "ready", "removed"] = "invited"


class PaymentAccount(Model):
    gateway: Literal["fake", "stripe"]
    account_id: str
    status: Literal["pending", "enabled", "restricted"] = "pending"
    payouts_enabled: bool = False
    bank_last4: str | None = None


class TaxDetails(Model):
    """Masked copies for display. Full values are sealed in tax_identities."""

    complete: bool = False
    ni_masked: str | None = None
    dob_masked: str | None = None
    updated_at: datetime | None = None


class ProviderStats(Model):
    """Denormalised for lists; refreshed by whoever changes the inputs."""

    rating_avg: float | None = None
    rating_count: int = 0
    jobs_30d: int = 0
    accept_rate: float | None = None


class Provider(Timestamped):
    COLLECTION: ClassVar[str] = "providers"

    user_id: str
    name: str
    short: str = Field(description='Display name used to customers, e.g. "Dave H."')
    initials: str
    home: Home
    travel_radius_miles: int = 4
    working_days: list[Weekday] = Field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
    skills: list[str] = Field(default_factory=list, description="Category ids")
    documents: list[ProviderDocument] = Field(default_factory=list)
    alert_settings: AlertSettings = Field(default_factory=AlertSettings)
    earnings_limit: EarningsLimit = Field(default_factory=EarningsLimit)
    helpers: list[Helper] = Field(default_factory=list)
    payment_account: PaymentAccount | None = None
    tax: TaxDetails = Field(default_factory=TaxDetails)
    status: ProviderStatus = "signing_up"
    status_reason: str | None = None
    stats: ProviderStats = Field(default_factory=ProviderStats)
    joined_on: IsoDate | None = None


class TaxIdentity(Doc):
    """Full NI number and date of birth, sealed with the tax data keys (app.core.crypto): each
    value is "<key id>:<token>". Read only by the HMRC export."""

    COLLECTION: ClassVar[str] = "tax_identities"

    provider_id: str
    ni_number_sealed: str
    dob_sealed: str
    updated_at: datetime
