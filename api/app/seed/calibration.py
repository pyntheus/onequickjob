"""Calibration points: the prototype's CAL_POINTS (mulberry32, seed 11), each a finished,
charged visit with its estimate and recorded time, so admin pricing has real data.

Some jobs were countered (roughly the prototype's CAL_TABLE counter rates), so those
have a booked request, its quote and the offers; the rest were taken at the guide price.
"""

import math
from datetime import timedelta

from app.adapters.area.manual_bands import ManualBandsV0
from app.core.geo import approximate
from app.core.rounding import D, round_half_up, round_to_pound
from app.core.timeutil import weekday_key
from app.models.common import GeoPoint
from app.models.job_requests import Booked, Broadcast, JobRequest, RequestEvent, When
from app.models.offers import Offer
from app.models.quotes import Measure, Quote, QuoteResult
from app.pricing.answers import defaults_for
from app.seed.context import Ctx, mulberry32, sid
from app.seed.history import Diary
from app.seed.jobs import add_booking, add_visit, unit_for
from app.services.quotes import fee_split

# (segment, category, count, est lo, est hi, factor lo, factor hi): CAL_POINTS in the prototype.
SEGMENTS = [
    ("mowing", "mowing", 34, 22, 60, 0.85, 1.18),
    ("first", "mowing", 12, 45, 90, 1.08, 1.55),
    ("hedges", "hedges", 16, 40, 160, 0.88, 1.38),
    ("clearance", "clearance", 10, 90, 220, 0.72, 1.45),
]
PROVIDERS = {
    "mowing": ["mike", "sue", "alan", "jan"],
    "first": ["mike", "sue", "alan", "jan"],
    "hedges": ["sue", "gary", "jan"],
    "clearance": ["mike", "gary"],
}
COUNTER_RATE = {"mowing": 0.26, "first": 0.57, "hedges": 0.62, "clearance": 0.82}
UPLIFT_PENCE = {"mowing": 400, "first": 900, "hedges": 1400, "clearance": 3500}
REASONS = {
    "mowing": "Tricky access",
    "first": "Longer grass than described",
    "hedges": "More waste than described",
    "clearance": "More waste than described",
}
OVERRUN_FLAGS = {
    "mowing": ["Access was harder", "Weather slowed me down"],
    "first": ["Grass was longer than described"],
    "hedges": ["More waste than expected", "Access was harder"],
    "clearance": ["More waste than expected"],
}
CLEARANCE_BY_MINS = [(90, 6500), (150, 11000), (240, 19000), (360, 32000)]


def cal_points() -> list[tuple[str, int, int]]:
    """Exactly the prototype's CAL_POINTS: (segment, estimated minutes, actual minutes)."""
    r = mulberry32(11)
    pts: list[tuple[str, int, int]] = []
    for seg, _cat, n, lo, hi, flo, fhi in SEGMENTS:
        for _ in range(n):
            est = lo + r() * (hi - lo)
            pts.append((seg, round_half_up(D(est)), round_half_up(D(est * (flo + r() * (fhi - flo))))))
    return pts


def guide_for(seg: str, est: int) -> int:
    """A guide price consistent with the estimate (the lawn and hedge models' £45 an hour)."""
    if seg == "mowing":  # routine visit on a fortnightly plan: 8% off
        return max(2800, round_to_pound((D(est) * 75 + 400) * D("0.92")))
    if seg == "first":
        return max(2800, round_to_pound(D(est) * 75 + 400))
    if seg == "hedges":
        return max(4000, round_to_pound(D(est) * 75 + 1700))
    return min(CLEARANCE_BY_MINS, key=lambda m: abs(m[0] - est))[1]


def countered(i: int, rate: float) -> bool:
    return math.floor((i + 1) * rate) > math.floor(i * rate)


async def seed_calibration(ctx: Ctx, diary: Diary) -> None:
    rnd = mulberry32(90)
    pool = [c["key"] for c in ctx.people["pool"]]
    seg_index: dict[str, int] = {}
    for idx, (seg, est, act) in enumerate(cal_points()):
        i = seg_index.get(seg, 0)
        seg_index[seg] = i + 1
        cat_id = next(c for s, c, *_ in SEGMENTS if s == seg)
        names = PROVIDERS[seg]
        pkey = names[i % len(names)]
        provider = ctx.providers[pkey]
        days_ago = 2 + int(rnd() * 88)
        day = ctx.day(days_ago)
        for _ in range(7):
            if weekday_key(day) in provider.working_days:
                break
            day -= timedelta(days=1)
        slot = diary.free_slot(pkey, day, est) or "08:30"
        diary.book(pkey, day, slot, est)
        customer = pool[(idx * 3) % len(pool)]
        guide = guide_for(seg, est)
        key = f"cal:{idx}"
        over = act * 10 > est * 11
        options = OVERRUN_FLAGS[seg]
        flags = [options[int(rnd() * len(options))]] if over else []
        posted = ctx.at(day - timedelta(days=3), "18:15")

        request_id = None
        price_pence = guide
        if countered(i, COUNTER_RATE[seg]):
            price_pence = guide + UPLIFT_PENCE[seg]
            request_id = await _countered_request(
                ctx, key, seg, cat_id, customer, pkey, guide, price_pence, est, posted
            )
        booking = add_booking(
            ctx,
            key=key,
            customer=customer,
            provider=pkey,
            category_id=cat_id,
            source="platform",
            via="counter" if request_id else "guide",
            price_pence=price_pence,
            created_at=posted + timedelta(hours=1),
            request_id=request_id,
        )
        add_visit(
            ctx,
            key=key,
            booking=booking,
            day=day,
            hhmm=slot,
            est_mins=est,
            actual_mins=act,
            is_first=seg == "first",
            flags=flags,
        )
        ctx.w.add(booking)


async def _countered_request(
    ctx: Ctx, key: str, seg: str, cat_id: str, customer: str, pkey: str, guide: int, price_pence: int, est: int, posted
) -> str:
    """A booked request whose customer accepted a counter (sometimes after keeping waiting once)."""
    cat = ctx.cats[cat_id]
    params = ctx.pricing.params[cat_id]
    cust = ctx.customers[customer]
    address = cust.addresses[0]
    answers = defaults_for(cat)
    measure = None
    if cat.measure == "lawn":
        answers = {**answers, "grassState": "long" if seg == "first" else "kept", "frequency": "oneoff"}
        measure = Measure(
            estimator=ManualBandsV0.id, area_m2=190, band="large", adjust="right", confidence=ManualBandsV0.confidence
        )
    request_id, booking_id = sid("request", key), sid("booking", key)
    spread = (float(params["spread"][0]), float(params["spread"][1]))
    quote = Quote(
        id=sid("quote", key),
        category_id=cat_id,
        answers=answers,
        measure=measure,
        address=address,
        pricing_version_id=ctx.pricing.id,
        pricing_version=ctx.pricing.version,
        result=QuoteResult(
            price_pence=guide,
            mins=est,
            low_pence=round_to_pound(D(guide) * D(str(spread[0]))),
            high_pence=round_to_pound(D(guide) * D(str(spread[1]))),
            spread=spread,
            # Lawn confidence follows the area estimator (ruling after F review), others the model.
            confidence=measure.confidence if measure else params["confidence"],
            unit=unit_for(cat_id, False),
        ),
        fee=fee_split(guide, settings=ctx.s),
        user_id=cust.user_id,
        request_id=request_id,
        **ctx.timestamps(posted - timedelta(minutes=3)),
    )
    ctx.w.add(quote)
    others = [k for k in PROVIDERS[seg] if k != pkey]
    events = [
        RequestEvent(at=posted, kind="created"),
        RequestEvent(at=posted + timedelta(seconds=5), kind="broadcast", count=len(PROVIDERS[seg])),
    ]
    accepted_at = posted + timedelta(minutes=55)
    if int(key.split(":")[1]) % 3 == 0 and others:
        other = ctx.providers[others[0]]
        at = posted + timedelta(minutes=20)
        declined = Offer(
            id=sid("offer", key, "declined"),
            request_id=request_id,
            provider_id=other.id,
            price_pence=price_pence + 500,
            guide_pence=guide,
            reasons=[REASONS[seg]],
            status="declined",
            decided_at=at + timedelta(minutes=10),
            **ctx.timestamps(at),
        )
        ctx.w.add(declined)
        events += [
            RequestEvent(
                at=at, kind="countered", provider_id=other.id, offer_id=declined.id, price_pence=declined.price_pence
            ),
            RequestEvent(
                at=at + timedelta(minutes=10), kind="counter_declined", provider_id=other.id, offer_id=declined.id
            ),
        ]
    provider = ctx.providers[pkey]
    offer = Offer(
        id=sid("offer", key),
        request_id=request_id,
        provider_id=provider.id,
        price_pence=price_pence,
        guide_pence=guide,
        reasons=[REASONS[seg]],
        status="accepted",
        decided_at=accepted_at,
        **ctx.timestamps(posted + timedelta(minutes=40)),
    )
    ctx.w.add(offer)
    events += [
        RequestEvent(
            at=offer.created_at, kind="countered", provider_id=provider.id, offer_id=offer.id, price_pence=price_pence
        ),
        RequestEvent(
            at=accepted_at, kind="accepted", provider_id=provider.id, offer_id=offer.id, price_pence=price_pence
        ),
    ]
    lat, lng = approximate(address.lat, address.lng)
    ctx.w.add(
        JobRequest(
            id=request_id,
            ref=ctx.next_request_ref(),
            customer_id=cust.id,
            category_id=cat_id,
            quote_id=quote.id,
            pricing_version_id=ctx.pricing.id,
            answers=answers,
            measure=measure,
            address=address,
            approx=GeoPoint(lat=lat, lng=lng),
            when=When(),
            recurring=False,
            frequency=None,
            guide_pence=guide,
            mins=est,
            unit=unit_for(cat_id, False),
            status="booked",
            broadcast=Broadcast(
                at=posted + timedelta(seconds=5), provider_ids=[ctx.providers[k].id for k in PROVIDERS[seg]]
            ),
            viewed_by=[ctx.providers[k].id for k in PROVIDERS[seg]],
            events=events,
            booked=Booked(
                booking_id=booking_id,
                provider_id=provider.id,
                price_pence=price_pence,
                via="counter",
                offer_id=offer.id,
                at=accepted_at,
            ),
            **ctx.timestamps(posted),
        )
    )
    return request_id
