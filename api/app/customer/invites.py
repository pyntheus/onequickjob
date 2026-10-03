"""Own-customer invites from the customer's side (L1): the public preview behind the link in the
provider's text, and accepting it. The price is the provider's; our fee (5%, at least £1) is
paid by the provider and never added to it. Accepting is one transaction: the invite, the
customer record, the booking (services.bookings.create_booking, source own_customer) and the
provider's message."""

from datetime import datetime

from fastapi import status

from app.core import money
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.core.ids import token_hash
from app.core.phone import mask
from app.core.timeutil import to_london, utcnow
from app.customer.schemas import InviteAccept, InvitePreview
from app.customer.views import frequency_label, provider_card
from app.models.bookings import Booking
from app.models.categories import Category
from app.models.common import Related
from app.models.customers import Customer
from app.models.provider_ops import OwnCustomerInvite
from app.models.providers import Provider
from app.models.users import User
from app.pricing.answers import validate_answers
from app.pricing.engine import params_for, price
from app.repos.bookings import Bookings
from app.repos.categories import Categories
from app.repos.customers import Customers
from app.repos.job_requests import JobRequests
from app.repos.own_customer_invites import OwnCustomerInvites
from app.repos.providers import Providers
from app.repos.users import Users
from app.services import schedule, wording
from app.services.bookings import create_booking
from app.services.notify import notify, recipient_for
from app.services.quotes import live_version

DEFAULT_LAWN_M2 = 85  # the Medium band: only used to estimate minutes for the provider's round
UNITS = {"cleaning": "a clean", "dogwalking": "a walk"}


async def find(db: Db, s: Settings, token: str) -> OwnCustomerInvite:
    invite = await OwnCustomerInvites(db).by_token_hash(token_hash(token, s.pepper))
    if invite is None:
        not_found("That invite")
    return invite


async def _parts(db: Db, invite: OwnCustomerInvite) -> tuple[Provider, Category]:
    provider = await Providers(db).get(invite.provider_id)
    cat = await Categories(db).get(invite.category_id)
    if provider is None or cat is None:
        not_found("That invite")
    return provider, cat


async def estimate(db: Db, cat: Category, frequency: str) -> tuple[int, str, dict]:
    """Minutes, unit and answers for the booking, from the live pricing version with the
    category's default answers (the provider set the price; this only sizes the visit)."""
    answers: dict = {}
    if any(f.key == "frequency" for f in cat.intake):
        answers["frequency"] = frequency
    try:
        full = validate_answers(cat, answers)
        version = await live_version(db)
        est = price(cat, full, params_for(version.params, cat.id), DEFAULT_LAWN_M2 if cat.measure else None, "medium")
        unit = est.unit
        if frequency == "oneoff":
            unit = "one-off"
        return est.mins, unit, full
    except Exception:
        unit = "one-off" if frequency == "oneoff" else UNITS.get(cat.id, "a visit")
        return 60, unit, answers


async def first_visit_text(db: Db, provider: Provider, mins: int) -> str:
    start = await schedule.first_slot(db, provider, "any", "either", mins)
    return wording.day_text(start)


async def preview(db: Db, s: Settings, invite: OwnCustomerInvite) -> InvitePreview:
    provider, cat = await _parts(db, invite)
    mins, _, _ = await estimate(db, cat, invite.frequency)
    booking = await Bookings(db).get(invite.booking_id) if invite.booking_id else None
    next_text = None
    if invite.status == "invited":
        next_text = await first_visit_text(db, provider, mins)
    elif booking:
        from app.customer.views import first_visit

        v = await first_visit(db, booking)
        next_text = wording.day_text(v.local_date) if v else None
    return InvitePreview(
        invite_id=invite.id,
        status=invite.status,
        customer_first_name=wording.first_name(invite.name),
        provider=provider_card(provider, cat, None),
        category_id=cat.id,
        category_name=cat.name,
        frequency_label=frequency_label(invite.frequency) or "one-off",
        price_pence=invite.price_pence,
        provider_fee_pence=money.split(invite.price_pence, "own_customer", s).fee_pence,
        next_visit_text=next_text,
        phone_hint=mask(invite.phone),
    )


async def _platform_customer(db: Db, customer: Customer) -> bool:
    """Has this customer already booked through the platform? Then the invite-only rule keeps
    them on the standard fee."""
    if customer.joined_via != "platform":
        return False
    return (
        await JobRequests(db).count({"customer_id": customer.id}) > 0
        or await Bookings(db).count({"customer_id": customer.id, "source": "platform"}) > 0
    )


async def accept(db: Db, s: Settings, invite: OwnCustomerInvite, user: User, body: InviteAccept) -> Booking:
    if invite.status == "accepted":
        fail(status.HTTP_409_CONFLICT, "already_accepted", "You've already accepted this invite.")
    if invite.status != "invited":
        fail(
            status.HTTP_409_CONFLICT,
            "not_open",
            "This invite isn't open any more. Ask your provider to send a new one.",
        )
    if user.phone != invite.phone:
        fail(
            status.HTTP_403_FORBIDDEN,
            "wrong_number",
            f"This invite was sent to {mask(invite.phone)}. Sign in with that number to accept it.",
        )
    provider, cat = await _parts(db, invite)
    customer = await Customers(db).by_user(user.id)
    if customer and await _platform_customer(db, customer):
        fail(
            status.HTTP_409_CONFLICT,
            "platform_customer",
            "You already book through OneQuickJob, so this stays on the standard terms. "
            f"You can book {wording.first_name(provider.name)} again from your account.",
        )
    if customer is None or customer.payment is None or customer.payment.card is None:
        fail(status.HTTP_409_CONFLICT, "card_needed", "Add your card first. It's charged only after each visit.")
    address = body.address or (customer.addresses[0] if customer.addresses else None)
    if address is None:
        fail(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "address_needed",
            "Tell us your address so your provider can find you.",
        )
    mins, unit, answers = await estimate(db, cat, invite.frequency)

    async def accept_invite(session: DbSession) -> Booking:
        now: datetime = utcnow()
        if (
            await OwnCustomerInvites(db).update(
                invite.id,
                {"status": "accepted", "accepted_at": now, "customer_id": customer.id},
                extra_filter={"status": "invited"},
                session=session,
            )
            is None
        ):
            fail(status.HTTP_409_CONFLICT, "not_open", "This invite isn't open any more.")
        updated = await Customers(db).update(
            customer.id,
            {
                "joined_via": "own_customer",
                "invited_by_provider_id": provider.id,
                "terms_accepted_at": now,
                "name": customer.name or invite.name,
            },
            session=session,
        )
        assert updated is not None
        await Customers(db).add_address(customer.id, address, session=session)
        await Users(db).add_role(user.id, "customer", session=session)
        if not user.name:
            await Users(db).update(user.id, {"name": invite.name}, session=session)
        booking, first = await create_booking(
            db,
            session=session,
            source="own_customer",
            via="invite",
            customer=updated,
            provider=provider,
            category_id=cat.id,
            price_pence=invite.price_pence,
            first_price_pence=None,
            unit=unit,  # type: ignore[arg-type]
            frequency=invite.frequency,
            est_mins=mins,
            first_est_mins=None,
            address=address,
            answers=answers,
            notes="",
            days="any",
            window="either",
            invite_id=invite.id,
        )
        await OwnCustomerInvites(db).update(invite.id, {"booking_id": booking.id}, session=session)
        pu = await Users(db).get(provider.user_id, session=session)
        if pu and pu.phone:
            await notify(
                db,
                "invite_accepted",
                to=recipient_for(pu),
                settings=s,
                related=Related(
                    invite_id=invite.id, booking_id=booking.id, customer_id=customer.id, provider_id=provider.id
                ),
                idempotency_key=f"invite:{invite.id}:invite_accepted",
                data={"customer": updated.name, "date": wording.day_text(to_london(first.scheduled_start))},
                session=session,
            )
        return booking

    return await transaction(db, accept_invite)
