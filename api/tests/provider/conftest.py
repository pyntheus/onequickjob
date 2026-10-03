"""Fixtures for the provider lane's tests: providers with payout accounts, signed-in clients,
bookings made the real way (services.bookings.create_booking or a guide acceptance)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
import pytest

from app.core.db import transaction
from app.core.timeutil import london_datetime, london_today
from app.models.bookings import Booking
from app.models.customers import Customer
from app.models.providers import Helper, PaymentAccount, Provider
from app.models.users import User
from app.models.visits import Visit
from app.repos import Providers, Users, Visits
from app.services import bookings as bookings_service
from app.services import marketplace
from tests.conftest import make_settings, new_client, sign_in
from tests.factories import HAZLEMERE, make_customer, make_provider, make_request

DAVE_PHONE = "+447700900201"
MIKE_PHONE = "+447700900202"
TOM_PHONE = "+447700900220"


async def with_account(db, p: Provider) -> Provider:
    acct = PaymentAccount(gateway="fake", account_id=f"acct_fake_{p.id[-8:]}", status="enabled", payouts_enabled=True)
    updated = await Providers(db).patch(p.id, {"payment_account": acct.model_dump()})
    assert updated is not None
    return updated


async def make_dave(db, **kw) -> Provider:
    p = await make_provider(db, "Dave Hughes", DAVE_PHONE, kw.pop("skills", ["mowing", "hedges", "cleaning"]), **kw)
    return await with_account(db, p)


async def add_tom(db, dave: Provider, status: str = "ready") -> User:
    tom = User(name="Tom Hughes", phone=TOM_PHONE, roles=[], helper_of=dave.id)
    await Users(db).insert(tom)
    helper = Helper(user_id=tom.id, name="Tom Hughes", relationship="Son", status=status)  # type: ignore[arg-type]
    await Providers(db).update(dave.id, {}, push={"helpers": helper.model_dump(mode="python")})
    return tom


async def book(
    db,
    customer: Customer,
    provider: Provider,
    *,
    source: str = "platform",
    frequency: str | None = "fortnightly",
    price: int = 3000,
    first_price: int | None = None,
    category: str = "mowing",
    from_day: date | None = None,
    est_mins: int = 40,
) -> tuple[Booking, Visit]:
    """A booking made by the shared service, as the marketplace or an invite would."""

    async def make(session):
        return await bookings_service.create_booking(
            db,
            session=session,
            source=source,  # type: ignore[arg-type]
            via="invite" if source == "own_customer" else "guide",
            customer=customer,
            provider=provider,
            category_id=category,
            price_pence=price,
            first_price_pence=first_price,
            unit="a visit" if frequency not in (None, "oneoff") else "one-off",
            frequency=frequency,
            est_mins=est_mins,
            first_est_mins=None,
            address=HAZLEMERE,
            answers={},
            notes="The side gate sticks.",
            days="any",
            window="morning",
            from_day=from_day,
        )

    return await transaction(db, make)


async def move_to_today(db, visit: Visit, hhmm: tuple[int, int] = (9, 0)) -> Visit:
    """Put a visit on today's round (tests run on any day of the week)."""
    from datetime import time

    today = london_today()
    v = await Visits(db).update(
        visit.id,
        {"local_date": today.isoformat(), "scheduled_start": london_datetime(today, time(*hhmm))},
    )
    assert v is not None
    return v


@dataclass
class World:
    customer: Customer
    dave: Provider
    booking: Booking
    first: Visit


@pytest.fixture
async def dave(db, catalogue) -> Provider:
    return await make_dave(db)


@pytest.fixture
async def world(db, catalogue, dave) -> World:
    customer = await make_customer(db)
    booking, first = await book(db, customer, dave)
    return World(customer=customer, dave=dave, booking=booking, first=first)


@pytest.fixture
async def dave_client(app, db, dave) -> AsyncIterator[httpx.AsyncClient]:
    async with await new_client(app) as c:
        await sign_in(c, db, DAVE_PHONE)
        yield c


@asynccontextmanager
async def client_for(app, db, phone: str) -> AsyncIterator[httpx.AsyncClient]:
    """A client signed in with this phone: `async with client_for(app, db, phone) as c:`."""
    async with await new_client(app) as c:
        await sign_in(c, db, phone)
        yield c


async def accepted(db, customer: Customer, provider: Provider, **kw) -> marketplace.BookingOutcome:
    req = await make_request(db, customer, **kw)
    return await marketplace.accept_at_guide(db, make_settings(), req.ref, provider)


def tomorrow() -> date:
    return london_today() + timedelta(days=1)


__all__ = [
    "DAVE_PHONE",
    "MIKE_PHONE",
    "TOM_PHONE",
    "World",
    "accepted",
    "add_tom",
    "book",
    "client_for",
    "make_dave",
    "move_to_today",
    "tomorrow",
    "with_account",
]
