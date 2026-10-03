"""Shared set-up for L1's tests: a signed-in customer with a card, quotes, requests made through
the real endpoint, and bookings made through the marketplace."""

from datetime import timedelta

import httpx

from app.core.timeutil import utcnow
from app.models.common import Address
from app.repos import Customers, JobRequests, Visits
from app.services import marketplace
from tests.conftest import make_settings, sign_in
from tests.factories import HAZLEMERE

SARAH = "+447700900123"


def address(**over) -> dict:
    return Address(**{**HAZLEMERE.model_dump(), **over}).model_dump(mode="json")


async def signed_in_with_card(client: httpx.AsyncClient, db, phone: str = SARAH, name: str = "Sarah Whitfield") -> dict:
    me = await sign_in(client, db, phone, name)
    r = await client.post("/api/c/payment/setup")
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/c/payment/setup/{r.json()['setup_id']}/confirm")
    assert r.status_code == 200, r.text
    return me


async def quote(client: httpx.AsyncClient, category_id: str = "mowing", answers: dict | None = None, **lawn) -> dict:
    body: dict = {"category_id": category_id, "answers": answers or {}}
    if category_id == "mowing":
        body["lawn"] = lawn or {"band": "large", "adjust": "right"}
    r = await client.post("/api/quotes", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def request_body(quote_id: str, **over) -> dict:
    body = {
        "quote_id": quote_id,
        "address": address(),
        "notes": "The side gate sticks.",
        "when": {"days": "weekdays", "time": "morning"},
        "contact": {"name": "Sarah Whitfield", "email": None},
        "agree_terms": True,
    }
    return {**body, **over}


async def make_request_via_api(client: httpx.AsyncClient, category_id: str = "mowing", **over) -> dict:
    q = await quote(client, category_id)
    r = await client.post("/api/c/requests", json=request_body(q["id"], **over))
    assert r.status_code == 201, r.text
    return r.json()


async def book_at_guide(db, ref: str, provider) -> marketplace.BookingOutcome:
    return await marketplace.accept_at_guide(db, make_settings(), ref, provider)


async def customer_of(db, phone: str = SARAH):
    from app.repos import Users

    user = await Users(db).by_phone(phone)
    return await Customers(db).by_user(user.id)


async def finish_visit(db, visit_id: str, *, ago: timedelta = timedelta(hours=2), minutes: int = 40) -> None:
    """What L2's finish endpoint records, written directly (test-only)."""
    at = utcnow() - ago
    await Visits(db).update(
        visit_id,
        {
            "status": "finished",
            "started_at": at - timedelta(minutes=minutes),
            "finished_at": at,
            "minutes_actual": minutes,
        },
    )


async def request_by_ref(db, ref: str):
    return await JobRequests(db).by_ref(ref)
