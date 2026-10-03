"""Finished visits ready to charge, for the payments and admin tests (L3)."""

import hashlib
import hmac
import json
import time
from datetime import timedelta

from app.core.ids import new_id
from app.core.timeutil import london_today, utcnow
from app.models.customers import Customer
from app.models.providers import PaymentAccount, Provider
from app.models.visits import Performer, Visit
from app.repos import Customers, Providers, Users, Visits
from tests.factories import make_customer, make_provider


async def payable_provider(db, name: str = "Dave Hughes", phone: str = "+447700900201", **kw) -> Provider:
    p = await make_provider(db, name, phone, ["mowing", "hedges", "clearance"], **kw)
    account = PaymentAccount(
        gateway="fake", account_id=f"acct_fake_{p.id[-8:]}", status="enabled", payouts_enabled=True
    )
    await Providers(db).patch(p.id, {"payment_account": account.model_dump(mode="python")})
    return await Providers(db).get(p.id)  # type: ignore[return-value]


async def card_customer(
    db, name: str = "Sarah Whitfield", phone: str = "+447700900123", email: str | None = "sarah@example.test"
) -> Customer:
    """A customer with a fake saved card. A name containing "decline" or "3ds" makes the fake
    gateway decline or ask for authentication."""
    c = await make_customer(db, name, phone)
    cus = f"cus_fake_{c.id[-8:]}"
    await Customers(db).update(c.id, {"payment.gateway_customer_id": cus})
    if email:
        await Users(db).update(c.user_id, {"email": email})
    await db["fake_gateway"].update_one({"_id": cus}, {"$set": {"kind": "customer", "name": name}}, upsert=True)
    return await Customers(db).get(c.id)  # type: ignore[return-value]


async def rename_card_holder(db, customer: Customer, name: str) -> None:
    assert customer.payment is not None
    await db["fake_gateway"].update_one({"_id": customer.payment.gateway_customer_id}, {"$set": {"name": name}})


async def finished_visit(
    db,
    customer: Customer,
    provider: Provider,
    *,
    price_pence: int = 3000,
    source: str = "platform",
    performer: Provider | None = None,
    performer_kind: str = "provider",
    category_id: str = "mowing",
    is_first: bool = False,
    est_mins: int = 40,
    actual_mins: int = 44,
    days_ago: int = 0,
) -> Visit:
    doer = performer or provider
    day = london_today() - timedelta(days=days_ago)
    start = utcnow() - timedelta(days=days_ago, hours=2)
    v = Visit(
        booking_id=new_id(),
        customer_id=customer.id,
        provider_id=provider.id,
        performer=Performer(kind=performer_kind, provider_id=doer.id, user_id=doer.user_id, name=doer.short),  # type: ignore[arg-type]
        category_id=category_id,
        source=source,  # type: ignore[arg-type]
        local_date=day,
        scheduled_start=start,
        is_first=is_first,
        price_pence=price_pence,
        est_mins=est_mins,
        status="finished",
        started_at=start,
        finished_at=start + timedelta(minutes=actual_mins),
        minutes_actual=actual_mins,
        minutes_from_timer=True,
        flags_none=True,
        overrun=actual_mins > est_mins * 1.1,
        over_25=actual_mins > est_mins * 1.25,
    )
    await Visits(db).insert(v)
    return v


def signed(event: dict, secret: str, at: int | None = None) -> tuple[bytes, dict[str, str]]:
    """A webhook body and the Stripe-Signature header Stripe would send with it."""
    payload = json.dumps(event).encode()
    t = at or int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return payload, {"stripe-signature": f"t={t},v1={sig}", "content-type": "application/json"}


def event(kind: str, obj: dict, *, eid: str | None = None, account: str | None = None, livemode: bool = False) -> dict:
    e = {
        "id": eid or f"evt_{new_id()[-12:]}",
        "object": "event",
        "type": kind,
        "livemode": livemode,
        "created": int(time.time()),
        "data": {"object": obj},
    }
    if account:
        e["account"] = account
    return e
