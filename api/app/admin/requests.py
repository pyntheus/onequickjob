"""One request, for /admin/requests/:id (A38): what the customer asked for and how it was priced,
where it stands, every offer and counter, what's happened, the messages about it, any raise
waiting for the customer, and who could take it. The actions (the WhatsApp text, raising the
guide) are the overview's endpoints, unchanged."""

from fastapi import status

from app.adapters.area.describe import metres_text, size_phrase
from app.adapters.area.manual_bands import BANDS
from app.admin.map import coverage, nearby_pins
from app.admin.overview import WAITING_AFTER
from app.admin.schemas import (
    AdminRequestDetail,
    AnswerRow,
    BookedRow,
    LawnRow,
    LawnSize,
    OfferRow,
    RequestCoverage,
    TimelineRow,
)
from app.admin.views import age_text, money, plural
from app.core.config import Settings
from app.core.db import Db
from app.core.errors import fail
from app.core.timeutil import utcnow
from app.models.job_requests import JobRequest, RequestEvent
from app.models.quotes import Measure
from app.provider.common import answer_text, frequency_label, when_text
from app.repos import Bookings, Categories, Customers, JobRequests, Offers, Outbox, Providers, Users
from app.shared.routes import outbox_item

BAND_LABELS = {b.id: b.label for b in BANDS}
ADJUST_TEXT = {"smaller": "looks smaller", "right": "looks about right", "bigger": "looks bigger"}
UNIT_TEXT = {"strides": "strides", "m": "m", "ft": "ft"}
MESSAGES_SHOWN = 100


def lawn_size(m: Measure | None) -> LawnSize | None:
    if m is None:
        return None
    if m.method == "band":
        band = BAND_LABELS.get(m.band or "", m.band or "a size")
        method_text = f"Picked a size: {band}, {ADJUST_TEXT.get(m.adjust or 'right', 'looks about right')}"
    elif m.method == "paced":
        method_text = "Paced it out (a big stride counts as a metre)"
    else:
        method_text = f"Gave the length and width, in {'feet' if m.unit == 'ft' else 'metres'}"
    unit = UNIT_TEXT.get(m.unit or "m", "m")
    return LawnSize(
        area_m2=m.area_m2,
        summary=size_phrase(m) or "",
        method=m.method,
        method_text=method_text,
        estimator=m.estimator,
        confidence=m.confidence,
        lawns=[
            LawnRow(
                given=f"{lw.length:g} × {lw.width:g} {unit}",
                metres=f"{metres_text(lw.length_m)} × {metres_text(lw.width_m)} metres",
                area_m2=lw.area_m2,
            )
            for lw in m.lawns
        ],
    )


def event_text(e: RequestEvent, names: dict[str, str]) -> str:
    """The admin's timeline, from the request's events."""
    who = names.get(e.provider_id or "", "A provider")
    price = money(e.price_pence) if e.price_pence is not None else None
    match e.kind:
        case "created":
            return f"Requested ({e.text})" if e.text else "Requested"
        case "broadcast":
            return f"Job alert sent to {plural(e.count or 0, 'provider')}" if e.count else "No provider was alerted"
        case "viewed":
            return f"{who} looked at it"
        case "countered":
            return f"{who} suggested {price}"
        case "counter_declined":
            return f"The customer declined {who}'s price"
        case "counter_lapsed":
            return f"{who}'s suggested price lapsed"
        case "accepted":
            return f"{who} took it at {price}" if price else f"{who} took it"
        case "guide_raised":
            return f"The customer approved the raise: the guide is now {price}"
        case "price_change_proposed":
            note = f" ({e.text})" if e.text else ""
            return f"A raise to {price} was sent to the customer to approve{note}"
        case "price_change_declined":
            return f"The customer kept the guide at {price}"
        case "price_change_withdrawn":
            return f"The raise to {price} was withdrawn: it was booked first"
        case "cancelled":
            return f"Cancelled ({e.text})" if e.text else "Cancelled by the customer"
        case "expired":
            return "Closed after 7 days with nobody booked"
        case "note":
            return e.text or "Note"
    return e.kind


async def find_request(db: Db, key: str) -> JobRequest:
    """By id, or by its reference (R-2297), for a link typed by hand."""
    req = await JobRequests(db).get(key) or await JobRequests(db).find_one({"ref": key})
    if req is None:
        fail(status.HTTP_404_NOT_FOUND, "not_found", "That request wasn't found.")
    return req


async def detail(db: Db, s: Settings, key: str) -> AdminRequestDetail:
    req = await find_request(db, key)
    now = utcnow()
    cats = {c.id: c for c in await Categories(db).all()}
    cat = cats.get(req.category_id)
    names = {c.id: c.name for c in cats.values()}
    providers = await Providers(db).find({})
    shorts = {p.id: p.short for p in providers}
    customer = await Customers(db).get(req.customer_id)
    user = await Users(db).get(customer.user_id) if customer else None
    offers = await Offers(db).find({"request_id": req.id}, sort=[("created_at", -1)])
    messages = await Outbox(db).find(
        {"related.request_id": req.id}, sort=[("created_at", -1), ("_id", -1)], limit=MESSAGES_SHOWN
    )
    booked = None
    if req.booked:
        booking = await Bookings(db).get(req.booked.booking_id)
        booked = BookedRow(
            booking_id=req.booked.booking_id,
            booking_ref=booking.ref if booking else None,
            provider_id=req.booked.provider_id,
            provider_short=shorts.get(req.booked.provider_id, ""),
            price_pence=req.booked.price_pence,
            first_price_pence=req.booked.first_price_pence,
            via=req.booked.via,
            at=req.booked.at,
        )
    answers = []
    if cat is not None:
        for field in cat.intake:
            if field.type == "photos" or field.key == "frequency":  # photos and "How often" have their own rows
                continue
            text = answer_text(field, req.answers.get(field.key, field.default))
            if text:
                answers.append(AnswerRow(question=field.label, answer=text))
    cov = coverage(req, providers)
    pending = req.price_change if req.price_change and req.price_change.status == "pending" else None
    return AdminRequestDetail(
        request_id=req.id,
        ref=req.ref,
        status=req.status,
        created_at=req.created_at,
        age_text=age_text(req.created_at, now),
        waiting=req.status == "open" and req.created_at <= now - WAITING_AFTER,
        category_id=req.category_id,
        category_name=names.get(req.category_id, req.category_id),
        customer_name=customer.name if customer else "Not known",
        customer_phone=user.phone if user else None,
        address=req.address,
        when_text=when_text(req.when),
        frequency_text=frequency_label(req.frequency),
        unit=req.unit,
        guide_pence=req.guide_pence,
        first_pence=req.first_pence,
        mins=req.mins,
        first_mins=req.first_mins,
        answers=answers,
        notes=req.notes,
        photos=len(req.photos),
        lawn=lawn_size(req.measure),
        cover=req.cover_for_visit_id is not None,
        direct_provider_short=shorts.get(req.direct_provider_id) if req.direct_provider_id else None,
        admin_note=req.admin_note,
        booked=booked,
        offers=[
            OfferRow(
                id=o.id,
                provider_id=o.provider_id,
                provider_short=shorts.get(o.provider_id, ""),
                price_pence=o.price_pence,
                first_price_pence=o.first_price_pence,
                guide_pence=o.guide_pence,
                status=o.status,
                reasons=o.reasons,
                message=o.message,
                created_at=o.created_at,
                decided_at=o.decided_at,
            )
            for o in offers
        ],
        timeline=[
            TimelineRow(at=e.at, kind=e.kind, text=event_text(e, shorts))
            for e in sorted(req.events, key=lambda e: e.at)
        ],
        # Outside DEMO_MODE, as on the admin outbox, a sign-in code is never shown.
        messages=[outbox_item(m, redact_codes=not s.demo_mode) for m in messages],
        price_change=pending,
        coverage=RequestCoverage(
            in_reach=cov.in_reach,
            in_reach_doing_it=cov.doing_it,
            uncovered=cov.uncovered,
            nearby=nearby_pins(cov, names),
        ),
    )
