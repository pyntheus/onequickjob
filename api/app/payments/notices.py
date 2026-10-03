"""The outbox messages money movements send, with idempotency keys so each goes once.

A charge that succeeds sends visit_done_customer (visit_done_customer_no_photo when there's
no after photo), receipt (when the customer has an email), payment_on_its_way and, when it
takes the provider to their earnings limit, limit_reached; one that fails or needs the
customer sends charge_failed_customer and charge_failed_provider, once per attempt; a refund
sends refund_issued; a payout that lands sends payout_sent; a tip that's charged sends
tip_received (L1). Every call takes the caller's transaction session.
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.core.db import Db, DbSession
from app.models.categories import Category
from app.models.common import Related
from app.models.customers import Customer
from app.models.providers import Provider
from app.models.users import User
from app.models.visits import Charge, Visit
from app.repos.categories import Categories
from app.repos.customers import Customers
from app.repos.providers import Providers
from app.repos.users import Users
from app.services import templates, wording
from app.services.eligibility import limit_status
from app.services.notify import link, notify, recipient_for


@dataclass(frozen=True)
class Parties:
    customer: Customer | None
    customer_user: User | None
    provider: Provider | None
    provider_user: User | None
    category: Category | None

    @property
    def category_word(self) -> str:
        return wording.lower_name(self.category) if self.category else "job"

    @property
    def category_name(self) -> str:
        return self.category.name if self.category else "Job"

    @property
    def customer_first(self) -> str:
        return wording.first_name(self.customer.name) if self.customer else "The customer"


async def parties(db: Db, visit: Visit, session: DbSession | None = None) -> Parties:
    customer = await Customers(db).get(visit.customer_id, session=session)
    provider = await Providers(db).get(visit.provider_id, session=session)
    users = Users(db)
    return Parties(
        customer=customer,
        customer_user=await users.get(customer.user_id, session=session) if customer else None,
        provider=provider,
        provider_user=await users.get(provider.user_id, session=session) if provider else None,
        category=await Categories(db).get(visit.category_id, session=session),
    )


def _related(visit: Visit, p: Parties) -> Related:
    return Related(
        visit_id=visit.id,
        booking_id=visit.booking_id,
        customer_id=visit.customer_id,
        provider_id=visit.provider_id,
    )


VISIT_DONE_NO_PHOTO = templates.register(
    templates.Template(
        id="visit_done_customer_no_photo",
        lane="L2",
        audience="customer",
        channels=("sms",),
        trigger="A provider finishes a visit without adding an after photo, and the card is charged.",
        body="{brand}: {provider} has finished your {category}. We've charged {price} to your card. "
        "Rate the visit: {link}",
    )
)


async def _full_name(db: Db, visit: Visit, session: DbSession) -> str:
    """Who did the visit, in full for the receipt (the short form ends in a full stop: "Dave H.")."""
    if visit.performer.kind == "helper":
        user = await Users(db).get(visit.performer.user_id, session=session)
        return user.name if user and user.name else visit.performer.name
    doer = await Providers(db).get(visit.performer.provider_id, session=session)
    return doer.name if doer else visit.performer.name


async def charged(db: Db, s: Settings, visit: Visit, charge: Charge, session: DbSession) -> None:
    """A visit's charge went through: tell the customer (text and receipt) and the provider."""
    p = await parties(db, visit, session)
    related = _related(visit, p)
    price, fee, net = (wording.money(x) for x in (charge.amount_pence, charge.fee_pence, charge.provider_pence))
    done_by = visit.performer.name
    base = f"charge:{visit.id}:visit:paid"
    if p.customer_user and p.customer_user.phone:
        # The photo is mentioned only when there is one (L2).
        done = "visit_done_customer" if visit.photos.after else VISIT_DONE_NO_PHOTO.id
        await notify(
            db,
            done,
            to=recipient_for(p.customer_user),
            data={
                "provider": done_by,
                "category": p.category_word,
                "price": price,
                "link": link(f"/account/visits/{visit.id}/rate", s),
            },
            related=related,
            settings=s,
            idempotency_key=f"{base}:visit_done_customer",
            session=session,
        )
    if p.customer_user and p.customer_user.email:
        card = p.customer.payment.card if p.customer and p.customer.payment else None
        await notify(
            db,
            "receipt",
            to=recipient_for(p.customer_user),
            data={
                "category": p.category_name,
                "date": wording.day_text(visit.local_date),
                "provider": await _full_name(db, visit, session),
                "price": price,
                "fee": fee,
                "provider_first": wording.first_name(p.provider.name if p.provider else done_by),
                "net": net,
                "last4": card.last4 if card else "••••",
            },
            related=related,
            settings=s,
            idempotency_key=f"{base}:receipt",
            session=session,
        )
    if p.provider_user and p.provider_user.phone:
        await notify(
            db,
            "payment_on_its_way",
            to=recipient_for(p.provider_user),
            data={"customer": p.customer_first, "price": price, "category": p.category_word, "net": net},
            related=related,
            settings=s,
            idempotency_key=f"{base}:payment_on_its_way",
            session=session,
        )
        await _limit_reached(db, s, p.provider, p.provider_user, charge.provider_pence, session)


async def _limit_reached(
    db: Db, s: Settings, provider: Provider | None, user: User, just_earned: int, session: DbSession
) -> None:
    """The text when this payment (already in the ledger) takes the provider to their earnings
    limit: once per period and amount, and not when they were over it before (L2)."""
    if provider is None:
        return
    lim = await limit_status(db, provider, session=session)
    if not (lim.on and lim.reached) or lim.earned_pence - just_earned >= lim.amount_pence:
        return
    await notify(
        db,
        "limit_reached",
        to=recipient_for(user),
        data={
            "period_word": "weekly" if lim.period == "week" else "monthly",
            "amount": wording.money(lim.amount_pence),
            "resume": wording.day_text(lim.resumes_on),
        },
        related=Related(provider_id=provider.id),
        settings=s,
        idempotency_key=f"limit:{provider.id}:{lim.period}:{lim.period_start}:{lim.amount_pence}",
        session=session,
    )


TIP_RECEIVED = templates.register(
    templates.Template(
        id="tip_received",
        lane="L3",
        audience="provider",
        channels=("sms",),
        trigger="A customer's tip is charged (with their rating; L1 charges it through app.payments.charging).",
        body="{brand}: {customer} added a {tip} tip for your {category}. All of it goes to you, with no fee.",
    )
)


async def tip_paid(db: Db, s: Settings, visit: Visit, charge: Charge, session: DbSession) -> None:
    """A tip went through: tell the provider, once (whichever path recorded it: the request,
    a webhook or the settle task)."""
    p = await parties(db, visit, session)
    if p.provider_user and p.provider_user.phone:
        await notify(
            db,
            "tip_received",
            to=recipient_for(p.provider_user),
            data={"customer": p.customer_first, "tip": wording.money(charge.amount_pence), "category": p.category_word},
            related=_related(visit, p),
            settings=s,
            idempotency_key=f"charge:{visit.id}:tip:paid:tip_received",
            session=session,
        )


async def charge_failed(
    db: Db,
    s: Settings,
    visit: Visit,
    charge: Charge,
    *,
    attempt_key: str,
    tell_customer: bool,
    session: DbSession,
) -> None:
    """A charge attempt failed or needs the customer to confirm. Once per attempt and state.
    tell_customer is False when the problem isn't their card (the provider's account, or ours)."""
    p = await parties(db, visit, session)
    related = _related(visit, p)
    base = f"{attempt_key}:{charge.status}"
    day = wording.day_text(visit.local_date)
    if tell_customer and p.customer_user and p.customer_user.phone:
        await notify(
            db,
            "charge_failed_customer",
            to=recipient_for(p.customer_user),
            data={
                "price": wording.money(charge.amount_pence),
                "category": p.category_word,
                "date": day,
                "link": link("/account", s),
            },
            related=related,
            settings=s,
            idempotency_key=f"{base}:charge_failed_customer",
            session=session,
        )
    if tell_customer and p.provider_user and p.provider_user.phone:
        await notify(
            db,
            "charge_failed_provider",
            to=recipient_for(p.provider_user),
            data={"customer": p.customer_first, "category": p.category_word, "date": day},
            related=related,
            settings=s,
            idempotency_key=f"{base}:charge_failed_provider",
            session=session,
        )


async def refunded(
    db: Db, s: Settings, visit: Visit, amount_pence: int, *, key: str, session: DbSession, dispute_id: str | None = None
) -> None:
    p = await parties(db, visit, session)
    if not (p.customer_user and p.customer_user.phone):
        return
    related = _related(visit, p)
    related.dispute_id = dispute_id
    await notify(
        db,
        "refund_issued",
        to=recipient_for(p.customer_user),
        data={
            "amount": wording.money(amount_pence),
            "category": p.category_word,
            "date": wording.day_text(visit.local_date),
        },
        related=related,
        settings=s,
        idempotency_key=f"{key}:refund_issued",
        session=session,
    )


async def payout_sent(
    db: Db, s: Settings, provider: Provider, *, payout_id: str, amount_pence: int, last4: str | None, session: DbSession
) -> None:
    user = await Users(db).get(provider.user_id, session=session)
    if not (user and user.phone):
        return
    await notify(
        db,
        "payout_sent",
        to=recipient_for(user),
        data={"amount": wording.money(amount_pence), "last4": last4 or "••••"},
        related=Related(provider_id=provider.id, user_id=user.id),
        settings=s,
        idempotency_key=f"payout:{payout_id}:payout_sent",
        session=session,
    )
