"""Users, customers, providers (with documents, tax and payout accounts) and helpers."""

from datetime import date, timedelta

from app.core.crypto import mask_dob, mask_ni, seal, unseal
from app.core.geo import district_of
from app.models.common import GeoPoint
from app.models.customers import Customer, CustomerPayment, SavedCard
from app.models.providers import (
    AlertSettings,
    EarningsLimit,
    Helper,
    Home,
    PaymentAccount,
    Provider,
    ProviderDocument,
    ProviderStats,
    TaxDetails,
    TaxIdentity,
)
from app.models.users import User
from app.repos.providers import TaxIdentities
from app.seed.cleanup import clear_clashing_people
from app.seed.context import Ctx, sid

CARD = SavedCard(brand="visa", last4="4242", exp_month=12, exp_year=2028)
LATER_EXPIRY = {"waste_carrier": date(2029, 3, 1)}


def gateway_customer_id(key: str) -> str:
    return "cus_fake_" + sid("customer-gateway", key)[-12:]


def gateway_account_id(key: str) -> str:
    return "acct_fake_" + sid("provider-gateway", key)[-12:]


def _email(name: str) -> str:
    return name.lower().replace(" ", ".") + "@example.com"


async def seed_people(ctx: Ctx) -> None:
    w = ctx.w
    admin_ids: list[str] = []
    for a in ctx.people["admins"]:
        joined = ctx.at(ctx.day(200), "09:00")
        u = User(
            id=sid("user", a["key"]),
            name=a["name"],
            phone=a["phone"],
            email=a["email"],
            roles=["admin"],
            demo_key=f"admin_{a['key']}",
            **ctx.timestamps(joined),
        )
        ctx.admins[a["key"]] = u
        ctx.users[f"admin_{a['key']}"] = u
        admin_ids.append(u.id)
    verifier = admin_ids[0]

    for c in ctx.people["customers"] + ctx.people["pool"]:
        demo = c in ctx.people["customers"]
        joined = ctx.at(ctx.day(c.get("joined_days_ago", 130)), "08:30") - timedelta(hours=2)
        u = User(
            id=sid("user", c["key"]),
            name=c["name"],
            phone=c["phone"],
            email=c.get("email") or _email(c["name"]),
            roles=["customer"],
            demo_key=c["key"] if demo else None,
            **ctx.timestamps(joined),
        )
        ctx.users[c["key"]] = u
        own = c.get("joined_via") == "own_customer"
        cust = Customer(
            id=sid("customer", c["key"]),
            user_id=u.id,
            name=c["name"],
            addresses=[ctx.address(c["address"])],
            payment=CustomerPayment(
                gateway="fake",
                gateway_customer_id=gateway_customer_id(c["key"]),
                setup_id="seti_fake_" + sid("setup", c["key"])[-12:],
                setup_status="succeeded",
                card=CARD,
            ),
            joined_via="own_customer" if own else "platform",
            invited_by_provider_id=sid("provider", c["invited_by"]) if own else None,
            terms_accepted_at=joined,
            **ctx.timestamps(joined),
        )
        ctx.customers[c["key"]] = cust
        w.add_raw("fake_gateway", {"_id": gateway_customer_id(c["key"]), "kind": "customer", "name": c["name"]})

    for p in ctx.people["providers"]:
        joined_on = date.fromisoformat(p["joined_on"]) if "joined_on" in p else ctx.day(p["joined_days_ago"])
        joined = ctx.at(joined_on, "10:00")
        u = User(
            id=sid("user", p["key"]),
            name=p["name"],
            phone=p["phone"],
            email=_email(p["name"]),
            roles=["provider"],
            demo_key=p["key"],
            **ctx.timestamps(joined),
        )
        ctx.users[p["key"]] = u
        docs: list[ProviderDocument] = []
        verified_at = joined + timedelta(days=2)
        identity = p.get("identity", "verified")
        docs.append(
            ProviderDocument(
                type="identity",
                status=identity,
                verified_by=verifier if identity == "verified" else None,
                verified_at=verified_at if identity == "verified" else None,
                note="Checked with Stripe" if identity == "verified" else None,
            )
        )
        insurance_expiry = (
            ctx.today + timedelta(days=p["insurance_expires_in_days"])
            if "insurance_expires_in_days" in p
            else date.fromisoformat(p["insurance_expires"])
            if p.get("insurance_expires")
            else None
        )
        for t in p["docs"]:
            expires = None if t == "dbs_basic" else LATER_EXPIRY.get(t, insurance_expiry)
            docs.append(
                ProviderDocument(
                    type=t, status="verified", expires_on=expires, verified_by=verifier, verified_at=verified_at
                )
            )
        active = p["status"] in ("active", "payouts_paused")
        account = None
        if active:
            enabled = p["status"] == "active"
            account = PaymentAccount(
                gateway="fake",
                account_id=gateway_account_id(p["key"]),
                status="enabled" if enabled else "restricted",
                payouts_enabled=enabled,
                bank_last4="2100",
            )
            w.add_raw(
                "fake_gateway",
                {
                    "_id": account.account_id,
                    "kind": "account",
                    "provider_id": sid("provider", p["key"]),
                    "status": "enabled" if enabled else "pending",
                    "bank_last4": "2100",
                    "created_at": verified_at,
                },
            )
        tax = TaxDetails()
        if p["hmrc"]:
            tax = TaxDetails(
                complete=True, ni_masked=mask_ni(p["ni"]), dob_masked=mask_dob(p["dob"]), updated_at=joined
            )
        prov = Provider(
            id=sid("provider", p["key"]),
            user_id=u.id,
            name=p["name"],
            short=p["short"],
            initials=p["initials"],
            home=Home(
                postcode=p["postcode"],
                district=district_of(p["postcode"]),
                area=p["area"],
                location=GeoPoint(lat=p["lat"], lng=p["lng"]),
            ),
            travel_radius_miles=p.get("travel_radius_miles", 4),
            working_days=p["working_days"],
            skills=p["skills"],
            documents=docs,
            alert_settings=AlertSettings(sms=True, whatsapp=False, quiet_hours=True),
            earnings_limit=EarningsLimit(on=False, period="week", amount_pence=25000),
            payment_account=account,
            tax=tax,
            status=p["status"],
            status_reason=p.get("status_reason"),
            stats=ProviderStats(
                rating_avg=p["rating"], rating_count=p["reviews"], jobs_30d=p["jobs30"], accept_rate=p["accept"]
            ),
            joined_on=joined_on,
            **ctx.timestamps(joined),
        )
        ctx.providers[p["key"]] = prov

    for h in ctx.people["helpers"]:
        boss = ctx.providers[h["helper_of"]]
        u = User(
            id=sid("user", h["key"]),
            name=h["name"],
            phone=h["phone"],
            email=h["email"],
            roles=[],
            helper_of=boss.id,
            demo_key=h["key"],
            **ctx.timestamps(boss.created_at + timedelta(days=30)),
        )
        ctx.users[h["key"]] = u
        boss.helpers.append(Helper(user_id=u.id, name=h["name"], relationship=h["relationship"], status="ready"))

    await clear_clashing_people(ctx)
    for u in ctx.users.values():
        w.add(u)
    for c in ctx.customers.values():
        w.add(c)
    for p in ctx.providers.values():
        w.add(p)
    await w.flush()
    await _tax_identities(ctx)


async def _tax_identities(ctx: Ctx) -> None:
    """Sealed NI numbers and dates of birth. Sealing isn't deterministic, so an existing
    identity that still unseals to the same values is kept as it is."""
    repo = TaxIdentities(ctx.db)
    for p in ctx.people["providers"]:
        if not p["hmrc"]:
            continue
        pid = sid("provider", p["key"])
        existing = await repo.find_one({"provider_id": pid})
        if existing:
            try:
                same = (
                    unseal(existing.ni_number_sealed, ctx.s) == p["ni"]
                    and unseal(existing.dob_sealed, ctx.s) == p["dob"]
                )
            except ValueError:
                same = False
            if same:
                continue
            await repo.delete(existing.id)
        await repo.insert(
            TaxIdentity(
                id=sid("tax_identity", p["key"]),
                provider_id=pid,
                ni_number_sealed=seal(p["ni"], ctx.s),
                dob_sealed=seal(p["dob"], ctx.s),
                updated_at=ctx.providers[p["key"]].created_at,
            )
        )
