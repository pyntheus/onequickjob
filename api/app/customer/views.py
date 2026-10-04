"""Turning stored records into the customer's views (L1). Read-only: nothing here writes.

Money shown to the customer comes from the records (agreed prices, the offer's stored
first-visit price) and fee splits from app.core.money only.
"""

from datetime import timedelta

from app.core import money
from app.core.config import Settings
from app.core.db import Db
from app.core.geo import miles_between
from app.core.phone import to_national
from app.core.rounding import round_half_up_to
from app.core.timeutil import london_today, utcnow
from app.customer.schemas import (
    Badge,
    BookingCard,
    BookingDetail,
    CounterOfferView,
    CustomerVisit,
    FrequencyOption,
    PendingPlanChange,
    PlanOut,
    PriceChangeView,
    ProviderCard,
    RequestDetail,
    RequestSummary,
    TimelineEvent,
)
from app.models.bookings import Booking, Series
from app.models.categories import Category
from app.models.common import Address
from app.models.job_requests import JobRequest
from app.models.offers import Offer
from app.models.providers import Provider
from app.models.quotes import FeeSplit, Measure
from app.models.visits import Visit
from app.repos.categories import Categories
from app.repos.disputes import Disputes
from app.repos.files import Files
from app.repos.offers import Offers
from app.repos.plan_changes import PlanChanges
from app.repos.providers import Providers
from app.repos.ratings import Ratings
from app.repos.users import Users
from app.repos.visits import Visits
from app.services import schedule, wording

REPORT_WINDOW = timedelta(hours=48)
BAND_LABELS = {"small": "Small", "medium": "Medium", "large": "Large", "very_large": "Very large"}
ADJUST_TEXT = {"smaller": ", a bit smaller than that", "bigger": ", a bit bigger than that", "right": ""}


def frequency_label(frequency: str | None) -> str | None:
    if not frequency or frequency == "oneoff":
        return None
    return wording.FREQUENCY_WORDS.get(frequency, frequency)


def size_text(measure: Measure | None) -> str | None:
    """The lawn size the customer chose, in their words: never "measured" (decisions.md A6)."""
    if measure is None:
        return None
    band = BAND_LABELS.get(measure.band or "", "")
    if not band:
        return f"About {measure.area_m2} m²"
    return f"{band}{ADJUST_TEXT.get(measure.adjust or 'right', '')} (about {measure.area_m2} m²)"


def miles_text(miles: float) -> str:
    if miles < 0.5:
        return "less than half a mile"
    if round(miles, 1) == 1.0:
        return "1 mile"
    return f"{miles:.1f} miles"


def fee_split(price_pence: int, mode: money.FeeMode, s: Settings) -> FeeSplit:
    sp = money.split(price_pence, mode, s)
    return FeeSplit(
        mode=sp.mode,
        rate_percent=sp.rate_percent,
        price_pence=sp.price_pence,
        fee_pence=sp.fee_pence,
        provider_pence=sp.provider_pence,
    )


def provider_card(p: Provider, cat: Category | None, at: Address | None) -> ProviderCard:
    today = london_today()
    held = {
        d.type: d for d in p.documents if d.status == "verified" and (d.expires_on is None or d.expires_on >= today)
    }
    badges: list[Badge] = []
    if "identity" in held:
        badges.append(Badge(kind="identity", label="ID checked"))
    if cat and "dbs_basic" in cat.requires and "dbs_basic" in held:
        badges.append(Badge(kind="dbs", label="Basic DBS checked"))
    if ins := held.get("insurance"):
        label = f"Insured until {ins.expires_on:%b %Y}" if ins.expires_on else "Insured"
        badges.append(Badge(kind="insured", label=label))
    miles = None
    if at is not None:
        miles = float(round_half_up_to(miles_between(p.home.location.lat, p.home.location.lng, at.lat, at.lng), "0.1"))
        badges.append(Badge(kind="distance", label=f"Lives {miles_text(miles)} away", tone="plain"))
    return ProviderCard(
        provider_id=p.id,
        short=p.short,
        first_name=wording.first_name(p.name),
        initials=p.initials,
        rating_avg=p.stats.rating_avg,
        rating_count=p.stats.rating_count,
        miles=miles,
        badges=badges,
    )


class Lookup:
    """Caches categories and providers while one view is built."""

    def __init__(self, db: Db):
        self.db = db
        self._cats: dict[str, Category | None] = {}
        self._providers: dict[str, Provider | None] = {}

    async def cat(self, category_id: str) -> Category:
        if category_id not in self._cats:
            self._cats[category_id] = await Categories(self.db).get(category_id)
        cat = self._cats[category_id]
        assert cat is not None, category_id
        return cat

    async def provider(self, provider_id: str) -> Provider | None:
        if provider_id not in self._providers:
            self._providers[provider_id] = await Providers(self.db).get(provider_id)
        return self._providers[provider_id]


# --------------------------------------------------------------------------------- requests


def request_summary(req: JobRequest, cat: Category) -> RequestSummary:
    return RequestSummary(
        id=req.id,
        ref=req.ref,
        category_id=cat.id,
        category_name=cat.name,
        status=req.status,
        guide_pence=req.guide_pence,
        first_pence=req.first_pence,
        unit=req.unit,
        area=req.address.area,
        district=req.address.district,
        created_at=req.created_at,
        booking_id=req.booked.booking_id if req.booked else None,
        frequency_label=frequency_label(req.frequency),
    )


def offer_view(o: Offer, card: ProviderCard) -> CounterOfferView:
    return CounterOfferView(
        offer_id=o.id,
        provider=card,
        price_pence=o.price_pence,
        first_price_pence=o.first_price_pence,
        guide_pence=o.guide_pence,
        reason_text=(o.message.strip() or "; ".join(o.reasons)).strip(),
        status=o.status,
        created_at=o.created_at,
    )


def _first_text(price: int | None) -> str:
    return f" (first visit {wording.money(price)})" if price else ""


async def request_detail(
    db: Db, req: JobRequest, *, demo: bool, simulating: bool = False, lookup: Lookup | None = None
) -> RequestDetail:
    look = lookup or Lookup(db)
    cat = await look.cat(req.category_id)
    offers = {o.id: o for o in await Offers(db).for_request(req.id)}

    async def card(provider_id: str | None) -> ProviderCard | None:
        p = await look.provider(provider_id) if provider_id else None
        return provider_card(p, cat, req.address) if p else None

    still_open = req.status == "open"
    timeline: list[TimelineEvent] = []
    viewers: list[str] = []
    viewing: TimelineEvent | None = None
    for e in sorted(req.events, key=lambda e: e.at):
        match e.kind:
            case "broadcast":
                text = (
                    f"Sent to checked {cat.short.lower()} providers near {req.address.district}"
                    if e.count
                    else "We're finding someone local by hand, which can take a little longer"
                )
                timeline.append(TimelineEvent(at=e.at, kind="sent", text=text))
            case "viewed":
                pc = await card(e.provider_id)
                if pc and pc.short not in viewers:
                    viewers.append(pc.short)
                if viewing is None:
                    viewing = TimelineEvent(at=e.at, kind="viewing", text="")
                    timeline.append(viewing)
            case "countered":
                o = offers.get(e.offer_id or "")
                pc = await card(e.provider_id)
                if o is None or pc is None:
                    continue
                text = (
                    f"{pc.short} suggested {wording.money(o.price_pence)} {req.unit}{_first_text(o.first_price_pence)}"
                )
                timeline.append(TimelineEvent(at=e.at, kind="counter", text=text, provider=pc, offer=offer_view(o, pc)))
            case "counter_lapsed":
                p = await look.provider(e.provider_id or "")
                who = wording.first_name(p.name) if p else "That provider"
                text = (
                    f"{who} can no longer take this job. We're still finding someone local."
                    if still_open
                    else f"{who} could no longer take this job."
                )
                timeline.append(TimelineEvent(at=e.at, kind="note", text=text))
            case "accepted":
                pc = await card(e.provider_id)
                if pc is None:
                    continue
                b = req.booked
                if b and b.via == "counter":
                    first = b.first_price_pence if b.first_price_pence != b.price_pence else None
                    text = f"You accepted {pc.short}'s price of {wording.money(b.price_pence)}{_first_text(first)}"
                elif b and b.via == "direct":
                    text = f"{pc.short} accepted your request to book them again"
                else:
                    text = f"{pc.short} accepted your guide price"
                timeline.append(TimelineEvent(at=e.at, kind="accepted", text=text, provider=pc))
            case "price_change_proposed":
                text = f"We suggested raising the guide price to {wording.money(e.price_pence or 0)}"
                timeline.append(TimelineEvent(at=e.at, kind="note", text=text))
            case "price_change_declined":
                text = f"You kept the guide price at {wording.money(e.price_pence or req.guide_pence)}"
                timeline.append(TimelineEvent(at=e.at, kind="note", text=text))
            case "price_change_withdrawn":
                proposed = wording.money(e.price_pence or 0)
                text = f"Booked before you answered, so the suggested {proposed} no longer applies"
                timeline.append(TimelineEvent(at=e.at, kind="note", text=text))
            case "guide_raised" if e.text == "Approved by the customer":
                again = (
                    f"we've sent it to checked providers near {req.address.district} again"
                    if e.count
                    else "we're finding someone local by hand"
                )
                text = f"You approved a guide price of {wording.money(e.price_pence or 0)}, and {again}"
                timeline.append(TimelineEvent(at=e.at, kind="note", text=text))
            case "guide_raised":
                price = f" to {wording.money(e.price_pence)}" if e.price_pence else ""
                timeline.append(
                    TimelineEvent(
                        at=e.at, kind="note", text=f"The guide price went up{price}, to help find someone local"
                    )
                )
            case "cancelled":
                timeline.append(TimelineEvent(at=e.at, kind="cancelled", text="You cancelled this request"))
            case "expired":
                timeline.append(
                    TimelineEvent(
                        at=e.at, kind="note", text="We couldn't find someone local this time, so this request closed"
                    )
                )
            case "note" if e.text:
                timeline.append(TimelineEvent(at=e.at, kind="note", text=e.text))
            case _:
                pass
    if viewing is not None:
        if not viewers:
            timeline.remove(viewing)
        else:
            others = len(viewers) - 1
            who = viewers[0] + ("" if not others else " and one other" if others == 1 else f" and {others} others")
            verb = ("is" if not others else "are") + " looking" if still_open else "looked"
            viewing.text = f"{who} {verb} at your job"

    pending = []
    for o in offers.values():
        if o.status == "pending":
            pc = await card(o.provider_id)
            if pc:
                pending.append(offer_view(o, pc))
    b = req.booked
    return RequestDetail(
        **request_summary(req, cat).model_dump(),
        timeline=timeline,
        pending_offers=sorted(pending, key=lambda v: v.created_at),
        booked_with=await card(b.provider_id) if b else None,
        booked_price_pence=b.price_pence if b else None,
        booked_first_price_pence=b.first_price_pence if b and b.first_price_pence != b.price_pence else None,
        booked_via=b.via if b else None,
        demo_simulator=demo and still_open and not req.cover_for_visit_id,
        alerted=len(req.broadcast.provider_ids) if req.broadcast else 0,
        size_text=size_text(req.measure),
        notes=req.notes,
        simulating=simulating,
        price_change=PriceChangeView(
            change_id=pc.id,
            guide_pence=pc.guide_pence,
            first_pence=pc.first_pence,
            from_guide_pence=pc.from_guide_pence,
            from_first_pence=pc.from_first_pence,
            proposed_at=pc.proposed_at,
        )
        if (pc := req.price_change) and pc.status == "pending" and still_open
        else None,
    )


# --------------------------------------------------------------------------------- bookings


def window_text(window: str) -> str:
    return schedule.WINDOW_COPY.get(window, "")


def visit_day_text(v: Visit) -> str:
    return f"{wording.day_text(v.local_date)}, {window_text(v.window)}"


def agreement_text(booking: Booking, provider: Provider, brand: str) -> str:
    who = wording.first_name(provider.name)
    if booking.source == "own_customer":
        return (
            f"Your agreement is still with {who}. {brand} handles bookings and payments on {who}'s behalf, and "
            f"{who} pays us a small fee for each visit. It isn't added to your price."
        )
    return (
        f"Your agreement for this job is with {who}. {brand} arranged it, takes payment on their behalf through "
        "Stripe, and helps sort things out if anything goes wrong."
    )


async def first_visit(db: Db, booking: Booking) -> Visit | None:
    return await Visits(db).find_one({"booking_id": booking.id, "is_first": True}) or await Visits(db).find_one(
        {"booking_id": booking.id}, sort=[("scheduled_start", 1)]
    )


async def booking_card(db: Db, s: Settings, booking: Booking, look: Lookup) -> BookingCard:
    cat = await look.cat(booking.category_id)
    provider = await look.provider(booking.provider_id)
    assert provider is not None, booking.provider_id
    first = await first_visit(db, booking)
    return BookingCard(
        id=booking.id,
        ref=booking.ref,
        source=booking.source,
        category_id=cat.id,
        category_name=cat.name,
        provider=provider_card(provider, cat, booking.address),
        recurring=booking.recurring,
        frequency_label=frequency_label(booking.frequency),
        price_pence=booking.price_pence,
        first_price_pence=booking.first_price_pence,
        unit=booking.unit,
        split=fee_split(booking.price_pence, money.mode_for_source(booking.source), s),
        charged_after="each visit" if booking.recurring else "the job",
        first_visit_text=visit_day_text(first) if first else "",
        status=booking.status,
        thread_id=booking.thread_id,
        series_id=booking.series_id,
    )


async def booking_detail(db: Db, s: Settings, booking: Booking, look: Lookup) -> BookingDetail:
    card = await booking_card(db, s, booking, look)
    provider = await look.provider(booking.provider_id)
    assert provider is not None
    from app.repos.customers import Customers

    customer = await Customers(db).get(booking.customer_id)
    user = await Users(db).get(customer.user_id) if customer else None
    return BookingDetail(
        **card.model_dump(),
        address=booking.address,
        agreement_text=agreement_text(booking, provider, s.brand),
        sms_sent_to=to_national(user.phone) if user and user.phone else None,
    )


# --------------------------------------------------------------------------------- visits


async def visit_views(db: Db, visits: list[Visit], look: Lookup, bookings: dict[str, Booking]) -> list[CustomerVisit]:
    now = utcnow()
    file_ids = [v.photos.after[0] for v in visits if v.photos.after]
    files = {f.id: f for f in await Files(db).find({"_id": {"$in": file_ids}})} if file_ids else {}
    rating_ids = [v.rating_id for v in visits if v.rating_id]
    ratings = {r.id: r for r in await Ratings(db).find({"_id": {"$in": rating_ids}})} if rating_ids else {}
    dispute_ids = [v.dispute_id for v in visits if v.dispute_id]
    disputes = {d.id: d for d in await Disputes(db).find({"_id": {"$in": dispute_ids}})} if dispute_ids else {}
    # The next scheduled visit of each booking is "booked"; later ones in a plan are "planned".
    next_of: dict[str, str] = {}
    for v in sorted(visits, key=lambda v: v.scheduled_start):
        if v.status == "scheduled" and v.booking_id not in next_of:
            next_of[v.booking_id] = v.id
    out: list[CustomerVisit] = []
    for v in visits:
        cat = await look.cat(v.category_id)
        booking = bookings.get(v.booking_id)
        recurring = bool(booking and booking.recurring)
        performer = v.performer.name
        p = await look.provider(v.performer.provider_id)
        first = wording.first_name(p.name) if p and v.performer.kind != "helper" else wording.first_name(performer)
        if v.status == "finished":
            label = "done"
        elif v.status in ("skipped", "cancelled"):
            label = "skipped"
        else:
            label = "booked" if next_of.get(v.booking_id) == v.id or not recurring else "planned"
        after = files.get(v.photos.after[0]) if v.photos.after else None
        rating = ratings.get(v.rating_id or "")
        dispute = disputes.get(v.dispute_id or "")
        future = v.scheduled_start > now
        finished_recently = v.finished_at is not None and now - v.finished_at <= REPORT_WINDOW
        out.append(
            CustomerVisit(
                id=v.id,
                booking_id=v.booking_id,
                category_id=cat.id,
                category_name=cat.name,
                provider_short=performer,
                provider_first_name=first,
                recurring=recurring,
                local_date=v.local_date,
                scheduled_start=v.scheduled_start,
                window=v.window,
                status=v.status,
                label=label,  # type: ignore[arg-type]
                price_pence=v.price_pence,
                minutes_actual=v.minutes_actual,
                after_photo_url=after.url if after else None,
                rating_stars=rating.stars if rating else None,
                can_rate=v.status == "finished" and v.rating_id is None,
                can_skip=v.status == "scheduled" and recurring and future,
                can_report=v.status == "finished" and finished_recently and v.dispute_id is None,
                can_change_date=v.status == "scheduled" and not recurring and future,
                thread_id=booking.thread_id if booking else None,
                dispute_ref=dispute.ref if dispute else None,
                tip_pence=v.tip_pence,
            )
        )
    return out


# --------------------------------------------------------------------------------- plans


async def plan_view(db: Db, series: Series, booking: Booking, look: Lookup) -> PlanOut:
    cat = await look.cat(series.category_id)
    provider = await look.provider(series.provider_id)
    assert provider is not None
    nxt = await Visits(db).find_one(
        {"series_id": series.id, "status": "scheduled", "local_date": {"$gte": london_today().isoformat()}},
        sort=[("local_date", 1)],
    )
    status = "paused" if series.status == "active" and _away_now(series) else series.status
    return PlanOut(
        series_id=series.id,
        booking_id=booking.id,
        category_id=cat.id,
        category_name=cat.name,
        outside=cat.group == "outside",
        provider=provider_card(provider, cat, booking.address),
        frequency=series.frequency,
        frequency_label=frequency_label(series.frequency) or "",
        price_pence=series.price_pence,
        unit=booking.unit,
        status=status,  # type: ignore[arg-type]
        pause_winter=series.pause.winter,
        away_from=series.pause.away_from,
        away_to=series.pause.away_to,
        cover_when_away=series.cover_when_away,
        next_visit_date=nxt.local_date if nxt else None,
        pending_change=PendingPlanChange(
            to_frequency=pc.to_frequency,
            to_frequency_label=frequency_label(pc.to_frequency) or "",
            to_price_pence=pc.to_price_pence,
            expires_at=pc.expires_at,
        )
        if (pc := await PlanChanges(db).pending_for(series.id))
        else None,
        frequency_options=[
            FrequencyOption(value=f, label=frequency_label(f) or f)
            for f in plan_frequencies(cat)
            if series.status != "cancelled" and series.frequency in plan_frequencies(cat)
        ],
    )


def plan_frequencies(cat: Category) -> list[str]:
    """The recurring frequencies a category offers (its intake's frequency options, not one-off)."""
    field = next((f for f in cat.intake if f.key == "frequency"), None)
    return [o.value for o in (field.options or []) if o.value != "oneoff"] if field else []


def _away_now(series: Series) -> bool:
    p = series.pause
    today = london_today()
    return bool(p.away_from and p.away_to and p.away_from <= today <= p.away_to)
