"""L1 customer endpoints (/api/c). Owner: L1.

Every endpoint starts as a 501 stub with its final request and response models. Replace
the body; keep the path, method and models (or change them additively and note it).
The offer endpoints /api/c/offers/{id}/accept|decline are shared (app/shared).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.adapters.payments.base import CardSetup
from app.core.deps import CurrentUser, current_customer, current_user
from app.core.errors import ERROR_RESPONSES, not_implemented
from app.customer.schemas import (
    BookingCard,
    BookingDetail,
    CardConfirmed,
    ChangeDateIn,
    CustomerProfile,
    CustomerVisit,
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
from app.models.customers import Customer, SavedCard
from app.shared.schemas import MessageOut, NewMessage, ThreadSummary

router = APIRouter(prefix="/api/c", tags=["L1 customer"], responses=ERROR_RESPONSES)
User = Annotated[CurrentUser, Depends(current_user)]
Cust = Annotated[Customer, Depends(current_customer)]
LANE = "L1"


# ---------------------------------------------------------------- job requests
@router.post("/requests", status_code=status.HTTP_201_CREATED)
async def create_request(body: NewRequest, user: User) -> RequestDetail:
    """Turn a quote into a job request: save the customer profile and address, check the card is
    saved, record terms acceptance, broadcast to eligible providers (alert_targets) with job_alert
    messages carrying magic links, and send request_sent."""
    not_implemented(LANE)


@router.get("/requests")
async def list_requests(customer: Cust) -> list[RequestSummary]:
    not_implemented(LANE)


@router.get("/requests/{ref}")
async def get_request(ref: str, customer: Cust) -> RequestDetail:
    """The "Finding someone local" screen polls this: timeline, pending counters, booking."""
    not_implemented(LANE)


@router.post("/requests/{ref}/cancel")
async def cancel_request(ref: str, customer: Cust) -> RequestDetail:
    not_implemented(LANE)


@router.post("/requests/{ref}/demo/simulate", status_code=status.HTTP_202_ACCEPTED)
async def simulate_responses(ref: str, customer: Cust) -> SimulationStarted:
    """DEMO_MODE only (404 otherwise): the nearest seeded provider with the skill counters at
    guide + 20% after a few seconds, and the next accepts at guide shortly after, through the
    real offer endpoints."""
    not_implemented(LANE)


# ---------------------------------------------------------------- profile and card
@router.get("/profile")
async def get_profile(customer: Cust) -> CustomerProfile:
    not_implemented(LANE)


@router.patch("/profile")
async def update_profile(body: ProfileUpdate, customer: Cust) -> CustomerProfile:
    not_implemented(LANE)


@router.post("/payment/setup")
async def start_card_setup(user: User) -> CardSetup:
    """Start saving a card through PaymentGateway.save_card_setup (fake: instantly 4242)."""
    not_implemented(LANE)


@router.post("/payment/setup/{setup_id}/confirm")
async def confirm_card_setup(setup_id: str, user: User) -> CardConfirmed:
    not_implemented(LANE)


@router.get("/payment/card")
async def get_card(customer: Cust) -> SavedCard | None:
    not_implemented(LANE)


# ---------------------------------------------------------------- bookings, visits, plans
@router.get("/bookings")
async def list_bookings(customer: Cust) -> list[BookingCard]:
    not_implemented(LANE)


@router.get("/bookings/{booking_id}")
async def get_booking(booking_id: str, customer: Cust) -> BookingDetail:
    not_implemented(LANE)


@router.post("/bookings/{booking_id}/rebook", status_code=status.HTTP_201_CREATED)
async def rebook(booking_id: str, body: RebookIn, customer: Cust) -> RequestSummary:
    """ "Book Dave again": a request offered to the same provider at the same price."""
    not_implemented(LANE)


@router.get("/visits")
async def list_visits(customer: Cust) -> VisitsOut:
    not_implemented(LANE)


@router.post("/visits/{visit_id}/skip")
async def skip_visit(visit_id: str, customer: Cust) -> CustomerVisit:
    not_implemented(LANE)


@router.post("/visits/{visit_id}/change-date")
async def change_visit_date(visit_id: str, body: ChangeDateIn, customer: Cust) -> CustomerVisit:
    not_implemented(LANE)


@router.post("/visits/{visit_id}/rating", status_code=status.HTTP_201_CREATED)
async def rate_visit(visit_id: str, body: RatingIn, customer: Cust) -> RatingOut:
    """Stars, tags and an optional tip (charged with PaymentGateway.charge_visit, purpose tip, fee 0)."""
    not_implemented(LANE)


@router.post("/visits/{visit_id}/problem", status_code=status.HTTP_201_CREATED)
async def report_problem(visit_id: str, body: ProblemIn, customer: Cust) -> ProblemOut:
    """ "Something not right?": opens a dispute (stage 0) and tells the provider."""
    not_implemented(LANE)


@router.get("/plans")
async def list_plans(customer: Cust) -> list[PlanOut]:
    not_implemented(LANE)


@router.get("/plans/{series_id}")
async def get_plan(series_id: str, customer: Cust) -> PlanOut:
    not_implemented(LANE)


@router.patch("/plans/{series_id}")
async def update_plan(series_id: str, body: PlanUpdate, customer: Cust) -> PlanOut:
    not_implemented(LANE)


@router.post("/plans/{series_id}/cancel")
async def cancel_plan(series_id: str, customer: Cust) -> PlanOut:
    not_implemented(LANE)


# ---------------------------------------------------------------- messages
@router.get("/threads")
async def list_threads(customer: Cust) -> list[ThreadSummary]:
    not_implemented(LANE)


@router.get("/threads/{thread_id}/messages")
async def list_messages(thread_id: str, customer: Cust) -> list[MessageOut]:
    not_implemented(LANE)


@router.post("/threads/{thread_id}/messages", status_code=status.HTTP_201_CREATED)
async def post_message(thread_id: str, body: NewMessage, customer: Cust) -> MessageOut:
    not_implemented(LANE)


# ---------------------------------------------------------------- own-customer invites
@router.get("/invites/{token}")
async def get_invite(token: str) -> InvitePreview:
    """Public: the invite link in the provider's text. No sign-in needed to read it."""
    not_implemented(LANE)


@router.post("/invites/{token}/accept", status_code=status.HTTP_201_CREATED)
async def accept_invite(token: str, body: InviteAccept, user: User) -> BookingCard:
    """Signed in with the invited number: creates the customer (joined_via own_customer) and a
    booking with source own_customer via app.services.bookings.create_booking."""
    not_implemented(LANE)
