"""Your own customers: people a provider already works for, brought on at the own-customer fee
(5%, 100p minimum: app.core.money) instead of the standard 15%.

The invite-only rule: a number that belongs to a customer who found us through the platform
is blocked (recorded, for the admin count) and they stay on the standard fee. The customer
accepts at /invite/{token} (L1), which creates the booking with source own_customer.
"""

from datetime import timedelta

from fastapi import status

from app.core import money
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail
from app.core.ids import new_token, token_hash
from app.core.phone import InvalidPhone, is_mobile, to_e164
from app.core.timeutil import utcnow
from app.models.common import Related
from app.models.provider_ops import OwnCustomerInvite
from app.models.providers import Provider
from app.models.system import Recipient
from app.provider.common import categories, frequency_label
from app.provider.schemas import FeeComparison, InviteIn, InviteOut, OwnCustomerRow, OwnCustomersView
from app.repos.bookings import Bookings
from app.repos.customers import Customers
from app.repos.own_customer_invites import OwnCustomerInvites
from app.repos.users import Users
from app.services import wording
from app.services.notify import link, notify
from app.services.quotes import fee_split

EXAMPLE_PRICE_PENCE = 3000
INVITE_DAYS = 30
BLOCKED = (
    "That number already belongs to a OneQuickJob customer, so they stay on the standard fee. "
    "Any regular work you already do for them is still yours."
)


async def view(db: Db, s: Settings, provider: Provider) -> OwnCustomersView:
    cats = await categories(db)
    bookings = await Bookings(db).find(
        {"provider_id": provider.id, "source": "own_customer", "status": "active"}, sort=[("created_at", 1)]
    )
    ids = list({b.customer_id for b in bookings})
    names = {c.id: c.name for c in await Customers(db).find({"_id": {"$in": ids}})} if ids else {}
    rows = [
        OwnCustomerRow(
            id=b.id,
            name=names.get(b.customer_id, ""),
            area=b.address.area,
            category_name=cats[b.category_id].name,
            frequency_label=frequency_label(b.frequency),
            price_pence=b.price_pence,
            status="active",
        )
        for b in bookings
    ]
    for inv in await OwnCustomerInvites(db).find(
        {"provider_id": provider.id, "status": "invited"}, sort=[("created_at", 1)]
    ):
        rows.append(
            OwnCustomerRow(
                id=inv.id,
                name=inv.name,
                area="",
                category_name=cats[inv.category_id].name,
                frequency_label=frequency_label(inv.frequency),
                price_pence=inv.price_pence,
                status="invited",
            )
        )
    return OwnCustomersView(
        comparison=FeeComparison(
            example_price_pence=EXAMPLE_PRICE_PENCE,
            own_customer=fee_split(EXAMPLE_PRICE_PENCE, "own_customer", s),
            standard=fee_split(EXAMPLE_PRICE_PENCE, "standard", s),
        ),
        customers=rows,
        skills=[c for c in provider.skills if c in cats and cats[c].status == "live"],
    )


async def invite(db: Db, s: Settings, provider: Provider, body: InviteIn) -> InviteOut:
    try:
        phone = to_e164(body.phone)
    except InvalidPhone as e:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_phone", str(e))
    if not is_mobile(phone):
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_a_mobile", "Enter their mobile number, so we can text them.")
    cats = await categories(db)
    cat = cats.get(body.category_id)
    if cat is None or cat.status != "live" or cat.id not in provider.skills:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_your_job", "Choose one of the jobs you do.")
    if body.price_pence % 100:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "whole_pounds", "Set your price in whole pounds.")
    name = " ".join(body.name.split())
    split = money.split(body.price_pence, "own_customer", s)

    user = await Users(db).by_phone(phone)
    customer = await Customers(db).by_user(user.id) if user else None
    if customer is not None and customer.joined_via == "platform":
        # Recorded so the admin overview can count them; nothing is sent.
        await OwnCustomerInvites(db).insert(
            OwnCustomerInvite(
                provider_id=provider.id,
                name=name,
                phone=phone,
                category_id=cat.id,
                price_pence=body.price_pence,
                frequency=body.frequency,
                status="blocked",
                blocked_reason=BLOCKED,
            )
        )
        fail(status.HTTP_409_CONFLICT, "platform_customer", BLOCKED)
    if customer is not None and customer.invited_by_provider_id == provider.id:
        fail(status.HTTP_409_CONFLICT, "already_yours", f"{wording.first_name(name)} is already one of your customers.")
    if await OwnCustomerInvites(db).count({"provider_id": provider.id, "phone": phone, "status": "invited"}):
        fail(
            status.HTTP_409_CONFLICT,
            "already_invited",
            "You've already invited that number. They can use the link in that text.",
        )

    token = new_token()
    inv = OwnCustomerInvite(
        provider_id=provider.id,
        name=name,
        phone=phone,
        category_id=cat.id,
        price_pence=body.price_pence,
        frequency=body.frequency,
        token_hash=token_hash(token, s.pepper),
        status="invited",
    )

    async def send(session: DbSession) -> None:
        msg = await notify(
            db,
            "own_customer_invite",
            to=Recipient(name=name, phone=phone),
            data={
                "provider_first": wording.first_name(provider.name),
                "category": wording.lower_name(cat),
                "price": wording.money(body.price_pence),
                "link": link(f"/invite/{token}", s),
            },
            related=Related(invite_id=inv.id, provider_id=provider.id),
            settings=s,
            session=session,
        )
        inv.outbox_id = msg.id
        await OwnCustomerInvites(db).insert(inv, session=session)

    await transaction(db, send)
    return InviteOut(
        invite_id=inv.id,
        status="invited",
        name=name,
        phone=phone,
        category_id=cat.id,
        price_pence=body.price_pence,
        provider_pence=split.provider_pence,
        fee_pence=split.fee_pence,
    )


async def expire_invites(db: Db) -> int:
    """Invites with no answer after 30 days expire (their link stops working)."""
    cutoff = utcnow() - timedelta(days=INVITE_DAYS)
    res = await OwnCustomerInvites(db).coll.update_many(
        {"status": "invited", "created_at": {"$lt": cutoff}},
        {"$set": {"status": "expired", "updated_at": utcnow()}},
    )
    return res.modified_count
