"""Pricing and calibration: recorded times against estimates, a table per job type, suggested
changes from simple rules, and pricing versions (one admin drafts, a different one approves).

Rules for suggestions (each needs at least MIN_JOBS timed jobs in the segment):
- time: the median overrun is above 20%, so the segment's time parameter rises by it;
- price: more than half the jobs were countered while times stayed within 15% of estimate,
  so the rate rises by the median counter's share of the guide.
A suggestion only drafts a version: nothing changes until a second admin approves it, and
quotes always keep the version they used.
"""

import copy
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from statistics import median
from typing import Any, NoReturn

from fastapi import status
from pymongo.errors import DuplicateKeyError

from app.admin.schemas import (
    Calibration,
    CalibrationPoint,
    ChangeIn,
    Kpi,
    PricingVersionSummary,
    Segment,
    SegmentRow,
    Suggestion,
)
from app.admin.views import money
from app.core.db import Db, DbSession, transaction
from app.core.errors import fail, not_found
from app.core.rounding import D, round_half_up_to
from app.core.timeutil import utcnow
from app.models.categories import Category
from app.models.common import Actor, Related
from app.models.pricing_versions import ParamChange, PricingVersion
from app.models.visits import Visit
from app.pricing.answers import defaults_for
from app.pricing.engine import PricingError, price
from app.repos import Bookings, Categories, JobRequests, PricingVersions, Users, Visits
from app.services.audit import audit

WINDOW = timedelta(days=90)
MIN_JOBS = 10
OVERRUN_RULE = 0.20
COUNTER_RULE = 0.50
CLOSE_ENOUGH = 0.15
COLOURS = ["--c1", "--c2", "--c3", "--c4"]
TEST_LAWN_M2 = 186


@dataclass(frozen=True)
class Lever:
    path: str
    step: str
    what: str  # "the overgrown multiplier"
    unit: str = ""  # " minutes per metre"
    title: str = ""  # the suggestion's heading; a generic one from the segment's label if empty


# What each segment's rules adjust: (time lever, price lever). Others fall back to GENERIC.
LEVERS: dict[str, tuple[Lever | None, Lever | None]] = {
    "first": (
        Lever(
            "growth.overgrown", "0.1", "the overgrown multiplier", title="First cuts take much longer than we estimate"
        ),
        None,
    ),
    "mowing": (
        Lever(
            "mins_per_m2", "0.01", "the minutes per square metre", title="Routine mowing takes longer than we estimate"
        ),
        Lever("hourly_pence", "100", "the hourly rate", title="Routine mowing looks underpriced"),
    ),
    "hedges": (
        Lever(
            "per_m_mins.head",
            "0.5",
            "the head-height rate",
            " minutes per metre",
            "Hedges take longer than we estimate",
        ),
        Lever("per_m_mins.above", "0.5", "the above-head rate", " minutes per metre", "Tall hedges are underpriced"),
    ),
    "clearance": (
        Lever(
            "mins.boot", "5", "the time for a car boot's worth", " minutes", "Clearance takes longer than we estimate"
        ),
        Lever("base_pence.boot", "500", "the car-boot price", title="Clearance is underpriced"),
    ),
}
GENERIC = (Lever("base_mins", "1", "the base time", " minutes"), Lever("hourly_pence", "100", "the hourly rate"))


def segment_of(v: Visit) -> str:
    if v.category_id == "mowing":
        return "first" if v.is_first else "mowing"
    return v.category_id


def segment_label(seg: str, cats: dict[str, Category]) -> str:
    if seg == "mowing":
        return "Mowing, routine"
    if seg == "first":
        return "Mowing, first cut"
    return cats[seg].short if seg in cats else seg


def category_of(seg: str) -> str:
    return "mowing" if seg == "first" else seg


def overrun(v: Visit) -> float:
    return ((v.minutes_actual or 0) - v.est_mins) / v.est_mins if v.est_mins else 0.0


def pct(x: float, signed: bool = False) -> str:
    n = round(x * 100)
    return f"{'+' if signed and n > 0 else ''}{n}%"


def get_path(params: dict[str, Any], path: str) -> Any:
    node: Any = params
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(path)
        node = node[part]
    return node


def set_path(params: dict[str, Any], path: str, value: Any) -> None:
    *parents, last = path.split(".")
    node = params
    for part in parents:
        node = node[part]
    node[last] = value


def stepped(value: Decimal, step: str, like: Any) -> int | float:
    v = round_half_up_to(value, step)
    return int(v) if isinstance(like, int) and not isinstance(like, bool) else float(v)


async def _calibration_rows(db: Db) -> tuple[list[Visit], dict[str, Any], dict[str, Any]]:
    since = utcnow() - WINDOW
    visits = await Visits(db).find({"status": "finished", "finished_at": {"$gte": since}}, sort=[("finished_at", 1)])
    bookings = {b.id: b for b in await Bookings(db).find({"_id": {"$in": list({v.booking_id for v in visits})}})}
    requests = {
        r.id: r
        for r in await JobRequests(db).find({"_id": {"$in": [b.request_id for b in bookings.values() if b.request_id]}})
    }
    return visits, bookings, requests


def _uplift(v: Visit, booking, req) -> int | None:
    """How far a countered job's agreed price is above its guide."""
    if booking is None or booking.via != "counter" or req is None:
        return None
    guide = req.first_pence if v.is_first and req.first_pence else req.guide_pence
    return v.price_pence - guide


def _suggest(seg: str, label: str, row: SegmentRow, live: PricingVersion, guides: list[int]) -> list[Suggestion]:
    out: list[Suggestion] = []
    if row.jobs < MIN_JOBS:
        return out
    cat_id = category_of(seg)
    params = live.params.get(cat_id, {})
    time_lever, price_lever = LEVERS.get(seg, GENERIC)

    def change(lever: Lever, factor: Decimal) -> tuple[ParamChange, Any, Any] | None:
        try:
            before = get_path(params, lever.path)
        except KeyError:
            return None
        if not isinstance(before, int | float) or isinstance(before, bool):
            return None
        after = stepped(D(before) * factor, lever.step, before)
        if after == before:
            return None
        return ParamChange(category_id=cat_id, path=lever.path, before=before, after=after), before, after

    def show(lever: Lever, v: Any) -> str:
        return money(int(v)) if lever.path.endswith("pence") or "pence." in lever.path else f"{v:g}{lever.unit}"

    if row.median_overrun > OVERRUN_RULE and time_lever and (c := change(time_lever, D(1 + row.median_overrun))):
        pc, before, after = c
        out.append(
            Suggestion(
                id=f"{seg}:time:{time_lever.path}",
                title=time_lever.title or f"{label} jobs take longer than we estimate",
                body=f"Across {row.jobs} timed jobs, recorded times were a median {pct(row.median_overrun)} above "
                f"estimate and {pct(row.countered)} were countered. {time_lever.what[:1].upper()}{time_lever.what[1:]} "
                "looks too low.",
                change_text=f"Raise {time_lever.what} from {show(time_lever, before)} to {show(time_lever, after)}",
                change=pc,
            )
        )
    elif (
        row.countered > COUNTER_RULE
        and row.median_overrun < CLOSE_ENOUGH
        and price_lever
        and guides
        and row.median_counter_uplift_pence > 0
        and (c := change(price_lever, 1 + D(row.median_counter_uplift_pence) / D(median(guides))))
    ):
        pc, before, after = c
        countered = round(row.countered * row.jobs)
        out.append(
            Suggestion(
                id=f"{seg}:price:{price_lever.path}",
                title=price_lever.title or f"{label} jobs look underpriced",
                body=f"{countered} of {row.jobs} jobs were countered, by a median of "
                f"{money(row.median_counter_uplift_pence)}. Recorded times are close to estimate, so the rate is the "
                "issue, not the time.",
                change_text=f"Raise {price_lever.what} from {show(price_lever, before)} to {show(price_lever, after)}",
                change=pc,
            )
        )
    return out


async def calibration(db: Db) -> Calibration:
    live = await PricingVersions(db).live()
    if live is None:
        fail(status.HTTP_409_CONFLICT, "no_live_version", "There's no live pricing version.")
    cats = {c.id: c for c in await Categories(db).all()}
    visits, bookings, requests = await _calibration_rows(db)
    timed = [v for v in visits if v.minutes_actual and v.est_mins]
    by_seg: dict[str, list[Visit]] = {}
    for v in timed:
        by_seg.setdefault(segment_of(v), []).append(v)
    order = sorted(by_seg, key=lambda sg: (-len(by_seg[sg]), sg))
    segments = [
        Segment(id=sg, label=segment_label(sg, cats), color_token=COLOURS[i % len(COLOURS)])
        for i, sg in enumerate(order)
    ]
    table: list[SegmentRow] = []
    suggestions: list[Suggestion] = []
    for sg in order:
        rows = by_seg[sg]
        vias = [bookings[v.booking_id].via for v in rows if v.booking_id in bookings]
        decided = [x for x in vias if x in ("guide", "counter")]
        countered = []  # (how far above the guide, the guide) for each countered job
        for v in rows:
            b = bookings.get(v.booking_id)
            u = _uplift(v, b, requests.get(b.request_id) if b and b.request_id else None)
            if u is not None:
                countered.append((u, v.price_pence - u))
        uplifts, guides = [u for u, _ in countered], [g for _, g in countered]
        r = SegmentRow(
            segment=sg,
            label=segment_label(sg, cats),
            jobs=len(rows),
            taken_at_guide=decided.count("guide") / len(decided) if decided else 0.0,
            countered=decided.count("counter") / len(decided) if decided else 0.0,
            median_counter_uplift_pence=int(median(uplifts)) if uplifts else 0,
            median_overrun=median(overrun(v) for v in rows),
            over_25=sum(1 for v in rows if v.over_25) / len(rows),
        )
        table.append(r)
        suggestions += _suggest(sg, r.label, r, live, guides)
    all_vias = [b.via for b in bookings.values() if b.via in ("guide", "counter")]
    errors = [overrun(v) for v in timed]
    return Calibration(
        kpis=[
            Kpi(
                label="Median estimate error",
                value=pct(median(errors), signed=True) if errors else "n/a",
                sub="actual vs estimated time",
            ),
            Kpi(
                label="Jobs over by 25%+",
                value=pct(sum(1 for v in timed if v.over_25) / len(timed)) if timed else "n/a",
                sub="of timed jobs",
            ),
            Kpi(
                label="Taken at guide price",
                value=pct(all_vias.count("guide") / len(all_vias)) if all_vias else "n/a",
                sub="of filled jobs",
            ),
            Kpi(
                label="Jobs with a recorded time",
                value=pct(sum(1 for v in visits if v.minutes_from_timer) / len(visits)) if visits else "n/a",
                sub="from the provider timer",
            ),
        ],
        points=[
            CalibrationPoint(
                visit_id=v.id, segment=segment_of(v), est_mins=v.est_mins, actual_mins=v.minutes_actual or 0
            )
            for v in timed
        ],
        segments=segments,
        table=table,
        suggestions=suggestions,
        live_version=live.version,
    )


# ------------------------------------------------------------------ versions
async def _names(db: Db, ids: set[str]) -> dict[str, str]:
    users = await Users(db).find({"_id": {"$in": [i for i in ids if i and i != "seed"]}})
    return {"seed": "Seed data"} | {u.id: u.name for u in users}


def summary(v: PricingVersion, names: dict[str, str], viewer_id: str) -> PricingVersionSummary:
    return PricingVersionSummary(
        id=v.id,
        version=v.version,
        status=v.status,
        notes=v.notes,
        changes=v.changes,
        created_by=v.created_by,
        created_by_name=names.get(v.created_by, "Someone"),
        created_at=v.created_at,
        approved_by=v.approved_by,
        approved_by_name=names.get(v.approved_by, "Someone") if v.approved_by else None,
        approved_at=v.approved_at,
        can_approve=v.status == "draft" and v.created_by != viewer_id,
    )


async def versions(db: Db, viewer_id: str) -> list[PricingVersionSummary]:
    vs = await PricingVersions(db).find({}, sort=[("version", -1)])
    names = await _names(db, {v.created_by for v in vs} | {v.approved_by for v in vs if v.approved_by})
    return [summary(v, names, viewer_id) for v in vs]


async def version(db: Db, version_id: str) -> PricingVersion:
    v = await PricingVersions(db).get(version_id)
    if v is None:
        not_found("That pricing version")
    return v


def _invalid(message: str, **extra: Any) -> NoReturn:
    fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_change", message, **extra)


def apply_changes(base: PricingVersion, changes: list[ChangeIn]) -> tuple[dict[str, dict[str, Any]], list[ParamChange]]:
    """Copy the base params with each change made: only existing numeric (or text) values, a
    number staying a number (whole pence staying whole), nothing negative."""
    params = copy.deepcopy(base.params)
    out: list[ParamChange] = []
    for ch in changes:
        if ch.category_id not in params:
            _invalid(f"Version {base.version} has no prices for {ch.category_id}.", category_id=ch.category_id)
        try:
            before = get_path(params[ch.category_id], ch.path)
        except KeyError:
            _invalid(f"{ch.category_id} has no setting {ch.path}.", path=ch.path)
        if isinstance(before, dict | list):
            _invalid(f"{ch.path} is a group of settings: change one value at a time.", path=ch.path)
        after = ch.after
        if isinstance(before, int | float) and not isinstance(before, bool):
            if not isinstance(after, int | float) or isinstance(after, bool) or after < 0:
                _invalid(f"{ch.path} must be a number of at least 0.", path=ch.path)
            if isinstance(before, int) and "pence" in ch.path and not isinstance(after, int):
                _invalid(f"{ch.path} is money in whole pence.", path=ch.path)
        elif not isinstance(after, type(before)):
            _invalid(f"{ch.path} must stay a {type(before).__name__}.", path=ch.path)
        if after == before:
            _invalid(f"{ch.path} is already {before}.", path=ch.path)
        set_path(params[ch.category_id], ch.path, after)
        out.append(ParamChange(category_id=ch.category_id, path=ch.path, before=before, after=after))
    return params, out


async def check_prices(db: Db, params: dict[str, dict[str, Any]]) -> None:
    """Every live category must still price its default answers with the new params."""
    for cat in await Categories(db).live():
        try:
            est = price(
                cat, defaults_for(cat), params[cat.id], TEST_LAWN_M2 if cat.measure == "lawn" else None, "medium"
            )
        except (PricingError, KeyError, TypeError, ValueError, ArithmeticError) as e:
            _invalid(f"With this change {cat.name} can't be priced: {e}", category_id=cat.id)
        if est.price_pence <= 0:
            _invalid(f"With this change {cat.name} would cost nothing.", category_id=cat.id)


async def draft(db: Db, based_on: str, changes: list[ChangeIn], notes: str, actor: Actor) -> PricingVersionSummary:
    base = await version(db, based_on)
    params, applied = apply_changes(base, changes)
    await check_prices(db, params)
    repo = PricingVersions(db)
    for _ in range(3):  # two drafts at once may pick the same number: the unique index refuses one

        async def create(session: DbSession) -> PricingVersion:
            v = PricingVersion(
                version=await repo.next_version(session=session),
                status="draft",
                params=params,
                notes=notes,
                changes=applied,
                based_on=base.id,
                created_by=actor.user_id or "",
                created_at=utcnow(),
            )
            await repo.insert(v, session=session)
            await audit(
                db,
                actor,
                "pricing.drafted",
                Related(),
                before={"version": base.version, "id": base.id},
                after={"version": v.version, "id": v.id, "changes": [c.model_dump(mode="json") for c in applied]},
                note=notes,
                session=session,
            )
            return v

        try:
            created = await transaction(db, create)
            break
        except DuplicateKeyError:
            continue
    else:  # pragma: no cover
        fail(status.HTTP_409_CONFLICT, "busy", "Someone else is drafting a version. Try again.")
    names = await _names(db, {created.created_by})
    return summary(created, names, actor.user_id or "")


async def approve(db: Db, version_id: str, actor: Actor) -> PricingVersionSummary:
    """A different admin from the drafter makes the draft live; the live version is retired."""
    v = await version(db, version_id)
    if v.status != "draft":
        fail(status.HTTP_409_CONFLICT, "not_draft", f"Version {v.version} isn't a draft.")
    if v.created_by == actor.user_id:
        fail(
            status.HTTP_403_FORBIDDEN,
            "same_admin",
            "You drafted this version, so another admin needs to approve it.",
        )
    repo = PricingVersions(db)
    live = await repo.live()
    if live is not None and v.based_on != live.id:
        fail(
            status.HTTP_409_CONFLICT,
            "stale_draft",
            f"Version {live.version} went live after this draft was made. Draft the change again from it.",
        )

    async def go_live(session: DbSession) -> PricingVersion:
        now = utcnow()
        current = await repo.live(session=session)
        if current is not None:
            if current.id != v.based_on:
                fail(status.HTTP_409_CONFLICT, "stale_draft", "Another version has just gone live. Have another look.")
            await repo.update(
                current.id, {"status": "retired", "retired_at": now}, extra_filter={"status": "live"}, session=session
            )
        made = await repo.update(
            v.id,
            {"status": "live", "approved_by": actor.user_id, "approved_at": now},
            extra_filter={"status": "draft", "created_by": {"$ne": actor.user_id}},
            session=session,
        )
        if made is None:
            fail(status.HTTP_409_CONFLICT, "not_draft", "This draft has just changed. Have another look.")
        await audit(
            db,
            actor,
            "pricing.approved",
            Related(),
            before={"live_version": current.version if current else None, "live_id": current.id if current else None},
            after={"live_version": made.version, "live_id": made.id, "drafted_by": made.created_by},
            session=session,
        )
        return made

    made = await transaction(db, go_live)
    names = await _names(db, {made.created_by, made.approved_by or ""})
    return summary(made, names, actor.user_id or "")
