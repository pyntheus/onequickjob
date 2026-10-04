"""Overview and dispatch: the week's figures, jobs waiting for a provider, where the work is,
customers providers brought, providers needing attention and charges needing a look."""

from collections import Counter
from datetime import date, time, timedelta
from statistics import median

from fastapi import status

from app.admin.schemas import (
    AttentionItem,
    DistrictTile,
    Kpi,
    Overview,
    OwnCustomersCard,
    PaymentIssue,
    UnfilledRequest,
    WhatsAppText,
)
from app.admin.views import (
    DISTRICT_NAMES,
    age_text,
    brief_for,
    doc_state,
    lower_first,
    money,
    plural,
    renewal_waiting,
    request_where,
    short_name,
)
from app.core import money as fees
from app.core.config import Settings
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.core.rounding import D, round_to_pound
from app.core.timeutil import london_datetime, london_today, utcnow, week_start
from app.models.categories import Category
from app.models.common import Actor, Related
from app.models.job_requests import JobRequest
from app.models.providers import Provider
from app.repos import (
    Bookings,
    Categories,
    Customers,
    DocumentTypes,
    JobRequests,
    LedgerEntries,
    Offers,
    OwnCustomerInvites,
    Providers,
    Visits,
)
from app.repos.payments import PaymentRefunds
from app.services import guide_raises
from app.services.audit import audit
from app.services.marketplace import scaled_first_price
from app.services.notify import link

WAITING_AFTER = timedelta(hours=1)  # newer requests are still being answered in the usual way
STALLED_AFTER = timedelta(days=3)
PAYMENT_PENDING_AFTER = timedelta(minutes=10)
REFUND_STUCK_AFTER = timedelta(minutes=15)


def week_label(start: date) -> str:
    end = start + timedelta(days=6)
    if start.month == end.month:
        return f"Monday {start.day} to Sunday {end.day} {end:%B}"
    return f"Monday {start.day} {start:%B} to Sunday {end.day} {end:%B}"


def season_note(today: date) -> str | None:
    if today.month in (9, 10):
        return "Late season: winter pauses start in November"
    if today.month in (11, 12, 1, 2):
        return "Winter: outside plans are paused until March"
    return None


def percent(part: int | float, whole: int | float) -> str:
    return f"{round(100 * part / whole)}%" if whole else "n/a"


def minutes_text(mins: float) -> str:
    m = round(mins)
    if m < 120:
        return f"{m} min"
    h, r = divmod(m, 60)
    return f"{h} h {r} min" if r else f"{h} h"


def first_yes_minutes(req: JobRequest) -> float | None:
    yes = [e.at for e in req.events if e.kind in ("countered", "accepted")]
    return (min(yes) - req.created_at).total_seconds() / 60 if yes else None


def _range(start: date, end: date) -> dict:
    """London days start..end (exclusive) as a UTC datetime range."""
    return {"$gte": london_datetime(start, time(0)), "$lt": london_datetime(end, time(0))}


async def _kpis(db: Db, start: date) -> list[Kpi]:
    end = start + timedelta(days=7)
    reqs = JobRequests(db)
    this_week = await reqs.find({"created_at": _range(start, end), "cover_for_visit_id": None})
    last_week = await reqs.count({"created_at": _range(start - timedelta(days=7), start), "cover_for_visit_id": None})
    booked = [r for r in this_week if r.status == "booked" and r.booked]
    at_guide = sum(1 for r in booked if r.booked and r.booked.via in ("guide", "direct"))
    waits = [m for r in this_week if (m := first_yes_minutes(r)) is not None]
    diff = len(this_week) - last_week
    rows = await LedgerEntries(db).find(
        {"local_date": {"$gte": start.isoformat(), "$lt": end.isoformat()}, "kind": {"$in": ["charge", "refund"]}}
    )
    gross = sum(e.gross_pence for e in rows if e.kind == "charge")
    revenue = sum(e.fee_pence for e in rows)
    return [
        Kpi(
            label="Requests",
            value=str(len(this_week)),
            sub=f"{abs(diff)} {'more' if diff >= 0 else 'fewer'} than last week" if diff else "same as last week",
        ),
        Kpi(label="Filled", value=str(len(booked)), sub=f"{percent(len(booked), len(this_week))} fill rate"),
        Kpi(
            label="Time to first yes",
            value=minutes_text(median(waits)) if waits else "n/a",
            sub="median" if waits else "no answers yet",
        ),
        Kpi(
            label="Taken at guide price",
            value=percent(at_guide, len(booked)),
            sub="the rest countered" if booked else "nothing filled yet",
        ),
        Kpi(label="Job value", value=money(gross), sub="all jobs charged this week"),
        Kpi(label="Our revenue", value=money(revenue), sub=f"{percent(revenue, gross)} of job value"),
    ]


def why_waiting(req: JobRequest, pending: list, names: dict[str, str]) -> str:
    if req.price_change and req.price_change.status == "pending":  # A12
        return f"Awaiting customer: they've been asked to approve {money(req.price_change.guide_pence)}."
    if req.admin_note:
        return req.admin_note
    if pending:
        if len(pending) == 1:
            o = pending[0]
            who = names.get(o.provider_id, "A provider").split(" ")[0]
            return f"{who} suggested {money(o.price_pence)}. Waiting on the customer."
        return f"{len(pending)} providers suggested other prices. Waiting on the customer."
    if req.viewed_by:
        return f"{plural(len(req.viewed_by), 'provider')} looked, nobody took it."
    if req.broadcast is not None and not req.broadcast.provider_ids:
        return "No providers in reach were alerted. Nobody has seen it."
    return "Nobody has opened it yet."


async def unfilled(db: Db, req: JobRequest, cat: Category | None = None) -> UnfilledRequest:
    cat = cat or await Categories(db).get(req.category_id)
    assert cat is not None
    pending = [o for o in await Offers(db).for_request(req.id) if o.status == "pending"]
    names = {p.id: p.short for p in await Providers(db).find({"_id": {"$in": [o.provider_id for o in pending]}})}
    return UnfilledRequest(
        request_id=req.id,
        request_ref=req.ref,
        category_id=req.category_id,
        category_name=cat.name,
        area=req.address.area,
        district=req.address.district,
        waiting_since=req.created_at,
        age_text=age_text(req.created_at),
        guide_pence=req.guide_pence,
        brief=brief_for(cat, req.answers, req.measure),
        why=why_waiting(req, pending, names),
        views=len(req.viewed_by),
        pending_counters=len(pending),
        awaiting_customer=bool(req.price_change and req.price_change.status == "pending"),
        proposed_guide_pence=req.price_change.guide_pence
        if req.price_change and req.price_change.status == "pending"
        else None,
    )


async def _waiting(db: Db, cats: dict[str, Category]) -> list[UnfilledRequest]:
    reqs = await JobRequests(db).find(
        {"status": "open", "created_at": {"$lte": utcnow() - WAITING_AFTER}}, sort=[("created_at", -1)], limit=50
    )
    return [await unfilled(db, r, cats.get(r.category_id)) for r in reqs]


async def _districts(db: Db, start: date) -> list[DistrictTile]:
    end = start + timedelta(days=6)
    visits = await Visits(db).find(
        {
            "local_date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
            "status": {"$nin": ["cancelled", "skipped"]},
        }
    )
    bookings = {b.id: b for b in await Bookings(db).find({"_id": {"$in": list({v.booking_id for v in visits})}})}
    jobs: Counter[str] = Counter()
    localities: dict[str, Counter[str]] = {}
    for v in visits:
        b = bookings.get(v.booking_id)
        if b is None:
            continue
        jobs[b.address.district] += 1
        localities.setdefault(b.address.district, Counter())[b.address.area] += 1
    providers = Counter(
        p.home.district for p in await Providers(db).find({"status": {"$in": ["active", "payouts_paused"]}})
    )
    codes = sorted(set(jobs) | set(providers), key=lambda c: (-jobs[c], -providers[c], c))[:8]
    return [
        DistrictTile(
            code=c,
            name=DISTRICT_NAMES.get(c) or (localities[c].most_common(1)[0][0] if c in localities else c),
            jobs=jobs[c],
            providers=providers[c],
        )
        for c in codes
    ]


async def _own_customers(db: Db, start: date) -> OwnCustomersCard:
    active = await Bookings(db).find({"source": "own_customer", "status": "active"})
    rows = await LedgerEntries(db).find(
        {
            "source": "own_customer",
            "kind": {"$in": ["charge", "refund"]},
            "local_date": {"$gte": start.isoformat(), "$lt": (start + timedelta(days=7)).isoformat()},
        }
    )
    return OwnCustomersCard(
        active=len({b.customer_id for b in active}),
        providers=len({b.provider_id for b in active}),
        job_value_pence=sum(e.gross_pence for e in rows if e.kind == "charge"),
        revenue_pence=sum(e.fee_pence for e in rows),
        invites_blocked=await OwnCustomerInvites(db).count({"status": "blocked"}),
    )


def attention_for(p: Provider, labels: dict[str, str], today: date) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    if p.status == "suspended":
        return items
    if p.status == "signing_up":
        if utcnow() - p.updated_at >= STALLED_AFTER:
            step = "tax details" if not p.tax.complete else "documents" if not p.documents else "their payment account"
            days = (utcnow() - p.updated_at).days
            items.append(
                AttentionItem(
                    provider_id=p.id,
                    short=p.short,
                    issue=f"Stuck on {step} for {days} days",
                    tone="warn",
                    action="Ring them",
                )
            )
        return items
    # A renewal waiting for a check: check it, rather than remind them about the old copy (Session S).
    renewing = sorted({d.type for d in p.documents if renewal_waiting(p.documents, d.type)})
    for t in renewing:
        items.append(
            AttentionItem(
                provider_id=p.id,
                short=p.short,
                issue=f"{labels.get(t, t)} renewal to check",
                tone="warn",
                action="Check it",
            )
        )
    for d in p.documents:
        state = doc_state(d, today)
        if d.type in renewing:
            continue
        if state in ("warn", "expired") and d.expires_on:
            label = labels.get(d.type, d.type)
            verb = "expires" if state == "warn" else "expired"
            items.append(
                AttentionItem(
                    provider_id=p.id,
                    short=p.short,
                    issue=f"{label} {verb} on {d.expires_on.day} {d.expires_on:%B}",
                    tone="warn" if state == "warn" else "danger",
                    action="Send reminder",
                )
            )
    if not p.tax.complete:
        items.append(
            AttentionItem(
                provider_id=p.id,
                short=p.short,
                issue="Tax details missing, so payouts are paused",
                tone="danger",
                action="Chase",
            )
        )
    return items


async def _attention(db: Db) -> list[AttentionItem]:
    labels = {t.id: t.label for t in await DocumentTypes(db).all()}
    labels["insurance"] = "Insurance"
    today = london_today()
    items = [i for p in await Providers(db).find({}, sort=[("name", 1)]) for i in attention_for(p, labels, today)]
    return sorted(items, key=lambda i: i.tone != "danger")


async def payment_issues(db: Db, cats: dict[str, Category]) -> list[PaymentIssue]:
    stale = utcnow() - PAYMENT_PENDING_AFTER
    visits = await Visits(db).find(
        {
            "$or": [
                {"charge.status": {"$in": ["failed", "requires_action"]}},
                {"charge.status": "pending", "updated_at": {"$lte": stale}},
                # Finished, but the charge never started (the settle task keeps trying: L2's filing).
                {"status": "finished", "charge.status": "none", "finished_at": {"$lte": stale}},
            ]
        },
        sort=[("updated_at", -1)],
        limit=50,
    )
    open_refunds = await PaymentRefunds(db).find(
        {
            "created_at": {"$lte": utcnow() - REFUND_STUCK_AFTER},
            "$or": [{"status": {"$in": ["pending", "fee_pending"]}}, {"restore": "needed"}],
        },
        sort=[("created_at", -1)],
        limit=50,
    )
    refunded = {v.id: v for v in await Visits(db).find({"_id": {"$in": [r.visit_id for r in open_refunds]}})}
    customers = {
        c.id: c
        for c in await Customers(db).find(
            {"_id": {"$in": list({v.customer_id for v in [*visits, *refunded.values()]})}}
        )
    }

    def who(v) -> str:
        return short_name(customers[v.customer_id].name) if v.customer_id in customers else "A customer"

    refund_issues = [
        PaymentIssue(
            visit_id=r.visit_id,
            customer_name=who(v),
            provider_short=v.performer.name,
            category_name=cats[v.category_id].name if v.category_id in cats else v.category_id,
            local_date=v.local_date,
            amount_pence=r.amount_pence,
            status="refund_restore" if r.restore == "needed" else "refund_" + r.status,
            failure_reason=r.failure_reason,
            since=r.created_at,
            kind="refund",
        )
        for r in open_refunds
        if (v := refunded.get(r.visit_id)) is not None
    ]
    return refund_issues + [
        PaymentIssue(
            visit_id=v.id,
            customer_name=who(v),
            provider_short=v.performer.name,
            category_name=cats[v.category_id].name if v.category_id in cats else v.category_id,
            local_date=v.local_date,
            amount_pence=v.charge.amount_pence or v.price_pence,
            status="not_started" if v.charge.status == "none" else v.charge.status,
            failure_reason=v.charge.failure_reason,
            since=(v.finished_at or v.updated_at) if v.charge.status == "none" else v.updated_at,
        )
        for v in visits
    ]


async def overview(db: Db) -> Overview:
    today = london_today()
    start = week_start(today)
    cats = {c.id: c for c in await Categories(db).all()}
    return Overview(
        week_label=week_label(start),
        season_note=season_note(today),
        kpis=await _kpis(db, start),
        waiting=await _waiting(db, cats),
        districts=await _districts(db, start),
        own_customers=await _own_customers(db, start),
        attention=await _attention(db),
        payments=await payment_issues(db, cats),
    )


async def _request(db: Db, ref: str, session: DbSession | None = None) -> JobRequest:
    req = await JobRequests(db).by_ref(ref, session=session)
    if req is None:
        not_found("That request")
    return req


async def whatsapp_text(db: Db, s: Settings, ref: str) -> WhatsAppText:
    """The prototype's group message. A link in a group can't sign anyone in, so it carries no
    token: whoever taps it signs in as usual."""
    req = await _request(db, ref)
    cat = await Categories(db).get(req.category_id)
    assert cat is not None
    keep = fees.split(req.guide_pence, "standard", s).provider_pence
    opener = "Cover needed" if req.cover_for_visit_id else "Job going"
    return WhatsAppText(
        text=f"{opener}: {lower_first(cat.name)} in {request_where(req)}. {brief_for(cat, req.answers, req.measure)}. "
        f"Guide price {money(req.guide_pence)}, you'd get {money(keep)}. Take it here: {link(f'/p/j/{req.ref}', s)}"
    )


async def raise_guide(db: Db, s: Settings, ref: str, percent_: int, note: str, actor: Actor) -> UnfilledRequest:
    """Suggest raising an open request's guide price by percent_, rounded half-up to whole pounds.
    A dearer first visit rises by the same ratio (marketplace.scaled_first_price, as for a
    counter: A1). Ruling A12: the raise waits for the customer's approval (app.services.guide_raises;
    they answer in app.customer.price_changes); only then does the guide change and the job go
    out again."""
    req = await _request(db, ref)
    if req.status != "open":
        fail(status.HTTP_409_CONFLICT, "not_open", "This request isn't open any more.")
    new_guide = round_to_pound(D(req.guide_pence) * (100 + percent_) / 100)
    if new_guide <= req.guide_pence:
        fail(status.HTTP_409_CONFLICT, "no_change", "That rounds to the same whole-pound price. Raise it by more.")
    new_first = scaled_first_price(req.guide_pence, req.first_pence, new_guide)
    before = {"guide_pence": req.guide_pence, "first_pence": req.first_pence}
    after = {"guide_pence": new_guide, "first_pence": new_first, "percent": percent_}

    async def apply(session: DbSession) -> JobRequest:
        updated = await guide_raises.propose(
            db, s, req, guide_pence=new_guide, first_pence=new_first, percent=percent_, note=note, actor=actor,
            session=session,
        )  # fmt: skip
        await audit(
            db,
            actor,
            "request.guide_raise_proposed",
            Related(request_id=req.id, customer_id=req.customer_id),
            before=before,
            after=after,
            note=note,
            session=session,
        )
        return updated

    return await unfilled(db, await transaction(db, apply))
