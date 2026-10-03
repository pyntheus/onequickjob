"""Sign-up: the checklist, the provider record, tax details (sealed), the payment account.

Tax identifiers: the full NI number and date of birth are sealed (core.crypto.seal, the tax
data keys) in tax_identities, read only by the HMRC export (L3); the provider record keeps
masked copies for display (decisions.md R28). A new provider stays signing_up until every
required check is done (an admin checks their documents), then becomes active automatically
(app.services.lifecycle, A19): giving tax details and finishing payout set-up can be the last.
"""

import contextlib
from datetime import date

from fastapi import status
from pymongo.errors import DuplicateKeyError

from app.adapters.address.base import AddressLookup, AddressLookupError
from app.adapters.payments.base import PaymentGateway, ProviderRef
from app.core.config import Settings
from app.core.crypto import mask_dob, mask_ni, seal
from app.core.db import Db, DbSession, transaction
from app.core.deps import CurrentUser
from app.core.errors import fail
from app.core.geo import district_of, normalise_postcode
from app.core.phone import to_national
from app.core.timeutil import london_today, utcnow
from app.models.common import Address, GeoPoint, Related
from app.models.providers import Home, PaymentAccount, Provider, TaxDetails
from app.models.system import Recipient
from app.provider.common import short_name
from app.provider.schemas import (
    OnboardingLink,
    SignupChecklist,
    SignupStart,
    SignupStep,
    TaxDetailsIn,
    TaxDetailsOut,
)
from app.repos.providers import Providers, TaxIdentities
from app.repos.users import Users
from app.services.lifecycle import activate_if_ready
from app.services.notify import link, notify

STEPS: list[tuple[str, str, str]] = [
    ("details", "Your details", "Name, home and phone"),
    ("identity", "Check your ID", "A photo of your passport or driving licence. We check it by hand."),
    ("tax", "Tax details", "National Insurance number and date of birth, for HMRC"),
    ("insurance", "Insurance", "Upload your public liability certificate"),
    ("work", "What you do and where", "Jobs, travel distance and days"),
    ("payouts", "Get paid", "Connect your bank account for Friday payouts"),
]


def _has(provider: Provider, doc_type: str) -> bool:
    return any(d.type == doc_type and d.status in ("pending", "verified") for d in provider.documents)


def checklist(provider: Provider | None) -> SignupChecklist:
    done = {
        "details": provider is not None,
        "identity": provider is not None and _has(provider, "identity"),
        "tax": provider is not None and provider.tax.complete,
        "insurance": provider is not None and _has(provider, "insurance"),
        "work": provider is not None and bool(provider.skills),
        "payouts": provider is not None
        and provider.payment_account is not None
        and provider.payment_account.status == "enabled",
    }
    steps: list[SignupStep] = []
    now_given = False
    for key, title, detail in STEPS:
        if done[key]:
            state = "done"
        elif not now_given:
            state, now_given = "now", True
        else:
            state = "todo"
        steps.append(SignupStep(key=key, title=title, detail=detail, state=state))  # type: ignore[arg-type]
    acct = provider.payment_account if provider else None
    return SignupChecklist(
        steps=steps,
        done_count=sum(done.values()),
        provider_id=provider.id if provider else None,
        status=provider.status if provider else None,
        payment_account_status=acct.status if acct else "none",
        limit_on=bool(provider and provider.earnings_limit.on),
    )


async def _sync_account(
    db: Db, s: Settings, gateway: PaymentGateway, provider: Provider, user: CurrentUser
) -> Provider:
    """Back from onboarding: ask the gateway how the payout account stands (L3's webhooks also
    keep it current with Stripe). An enabled account can be the last check (A19)."""
    acct = provider.payment_account
    if acct is None or acct.status == "enabled":
        return provider
    try:
        now = await gateway.account_status(acct.account_id)
    except Exception:
        return provider
    synced = acct.model_copy(
        update={"status": now.status, "payouts_enabled": now.payouts_enabled, "bank_last4": now.bank_last4}
    )
    if synced == acct:
        return provider

    async def save(session: DbSession) -> Provider | None:
        updated = await Providers(db).update(
            provider.id,
            {"payment_account": synced.model_dump()},
            extra_filter={"payment_account.account_id": acct.account_id},
            session=session,
        )
        if updated is not None:
            updated = (
                await activate_if_ready(db, s, provider.id, actor=user.actor("provider"), session=session) or updated
            )
        return updated

    return await transaction(db, save) or provider


async def get_checklist(db: Db, s: Settings, gateway: PaymentGateway, user: CurrentUser) -> SignupChecklist:
    provider = await Providers(db).by_user(user.id)
    if provider is not None:
        provider = await _sync_account(db, s, gateway, provider, user)
    return checklist(provider)


async def _home(lookup: AddressLookup, body: SignupStart) -> Address:
    try:
        postcode = normalise_postcode(body.postcode)
    except ValueError:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_postcode", "That doesn't look like a UK postcode.")
    try:
        if body.address_id:
            address = await lookup.resolve(body.address_id)
        else:
            found = await lookup.search(postcode, limit=1)
            address = await lookup.resolve(found[0].id) if found else None
    except AddressLookupError:
        fail(status.HTTP_503_SERVICE_UNAVAILABLE, "lookup_down", "We couldn't look that up just now. Try again soon.")
    if address is None:
        fail(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "postcode_not_found",
            "We couldn't find that postcode. Choose your address from the list.",
        )
    return address


async def start(db: Db, lookup: AddressLookup, user: CurrentUser, body: SignupStart) -> SignupChecklist:
    """Adds the provider role and creates the provider record (status signing_up). Safe to
    repeat: an existing record is returned as it is."""
    if user.user.helper_of:
        fail(
            status.HTTP_409_CONFLICT,
            "helper_account",
            "You're set up as a helper. Ring us if you'd like your own account.",
        )
    existing = await Providers(db).by_user(user.id)
    if existing is not None:
        return checklist(existing)
    address = await _home(lookup, body)
    name = " ".join(body.name.split())
    email = (body.email or "").strip().lower() or None
    if email and ("@" not in email or " " in email):
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_email", "That doesn't look like an email address.")
    provider = Provider(
        user_id=user.id,
        name=name,
        short=short_name(name),
        initials="".join(w[0] for w in name.split()[:2]).upper(),
        home=Home(
            postcode=address.postcode,
            district=district_of(address.postcode),
            area=address.locality or address.town,
            location=GeoPoint(lat=address.lat, lng=address.lng),
        ),
        status="signing_up",
        email=email,
    )

    async def create(session: DbSession) -> None:
        await Users(db).add_role(user.id, "provider", session=session)
        await Providers(db).insert(provider, session=session)

    with contextlib.suppress(DuplicateKeyError):  # started twice at once: the first one stands
        await transaction(db, create)
    return checklist(await Providers(db).by_user(user.id))


async def _provider_of(db: Db, user: CurrentUser) -> Provider:
    provider = await Providers(db).by_user(user.id)
    if provider is None:
        fail(status.HTTP_409_CONFLICT, "start_first", "Start with your details first.")
    return provider


def _age(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


async def save_tax(db: Db, s: Settings, user: CurrentUser, body: TaxDetailsIn) -> TaxDetailsOut:
    provider = await _provider_of(db, user)
    ni = "".join(body.ni_number.split()).upper()
    age = _age(body.date_of_birth, london_today())
    if not 16 <= age <= 100:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_dob", "Check your date of birth.")
    dob = body.date_of_birth.isoformat()
    details = TaxDetails(complete=True, ni_masked=mask_ni(ni), dob_masked=mask_dob(dob), updated_at=utcnow())

    async def save(session: DbSession) -> None:
        await TaxIdentities(db).upsert(provider.id, seal(ni, s), seal(dob, s), session=session)
        await Providers(db).update(provider.id, {"tax": details.model_dump()}, session=session)
        await activate_if_ready(db, s, provider.id, actor=user.actor("provider"), session=session)

    await transaction(db, save)
    return TaxDetailsOut(complete=True, ni_masked=details.ni_masked or "", dob_masked=details.dob_masked or "")


async def payment_account(db: Db, s: Settings, gateway: PaymentGateway, user: CurrentUser) -> OnboardingLink:
    """PaymentGateway.create_provider_account (once) then onboarding_link. Gateway calls are
    never inside a transaction."""
    provider = await _provider_of(db, user)
    acct = provider.payment_account
    if acct is None:
        made = await gateway.create_provider_account(
            ProviderRef(provider_id=provider.id, name=provider.name, email=provider.email, phone=user.user.phone)
        )
        acct = PaymentAccount(
            gateway=gateway.name,
            account_id=made.account_id,
            status=made.status,
            payouts_enabled=made.payouts_enabled,
            bank_last4=made.bank_last4,
        )

        async def save(session: DbSession) -> Provider | None:
            saved = await Providers(db).update(
                provider.id,
                {"payment_account": acct.model_dump()},
                extra_filter={"payment_account": None},
                session=session,
            )
            if saved is not None:  # the gateway may enable the account at once (A19)
                await activate_if_ready(db, s, provider.id, actor=user.actor("provider"), session=session)
            return saved

        if await transaction(db, save) is None:  # made twice at once: use the one that was saved
            again = await Providers(db).get(provider.id)
            assert again is not None and again.payment_account is not None
            acct = again.payment_account
    url = await gateway.onboarding_link(
        acct.account_id,
        return_url=link("/p/signup?onboarding=done", s),
        refresh_url=link("/p/signup?onboarding=again", s),
    )
    return OnboardingLink(url=url)


async def callback(db: Db, s: Settings, user: CurrentUser, step: str) -> str:
    """ "Call me": an email to the team, at most one a day per person."""
    admins = await Users(db).find({"roles": "admin", "email": {"$type": "string"}})
    phone = to_national(user.user.phone) if user.user.phone else "no phone"
    for admin in admins:
        await notify(
            db,
            "callback_requested",
            to=Recipient(user_id=admin.id, name=admin.name, email=admin.email),
            channel="email",
            data={"name": user.user.name, "phone": phone, "step": step.strip() or "the start"},
            related=Related(user_id=user.id),
            idempotency_key=f"callback:{user.id}:{admin.id}:{london_today().isoformat()}",
            settings=s,
        )
    return "Thanks. Someone from our local team will ring you back."
