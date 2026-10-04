"""New jobs near the provider, the offer screen and what a suggested price means.

Accepting at the guide price and suggesting a price are the shared endpoints built in F
(app.services.marketplace). This module only reads, except for recording that a provider
has opened a job (JobRequests.record_view).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.core import money
from app.core.config import Settings
from app.core.db import Db
from app.core.errors import not_found
from app.core.rounding import D, round_to_pound
from app.core.timeutil import london_today, utcnow, weekday_key
from app.models.categories import Category
from app.models.common import Address
from app.models.job_requests import JobRequest, RequestEvent
from app.models.offers import Offer
from app.models.providers import Provider
from app.models.visits import Visit
from app.provider.common import categories, facts_for, frequency_label, miles, one_dp, short_name
from app.provider.schemas import CounterPreview, CustomerMeta, Fact, JobCard, JobOffer
from app.repos.bookings import Bookings
from app.repos.customers import Customers
from app.repos.job_requests import JobRequests
from app.repos.offers import Offers
from app.repos.providers import Providers
from app.repos.quotes import Quotes
from app.repos.visits import Visits
from app.services import marketplace, schedule, wording
from app.services.eligibility import LimitStatus, can_take_request, limit_status, over_limit

RECENT = timedelta(days=3)  # how long a job you booked, or lost, stays on your list
ROUTE_DAYS = 14  # how far ahead "fits your round" looks
ROUTE_MILES = 1.0

COUNTER_REASONS: dict[str, list[str]] = {
    "mowing": ["Longer grass than described", "Tricky access", "More waste than described"],
    "hedges": ["Taller or longer than described", "Tricky access", "More waste than described"],
    "clearance": ["More waste than described", "Tricky access", "Extra trips to the tip"],
    "outside": ["Bigger job than described", "Tricky access"],
    "inside": ["Bigger job than described", "Needs extra materials"],
    "help": ["Takes longer than described"],
}
FAR_REASON = "Further than I usually go"


# ------------------------------------------------------------------ the provider's round, for route hints


@dataclass(frozen=True)
class Stop:
    visit: Visit
    address: Address


async def upcoming_stops(db: Db, provider: Provider, today: date) -> list[Stop]:
    """Visits the provider will do themself in the next fortnight, with their addresses."""
    visits = await Visits(db).find(
        {
            "provider_id": provider.id,
            "status": "scheduled",
            "performer.kind": {"$ne": "helper"},
            "local_date": {"$gt": today.isoformat(), "$lte": (today + timedelta(days=ROUTE_DAYS)).isoformat()},
        },
        sort=[("scheduled_start", 1)],
    )
    ids = list({v.booking_id for v in visits})
    addresses = {b.id: b.address for b in await Bookings(db).find({"_id": {"$in": ids}})} if ids else {}
    return [Stop(v, addresses[v.booking_id]) for v in visits if v.booking_id in addresses]


def route_hint(
    stops: list[Stop], provider: Provider, req: JobRequest, today: date, cover_day: date | None = None
) -> str | None:
    """Another of their visits within a mile, on a day this job could be done: "0.4 miles from
    your 9:00 on Tuesday". The earliest such visit wins. A cover is for one fixed day."""
    for stop in stops:
        day = stop.visit.local_date
        if weekday_key(day) not in provider.working_days or not schedule.suits(day, req.when.days):
            continue
        if cover_day is not None and day != cover_day:
            continue
        d = miles(stop.address, req.address.lat, req.address.lng)
        if d <= ROUTE_MILES:
            when = wording.time_text(stop.visit.scheduled_start)
            on = f"{day:%A}" if day - today < timedelta(days=7) else wording.day_text(day)
            return f"{max(one_dp(d), 0.1)} miles from your {when} on {on}"
    return None


async def cover_days(db: Db, reqs: list[JobRequest]) -> dict[str, date]:
    """request id -> the day of the visit it covers, for visits still happening."""
    ids = {r.cover_for_visit_id: r.id for r in reqs if r.cover_for_visit_id}
    if not ids:
        return {}
    found = await Visits(db).find({"_id": {"$in": list(ids)}, "status": "scheduled"})
    return {ids[v.id]: v.local_date for v in found}


# ------------------------------------------------------------------ job cards


def _state(req: JobRequest, provider: Provider, mine: Offer | None) -> str | None:
    if req.status == "booked" and req.booked is not None:
        return "yours" if req.booked.provider_id == provider.id else ("taken" if mine else None)
    if mine is None:
        return None
    if mine.status == "pending":
        return "countered"
    if mine.status == "lapsed" and req.status == "open":
        return "lapsed"
    return None


def card(
    s: Settings,
    req: JobRequest,
    cat: Category,
    provider: Provider,
    lim: LimitStatus,
    stops: list[Stop],
    mine: Offer | None,
    today: date,
    cover_day: date | None = None,
) -> JobCard:
    state = _state(req, provider, mine)
    split = money.split_for_source(req.guide_pence, "platform", s)
    open_ = req.status == "open"
    return JobCard(
        request_ref=req.ref,
        category_id=cat.id,
        category_name=cat.name,
        area=req.address.area,
        district=req.address.district,
        miles=one_dp(miles(req.address, provider.home.location.lat, provider.home.location.lng)),
        mins=req.mins,
        frequency_label=f"Cover, {wording.day_text(cover_day)}" if cover_day else frequency_label(req.frequency),
        guide_pence=req.guide_pence,
        provider_pence=split.provider_pence,
        unit=req.unit,
        posted_at=req.created_at,
        route_hint=route_hint(stops, provider, req, today, cover_day) if open_ else None,
        state=state,  # type: ignore[arg-type]
        over_limit=open_ and state != "yours" and over_limit(lim, req.guide_pence),
        is_cover=bool(req.cover_for_visit_id),
        cover_date=cover_day,
    )


async def _cover_of_own_visit(db: Db, provider: Provider, req: JobRequest) -> bool:
    if not req.cover_for_visit_id:
        return False
    v = await Visits(db).get(req.cover_for_visit_id)
    return v is not None and (v.cover.original_provider_id or v.provider_id) == provider.id


async def list_jobs(db: Db, s: Settings, provider: Provider, today: date | None = None) -> list[JobCard]:
    """Open jobs this provider can take (eligibility.can_take) near them (within their travel
    radius, or alerted to them, or already priced by them), nearest first and over-limit
    marked; then the jobs they booked or lost in the last few days."""
    today = today or london_today()
    cats = await categories(db)
    since = utcnow() - RECENT
    mine_by_request: dict[str, Offer] = {}
    for o in await Offers(db).find(
        {"provider_id": provider.id, "created_at": {"$gte": since}}, sort=[("created_at", 1)]
    ):
        mine_by_request[o.request_id] = o  # the latest offer per request wins
    lim = await limit_status(db, provider, today)
    stops = await upcoming_stops(db, provider, today)
    home = provider.home.location

    actionable: list[JobCard] = []
    open_reqs = await JobRequests(db).open_for_category(provider.skills)
    days = await cover_days(db, open_reqs)
    for req in open_reqs:
        cat = cats.get(req.category_id)
        if cat is None or (req.direct_provider_id and req.direct_provider_id != provider.id):
            continue
        if not can_take_request(provider, cat, req, today).ok or await _cover_of_own_visit(db, provider, req):
            continue
        if req.cover_for_visit_id and req.id not in days:
            continue  # the visit it covers isn't happening any more
        near = miles(req.address, home.lat, home.lng) <= provider.travel_radius_miles
        alerted = req.broadcast is not None and provider.id in req.broadcast.provider_ids
        if near or alerted or req.id in mine_by_request or req.direct_provider_id == provider.id:
            actionable.append(
                card(s, req, cat, provider, lim, stops, mine_by_request.get(req.id), today, days.get(req.id))
            )
    actionable.sort(key=lambda c: c.miles)

    seen = {c.request_ref for c in actionable}
    recent: list[tuple[object, JobCard]] = []
    booked = await JobRequests(db).find(
        {"status": "booked", "booked.provider_id": provider.id, "booked.at": {"$gte": since}}
    )
    others = await JobRequests(db).find({"_id": {"$in": list(mine_by_request)}})
    days = await cover_days(db, [*booked, *others])
    for req in [*booked, *others]:
        cat = cats.get(req.category_id)
        if cat is None or req.ref in seen:
            continue
        c = card(s, req, cat, provider, lim, stops, mine_by_request.get(req.id), today, days.get(req.id))
        if c.state in ("yours", "taken", "lapsed"):
            seen.add(req.ref)
            recent.append((req.booked.at if req.booked else req.updated_at, c))
    recent.sort(key=lambda t: t[0], reverse=True)  # type: ignore[arg-type,return-value]
    return actionable + [c for _, c in recent]


# ------------------------------------------------------------------ the offer screen


async def _request_for(db: Db, provider: Provider, ref: str) -> JobRequest:
    req = await JobRequests(db).by_ref(ref)
    if req is None or (req.direct_provider_id and req.direct_provider_id != provider.id):
        not_found("That job")  # a job offered to someone else is private
    return req


def _customer_meta(name: str, initials: str, bookings: int, card_saved: bool) -> CustomerMeta:
    past = "First booking" if bookings == 0 else f"{bookings} past booking{'s' if bookings != 1 else ''}"
    return CustomerMeta(initials=initials, name=short_name(name), meta=past + (", pays by card" if card_saved else ""))


async def first_visit_text(db: Db, visit: Visit) -> str:
    """Added to Tuesday 29 September at 10:30, straight after Widmer End."""
    when = wording.when_text(visit.scheduled_start, False)
    before = [
        v
        for v in await Visits(db).for_provider_day(visit.provider_id, visit.local_date)
        if v.id != visit.id and v.scheduled_start < visit.scheduled_start and v.performer.kind != "helper"
    ]
    if before:
        prev = before[-1]
        gap = visit.scheduled_start - (prev.scheduled_start + timedelta(minutes=prev.est_mins))
        booking = await Bookings(db).get(prev.booking_id)
        if booking and gap <= timedelta(minutes=60):
            return f"Added to {when}, straight after {booking.address.area}."
    return f"Added to {when}."


def _counter_note(req: JobRequest, mine: Offer | None, provider: Provider, cat: Category, s: Settings) -> str | None:
    if mine is None or mine.status in ("pending", "accepted", "withdrawn"):
        return None
    price = wording.money(mine.price_pence)
    if mine.status == "declined" and req.status == "open":
        return (
            f"The customer would rather wait for the guide price, so your {price} wasn't taken. "
            f"The job's still open if you'd like it at {wording.money(req.guide_pence)}."
        )
    if mine.status == "lapsed" and req.status == "open":
        if can_take_request(provider, cat, req).ok:
            return (
                f"Your suggested price of {price} lapsed while you couldn't take jobs like this. "
                "You can accept the guide price, or suggest a price again."
            )
        return f"Your suggested price of {price} lapsed because you can't take this job at the moment."
    return None


async def job_offer(db: Db, s: Settings, provider: Provider, ref: str) -> JobOffer:
    req = await _request_for(db, provider, ref)
    cats = await categories(db)
    cat = cats[req.category_id]
    today = london_today()
    if req.status == "open":
        await JobRequests(db).record_view(
            req.id, provider.id, RequestEvent(at=utcnow(), kind="viewed", provider_id=provider.id)
        )
    offers = await Offers(db).find({"request_id": req.id, "provider_id": provider.id}, sort=[("created_at", 1)])
    mine = offers[-1] if offers else None
    lim = await limit_status(db, provider, today)
    stops = await upcoming_stops(db, provider, today)
    cover_visit = await Visits(db).get(req.cover_for_visit_id) if req.cover_for_visit_id else None
    cover_day = cover_visit.local_date if cover_visit else None
    the_card = card(s, req, cat, provider, lim, stops, mine, today, cover_day)

    elig = can_take_request(provider, cat, req, today)
    reasons = list(elig.reasons)
    own_cover = await _cover_of_own_visit(db, provider, req)
    if own_cover:
        reasons.append("This is cover for your own visit.")
    dead_cover = cover_visit is not None and cover_visit.status != "scheduled"
    if dead_cover:
        reasons.append("The visit this covers isn't happening any more.")
    booked_by_me = req.status == "booked" and req.booked is not None and req.booked.provider_id == provider.id

    customer = await Customers(db).get(req.customer_id)
    past = await Bookings(db).count({"customer_id": req.customer_id}) if customer else 0
    name = customer.name if customer else "Customer"
    meta = _customer_meta(
        name,
        "".join(w[0] for w in name.split()[:2]).upper(),
        past,
        bool(customer and customer.payment and customer.payment.card),
    )

    split = money.split_for_source(req.guide_pence, "platform", s)
    first_split = money.split_for_source(req.first_pence, "platform", s) if req.first_pence else None
    quote = await Quotes(db).get(req.quote_id) if req.quote_id else None
    remaining = lim.remaining_pence
    over_by = split.provider_pence - remaining if remaining is not None and split.provider_pence > remaining else None

    first_text = address_line = None
    first_day = None
    if booked_by_me and req.booked is not None:
        if cover_visit is not None:
            visit = await Visits(db).get(cover_visit.id)
        else:
            visit = await Visits(db).find_one({"booking_id": req.booked.booking_id, "is_first": True})
        if visit is not None:
            first_text = await first_visit_text(db, visit)
            first_day = visit.local_date
        address_line = req.address.label or f"{req.address.line1}, {req.address.area}"

    cover_text = None
    if cover_visit is not None:
        regular = await Providers(db).get(cover_visit.cover.original_provider_id or cover_visit.provider_id)
        who = regular.short if regular else "another provider"
        cover_text = (
            f"Cover for {who}'s regular customer on {wording.day_text(cover_visit.local_date)}, "
            f"at the usual price. They stay {who.split(' ')[0]}'s customer afterwards."
        )

    lo, hi = marketplace.counter_bounds(req.guide_pence)
    start = min(hi, max(lo, round_to_pound(D(req.guide_pence) * D("1.2"))))
    reasons_for = COUNTER_REASONS.get(cat.id) or COUNTER_REASONS[cat.group]
    can = elig.ok and not own_cover and not dead_cover and req.status == "open"
    return JobOffer(
        card=the_card,
        approx=req.approx,
        facts=[Fact(label=k, value=v) for k, v in facts_for(cat, req.answers, req.measure, req.when, req.mins)],
        note=req.notes or None,
        customer=meta,
        fee_percent=split.rate_percent,
        my_counter=mine if mine is not None and mine.status == "pending" else None,
        can_take=can,
        missing_documents=elig.missing_documents,
        over_limit_by_pence=over_by if req.status == "open" else None,
        booked_by_me=booked_by_me,
        first_visit_text=first_text,
        request_status=req.status,
        unit=req.unit,
        first_pence=req.first_pence,
        first_provider_pence=first_split.provider_pence if first_split else None,
        first_reason=quote.result.first_reason if quote else None,
        is_cover=bool(req.cover_for_visit_id),
        cover_text=cover_text,
        can_counter=can and not req.cover_for_visit_id,
        counter_min_pence=lo,
        counter_max_pence=hi,
        counter_start_pence=start,
        counter_reasons=[*reasons_for, FAR_REASON],
        counter_note=_counter_note(req, mine, provider, cat, s),
        not_eligible_reasons=reasons,
        address_line=address_line,
        first_visit_date=first_day,
    )


def _price_words(price_pence: int, unit: str) -> str:
    return wording.money(price_pence) + ("" if unit == "one-off" else f" {unit}")


async def counter_preview(db: Db, s: Settings, provider: Provider, ref: str, price_pence: int) -> CounterPreview:
    """What a suggested price means before it's sent (A1): the per-visit price the provider
    sets, the first-visit price it scales to (marketplace.scaled_first_price) and what the
    provider would get for each (money.split)."""
    req = await _request_for(db, provider, ref)
    lo, hi = marketplace.counter_bounds(req.guide_pence)
    problem = None
    if price_pence % 100 or not lo <= price_pence <= hi:
        problem = f"Suggest a whole-pound price between {wording.money(lo)} and {wording.money(hi)}."
    elif price_pence == req.guide_pence:
        problem = "That's the guide price. Accept it instead."
    elif req.cover_for_visit_id:
        problem = "Cover is at the regular price."
    first = marketplace.scaled_first_price(req.guide_pence, req.first_pence, price_pence) if not problem else None
    split = money.split_for_source(price_pence, "platform", s)
    first_split = money.split_for_source(first, "platform", s) if first else None
    text = f"Your price: {_price_words(price_pence, req.unit)}."
    if first:
        text += f" The first visit becomes {wording.money(first)}."
    return CounterPreview(
        price_pence=price_pence,
        first_price_pence=first,
        provider_pence=split.provider_pence,
        first_provider_pence=first_split.provider_pence if first_split else None,
        fee_percent=split.rate_percent,
        text=text,
        valid=problem is None,
        problem=problem,
    )
