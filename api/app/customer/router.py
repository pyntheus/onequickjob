"""L1 customer endpoints (/api/c). Owner: L1.

Endpoints keep the paths, methods and models from foundations (some models gained optional
fields). The offer endpoints /api/c/offers/{id}/accept|decline are shared (app/shared).
Logic lives in the modules beside this one: requests, simulator, account, threads, invites,
views (read-only presenters).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.adapters.payments.base import CardSetup, CustomerRef, PaymentGateway
from app.core.config import Settings
from app.core.db import Db, get_db
from app.core.deps import CurrentUser, current_customer, current_user, gateway_dep, settings_dep
from app.core.errors import ERROR_RESPONSES, fail, not_found
from app.customer import account, invites, requests, simulator, threads
from app.customer import templates as _templates  # noqa: F401 (registers L1's outbox templates)
from app.customer.schemas import (
    BookingCard,
    BookingDetail,
    CardConfirmed,
    ChangeDateIn,
    CustomerProfile,
    CustomerVisit,
    FeeExample,
    InviteAccept,
    InvitePreview,
    NewRequest,
    PlanOut,
    PlanUpdate,
    ProblemIn,
    ProblemOut,
    ProfileUpdate,
    RatingIn,
    RatingOut,
    RebookIn,
    RequestDetail,
    RequestSummary,
    SimulationStarted,
    VisitsOut,
)
from app.customer.views import (
    Lookup,
    booking_card,
    booking_detail,
    fee_split,
    plan_view,
    request_detail,
    request_summary,
    visit_views,
)
from app.models.customers import Customer, CustomerPayment, SavedCard
from app.models.users import User
from app.repos.bookings import Bookings
from app.repos.customers import Customers
from app.repos.job_requests import JobRequests
from app.repos.own_customer_invites import OwnCustomerInvites
from app.repos.series import SeriesRepo
from app.repos.users import Users
from app.repos.visits import Visits
from app.shared.schemas import MessageOut, NewMessage, ThreadSummary

router = APIRouter(prefix="/api/c", tags=["L1 customer"], responses=ERROR_RESPONSES)
User_ = Annotated[CurrentUser, Depends(current_user)]
Cust = Annotated[Customer, Depends(current_customer)]
DbDep = Annotated[Db, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
Gateway = Annotated[PaymentGateway, Depends(gateway_dep)]
LANE = "L1"
UPCOMING_LIMIT = 12
DONE_LIMIT = 20


async def _user(db: Db, customer: Customer) -> User:
    user = await Users(db).get(customer.user_id)
    assert user is not None, customer.user_id
    return user


async def _own_request(db: Db, ref: str, customer: Customer):
    req = await JobRequests(db).by_ref(ref)
    if req is None or req.customer_id != customer.id:
        not_found("That request")
    return req


# ---------------------------------------------------------------- landing
@router.get("/fees/example")
async def fee_example(s: SettingsDep, price_pence: Annotated[int, Query(ge=100, le=100_000)] = 3000) -> FeeExample:
    """ "Where your money goes" on the landing page: the split of an example price, from money.py."""
    return FeeExample(split=fee_split(price_pence, "standard", s))


# ---------------------------------------------------------------- job requests
@router.post("/requests", status_code=status.HTTP_201_CREATED)
async def create_request(body: NewRequest, user: User_, db: DbDep, s: SettingsDep) -> RequestDetail:
    """Turn a quote into a job request: save the customer profile and address, check the card is
    saved, record terms acceptance, broadcast to eligible providers (alert_targets) with job_alert
    messages carrying magic links, and send request_sent."""
    req = await requests.create_request(db, s, user.user, body)
    return await request_detail(db, req, demo=s.demo_mode)


@router.get("/requests")
async def list_requests(customer: Cust, db: DbDep) -> list[RequestSummary]:
    look = Lookup(db)
    found = await JobRequests(db).find({"customer_id": customer.id}, sort=[("created_at", -1)], limit=50)
    return [request_summary(r, await look.cat(r.category_id)) for r in found if not r.cover_for_visit_id]


@router.get("/requests/{ref}")
async def get_request(ref: str, customer: Cust, db: DbDep, s: SettingsDep) -> RequestDetail:
    """The "Finding someone local" screen polls this: timeline, pending counters, booking."""
    req = await _own_request(db, ref, customer)
    return await request_detail(db, req, demo=s.demo_mode, simulating=s.demo_mode and simulator.running(req.id))


@router.post("/requests/{ref}/cancel")
async def cancel_request(ref: str, customer: Cust, db: DbDep, s: SettingsDep) -> RequestDetail:
    req = await _own_request(db, ref, customer)
    updated = await requests.cancel_request(db, s, req, customer, await _user(db, customer))
    return await request_detail(db, updated, demo=s.demo_mode)


@router.post("/requests/{ref}/demo/simulate", status_code=status.HTTP_202_ACCEPTED)
async def simulate_responses(
    ref: str, request: Request, customer: Cust, db: DbDep, s: SettingsDep
) -> SimulationStarted:
    """DEMO_MODE only (404 otherwise): the nearest seeded provider with the skill counters at
    guide + 20% after a few seconds, and the next accepts at guide shortly after, through the
    real offer endpoints."""
    if not s.demo_mode:
        not_found("That page")
    req = await _own_request(db, ref, customer)
    cat = await Lookup(db).cat(req.category_id)
    return await simulator.start(request.app, db, s, req, cat)


# ---------------------------------------------------------------- profile and card
def _profile(customer: Customer, user: User) -> CustomerProfile:
    return CustomerProfile(
        customer_id=customer.id,
        name=customer.name,
        phone=user.phone,
        email=user.email,
        addresses=customer.addresses,
        card=customer.payment.card if customer.payment else None,
    )


@router.get("/profile")
async def get_profile(customer: Cust, db: DbDep) -> CustomerProfile:
    return _profile(customer, await _user(db, customer))


@router.patch("/profile")
async def update_profile(body: ProfileUpdate, customer: Cust, db: DbDep) -> CustomerProfile:
    user = await _user(db, customer)
    if body.name is not None:
        customer = await Customers(db).update(customer.id, {"name": body.name.strip()}) or customer
        user = await Users(db).update(user.id, {"name": body.name.strip()}) or user
    if body.email is not None:
        email = body.email.strip().lower() or None
        if email:
            other = await Users(db).by_email(email)
            if other and other.id != user.id:
                fail(status.HTTP_409_CONFLICT, "email_in_use", "That email belongs to another account.")
        user = await Users(db).update(user.id, {"email": email}) or user
    return _profile(customer, user)


async def _customer_for_card(db: Db, user: User) -> Customer:
    """The customer record, created on first use: someone saving a card on the contact screen
    (or the invite screen) may not have one yet. A person with an open invite from a provider
    joined through that provider (decisions.md: the invite-only rule)."""
    customer = await Customers(db).by_user(user.id)
    if customer is not None:
        return customer
    invite = await OwnCustomerInvites(db).find_one({"phone": user.phone, "status": "invited"}) if user.phone else None
    await Users(db).add_role(user.id, "customer")
    return await Customers(db).insert_once(
        Customer(
            user_id=user.id,
            name=user.name,
            joined_via="own_customer" if invite else "platform",
            invited_by_provider_id=invite.provider_id if invite else None,
        ),
        {"user_id": user.id},
    )


@router.post("/payment/setup")
async def start_card_setup(user: User_, db: DbDep, gateway: Gateway) -> CardSetup:
    """Start saving a card through PaymentGateway.save_card_setup (fake: instantly 4242)."""
    customer = await _customer_for_card(db, user.user)
    payment = customer.payment
    setup = await gateway.save_card_setup(
        CustomerRef(
            customer_id=customer.id,
            name=customer.name or user.user.name,
            email=user.user.email,
            phone=user.user.phone,
            gateway_customer_id=payment.gateway_customer_id if payment and payment.gateway == gateway.name else None,
        )
    )
    await Customers(db).set_payment(
        customer.id,
        CustomerPayment(
            gateway=setup.gateway,
            gateway_customer_id=setup.gateway_customer_id,
            setup_id=setup.setup_id,
            setup_status="pending",
            card=payment.card if payment and payment.gateway == setup.gateway else None,
        ),
    )
    return setup


@router.post("/payment/setup/{setup_id}/confirm")
async def confirm_card_setup(setup_id: str, user: User_, db: DbDep, gateway: Gateway) -> CardConfirmed:
    customer = await Customers(db).by_user(user.id)
    if customer is None or customer.payment is None or customer.payment.setup_id != setup_id:
        not_found("That card setup")
    result = await gateway.card_setup_status(setup_id)
    if result.status != "succeeded" or result.card is None:
        failed = result.status == "failed"
        await Customers(db).set_payment(
            customer.id, customer.payment.model_copy(update={"setup_status": "failed" if failed else "pending"})
        )
        fail(
            status.HTTP_409_CONFLICT,
            "card_not_saved",
            result.failure_reason or "Your card isn't saved yet. Please try again.",
        )
    card = SavedCard(**result.card.model_dump())
    await Customers(db).set_payment(
        customer.id, customer.payment.model_copy(update={"setup_status": "succeeded", "card": card})
    )
    return CardConfirmed(card=result.card)


@router.get("/payment/card")
async def get_card(customer: Cust) -> SavedCard | None:
    return customer.payment.card if customer.payment else None


# ---------------------------------------------------------------- bookings, visits, plans
@router.get("/bookings")
async def list_bookings(customer: Cust, db: DbDep, s: SettingsDep) -> list[BookingCard]:
    look = Lookup(db)
    found = await Bookings(db).find({"customer_id": customer.id}, sort=[("created_at", -1)], limit=50)
    return [await booking_card(db, s, b, look) for b in found]


@router.get("/bookings/{booking_id}")
async def get_booking(booking_id: str, customer: Cust, db: DbDep, s: SettingsDep) -> BookingDetail:
    booking = await account.own_booking(db, booking_id, customer)
    return await booking_detail(db, s, booking, Lookup(db))


@router.post("/bookings/{booking_id}/rebook", status_code=status.HTTP_201_CREATED)
async def rebook(booking_id: str, body: RebookIn, customer: Cust, db: DbDep, s: SettingsDep) -> RequestSummary:
    """ "Book Dave again": a request offered to the same provider at the same price."""
    booking = await account.own_booking(db, booking_id, customer)
    req = await account.rebook(db, s, booking, customer, await _user(db, customer), body)
    return request_summary(req, await Lookup(db).cat(req.category_id))


async def _visit_view(db: Db, visit_id: str) -> CustomerVisit:
    visit = await Visits(db).get(visit_id)
    assert visit is not None
    booking = await Bookings(db).get(visit.booking_id)
    return (await visit_views(db, [visit], Lookup(db), {booking.id: booking} if booking else {}))[0]


@router.get("/visits")
async def list_visits(customer: Cust, db: DbDep) -> VisitsOut:
    visits = Visits(db)
    upcoming = await visits.find(
        {"customer_id": customer.id, "status": {"$in": ["scheduled", "in_progress"]}},
        sort=[("scheduled_start", 1)],
        limit=UPCOMING_LIMIT,
    )
    done = await visits.find(
        {"customer_id": customer.id, "status": {"$in": ["finished", "skipped"]}},
        sort=[("scheduled_start", -1)],
        limit=DONE_LIMIT,
    )
    ids = list({v.booking_id for v in upcoming + done})
    bookings = {b.id: b for b in await Bookings(db).find({"_id": {"$in": ids}})}
    look = Lookup(db)
    up = await visit_views(db, upcoming, look, bookings)
    return VisitsOut(next_visit=up[0] if up else None, upcoming=up, done=await visit_views(db, done, look, bookings))


@router.get("/visits/{visit_id}")
async def get_visit(visit_id: str, customer: Cust, db: DbDep) -> CustomerVisit:
    """One visit, for the rate screen. (Added by L1.)"""
    visit = await account.own_visit(db, visit_id, customer)
    return await _visit_view(db, visit.id)


@router.post("/visits/{visit_id}/skip")
async def skip_visit(visit_id: str, customer: Cust, db: DbDep, s: SettingsDep) -> CustomerVisit:
    visit = await account.own_visit(db, visit_id, customer)
    await account.skip_visit(db, s, visit, customer, await _user(db, customer))
    return await _visit_view(db, visit.id)


@router.post("/visits/{visit_id}/change-date")
async def change_visit_date(
    visit_id: str, body: ChangeDateIn, customer: Cust, db: DbDep, s: SettingsDep
) -> CustomerVisit:
    visit = await account.own_visit(db, visit_id, customer)
    await account.change_date(db, s, visit, customer, await _user(db, customer), body)
    return await _visit_view(db, visit.id)


@router.post("/visits/{visit_id}/rating", status_code=status.HTTP_201_CREATED)
async def rate_visit(
    visit_id: str, body: RatingIn, customer: Cust, db: DbDep, s: SettingsDep, gateway: Gateway
) -> RatingOut:
    """Stars, tags and an optional tip (charged with PaymentGateway.charge_visit, purpose tip, fee 0)."""
    visit = await account.own_visit(db, visit_id, customer)
    rating, tip_status = await account.rate_visit(db, s, gateway, visit, customer, await _user(db, customer), body)
    message = None
    if tip_status == "pending":
        message = "Your rating is saved. The tip is still going through: we'll keep trying, and it's only taken once."
    elif tip_status == "failed":
        stored = await Visits(db).get(visit.id)
        reason = stored.tip_charge.failure_reason if stored and stored.tip_charge else None
        message = f"Your rating is saved, but the tip didn't go through{': ' + reason if reason else '.'}"
    return RatingOut(
        id=rating.id,
        visit_id=visit.id,
        stars=rating.stars,
        tags=rating.tags,
        tip_pence=rating.tip_pence,
        tip_status=tip_status,  # type: ignore[arg-type]
        tip_message=message,
    )


@router.post("/visits/{visit_id}/problem", status_code=status.HTTP_201_CREATED)
async def report_problem(visit_id: str, body: ProblemIn, customer: Cust, db: DbDep, s: SettingsDep) -> ProblemOut:
    """ "Something not right?": opens a dispute (stage 0) and tells the provider."""
    visit = await account.own_visit(db, visit_id, customer)
    dispute = await account.report_problem(db, s, visit, customer, await _user(db, customer), body)
    return ProblemOut(dispute_id=dispute.id, ref=dispute.ref, status_text=dispute.status_text)


@router.get("/plans")
async def list_plans(customer: Cust, db: DbDep) -> list[PlanOut]:
    look = Lookup(db)
    out = []
    for series in await SeriesRepo(db).find({"customer_id": customer.id}, sort=[("created_at", -1)]):
        booking = await Bookings(db).get(series.booking_id)
        if booking:
            out.append(await plan_view(db, series, booking, look))
    return out


@router.get("/plans/{series_id}")
async def get_plan(series_id: str, customer: Cust, db: DbDep) -> PlanOut:
    series, booking = await account.own_series(db, series_id, customer)
    return await plan_view(db, series, booking, Lookup(db))


@router.patch("/plans/{series_id}")
async def update_plan(series_id: str, body: PlanUpdate, customer: Cust, db: DbDep, s: SettingsDep) -> PlanOut:
    series, booking = await account.own_series(db, series_id, customer)
    updated = await account.update_plan(db, s, series, booking, customer, await _user(db, customer), body)
    return await plan_view(db, updated, booking, Lookup(db))


@router.post("/plans/{series_id}/cancel")
async def cancel_plan(series_id: str, customer: Cust, db: DbDep, s: SettingsDep) -> PlanOut:
    series, booking = await account.own_series(db, series_id, customer)
    updated = await account.cancel_plan(db, s, series, booking, customer, await _user(db, customer))
    return await plan_view(db, updated, await Bookings(db).get(booking.id) or booking, Lookup(db))


# ---------------------------------------------------------------- messages
@router.get("/threads")
async def list_threads(customer: Cust, db: DbDep) -> list[ThreadSummary]:
    return await threads.summaries(db, await _user(db, customer))


@router.get("/threads/{thread_id}/messages")
async def list_messages(thread_id: str, customer: Cust, db: DbDep) -> list[MessageOut]:
    user = await _user(db, customer)
    return await threads.messages(db, await threads.own_thread(db, thread_id, user), user)


@router.post("/threads/{thread_id}/messages", status_code=status.HTTP_201_CREATED)
async def post_message(thread_id: str, body: NewMessage, customer: Cust, db: DbDep, s: SettingsDep) -> MessageOut:
    user = await _user(db, customer)
    return await threads.post(db, s, await threads.own_thread(db, thread_id, user), user, body.body)


# ---------------------------------------------------------------- own-customer invites
@router.get("/invites/{token}")
async def get_invite(token: str, db: DbDep, s: SettingsDep) -> InvitePreview:
    """Public: the invite link in the provider's text. No sign-in needed to read it."""
    return await invites.preview(db, s, await invites.find(db, s, token))


@router.post("/invites/{token}/accept", status_code=status.HTTP_201_CREATED)
async def accept_invite(token: str, body: InviteAccept, user: User_, db: DbDep, s: SettingsDep) -> BookingCard:
    """Signed in with the invited number: creates the customer (joined_via own_customer) and a
    booking with source own_customer via app.services.bookings.create_booking, in one
    transaction with marking the invite accepted and its messages."""
    booking = await invites.accept(db, s, await invites.find(db, s, token), user.user, body)
    return await booking_card(db, s, booking, Lookup(db))
