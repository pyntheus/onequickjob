"""The admin map (A30 to A35): where the jobs are, where providers reach, and where demand is
outrunning coverage, so the team knows where to recruit. Everything the layers need is worked out
here, so it's tested: the features, the H3 concentration grid and the uncovered-demand rule. The
web only draws. Admins only: request and job pins sit on customers' exact addresses."""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import h3
from fastapi import status

from app.admin.overview import WAITING_AFTER
from app.admin.schemas import (
    HexBand,
    HexCount,
    HexFeature,
    HexGrid,
    HexLayer,
    JobFeature,
    JobLayer,
    JobPin,
    LngLat,
    MapData,
    MapLayerName,
    PointGeometry,
    PolygonGeometry,
    ProviderFeature,
    ProviderLayer,
    ProviderPin,
    ReachArea,
    ReachFeature,
    ReachLayer,
    RequestFeature,
    RequestLayer,
    RequestPin,
    ShadeBy,
)
from app.admin.views import age_text
from app.core.db import Db
from app.core.errors import fail
from app.core.geo import EARTH_RADIUS_MILES
from app.core.timeutil import london_today, utcnow
from app.models.bookings import Booking
from app.models.common import Address
from app.models.job_requests import JobRequest
from app.models.providers import Provider
from app.models.visits import Visit
from app.repos import Bookings, Categories, JobRequests, Providers, Visits
from app.services.eligibility import TAKES_JOBS, within_reach
from app.services.postcodes import place_home

HEX_RESOLUTION = 8  # cells about 1 km across (0.74 km²)
HEX_BANDS = 5
DEFAULT_RANGE_DAYS = 30  # completed jobs: the last 30 days, today included
MAX_RANGE_DAYS = 366
REACH_POINTS = 64  # vertices of a travel-radius circle
UPCOMING = ("scheduled", "in_progress")


def lng_lat(lat: float, lng: float, places: int = 6) -> LngLat:
    return [round(lng, places), round(lat, places)]


def point(lat: float, lng: float) -> PointGeometry:
    return PointGeometry(coordinates=lng_lat(lat, lng))


def date_range(start: date | None, end: date | None, today: date | None = None) -> tuple[date, date]:
    """The completed jobs' range, London days inclusive: 30 days ending today by default, 30 days
    ending `end` if only that is given, `start` to today if only that is. At most a year."""
    end = end or today or london_today()
    start = start or end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if start > end:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_range", "The start date must be on or before the end date.")
    if (end - start).days >= MAX_RANGE_DAYS:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_range", "Choose a range of a year or less.")
    return start, end


# ---------------------------------------------------------------- the uncovered-demand rule (A32)


@dataclass(frozen=True)
class Coverage:
    in_reach: int
    doing_it: int

    @property
    def uncovered(self) -> bool:
        return self.in_reach == 0


def coverage(request: JobRequest, providers: list[Provider]) -> Coverage:
    """How many providers who take jobs (active, or active with payouts paused) have the request
    inside their travel radius, measured as the broadcast measures it. None: uncovered demand.
    It's geography only: a nearby provider who doesn't do this job still covers the place (the
    panel says how many in reach do it)."""
    near = [p for p in providers if p.status in TAKES_JOBS and within_reach(p, request)]
    return Coverage(in_reach=len(near), doing_it=sum(request.category_id in p.skills for p in near))


# ---------------------------------------------------------------- concentration (A34)


def hex_of(lat: float, lng: float) -> str:
    return h3.latlng_to_cell(lat, lng, HEX_RESOLUTION)


def hex_ring(cell: str) -> list[LngLat]:
    ring = [lng_lat(lat, lng) for lat, lng in h3.cell_to_boundary(cell)]
    return [*ring, ring[0]]


def bands(top: int, n: int = HEX_BANDS) -> list[HexBand]:
    """Legend bands for counts 1..top: one per count up to n, else n bands split evenly."""
    if top < 1:
        return []
    starts = list(range(1, top + 1)) if top <= n else sorted({1, *(-(-top * i // n) for i in range(1, n))})
    out = []
    for level, lo in enumerate(starts):
        hi = starts[level + 1] - 1 if level + 1 < len(starts) else top
        out.append(HexBand(level=level, min=lo, max=hi, label=str(lo) if lo == hi else f"{lo} to {hi}"))
    return out


def level_of(count: int, legend: list[HexBand]) -> int:
    return max((b.level for b in legend if b.min <= count), default=0)


def hex_grid(shade_by: str, points: list[tuple[float, float, int]]) -> HexGrid:
    """Counts per H3 cell; each point is (lat, lng, how many it counts for)."""
    counts: dict[str, int] = defaultdict(int)
    for lat, lng, n in points:
        counts[hex_of(lat, lng)] += n
    top = max(counts.values(), default=0)
    legend = bands(top)
    cells = [
        HexFeature(
            id=cell,
            geometry=PolygonGeometry(coordinates=[hex_ring(cell)]),
            properties=HexCount(cell=cell, count=n, level=level_of(n, legend)),
        )
        for cell, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return HexGrid(
        shade_by=shade_by,  # type: ignore[arg-type]
        resolution=HEX_RESOLUTION,
        total=sum(counts.values()),
        max=top,
        legend=legend,
        cells=HexLayer(features=cells),
    )


# ---------------------------------------------------------------- travel radius


def circle(lat: float, lng: float, miles: float, n: int = REACH_POINTS) -> list[LngLat]:
    """A closed ring `miles` from the centre all round (great-circle destination points)."""
    d = miles / EARTH_RADIUS_MILES
    p1, l1 = math.radians(lat), math.radians(lng)
    ring = []
    for k in range(n):
        bearing = 2 * math.pi * k / n
        p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(bearing))
        l2 = l1 + math.atan2(math.sin(bearing) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
        ring.append(lng_lat(math.degrees(p2), math.degrees(l2), 5))
    return [*ring, ring[0]]


# ---------------------------------------------------------------- layers


async def _requests(db: Db, providers: list[Provider], names: dict[str, str], now: datetime) -> list[RequestFeature]:
    out = []
    for r in await JobRequests(db).find({"status": "open"}, sort=[("created_at", 1)]):
        cov = coverage(r, providers)
        pending_raise = bool(r.price_change and r.price_change.status == "pending")
        out.append(
            RequestFeature(
                id=r.id,
                geometry=point(r.address.lat, r.address.lng),
                properties=RequestPin(
                    request_id=r.id,
                    ref=r.ref,
                    category_id=r.category_id,
                    category_name=names.get(r.category_id, r.category_id),
                    area=r.address.area,
                    district=r.address.district,
                    created_at=r.created_at,
                    age_text=age_text(r.created_at, now),
                    guide_pence=r.guide_pence,
                    waiting=r.created_at <= now - WAITING_AFTER,
                    uncovered=cov.uncovered,
                    in_reach=cov.in_reach,
                    in_reach_doing_it=cov.doing_it,
                    cover=r.cover_for_visit_id is not None,
                    awaiting_customer=pending_raise,
                ),
            )
        )
    return out


def _jobs(
    visits: list[Visit],
    bookings: dict[str, Booking],
    providers: dict[str, Provider],
    names: dict[str, str],
    *,
    latest: bool,
) -> JobLayer:
    """One pin per booking: its visits in the layer, dated by the next one (booked) or the latest
    (completed), with that visit's provider and price. A visit whose booking isn't found has no
    address and is left out."""
    by_booking: dict[str, list[Visit]] = defaultdict(list)
    for v in visits:
        if v.booking_id in bookings:
            by_booking[v.booking_id].append(v)
    features = []
    for booking_id, vs in by_booking.items():
        b = bookings[booking_id]
        vs.sort(key=lambda v: v.scheduled_start)
        shown = vs[-1] if latest else vs[0]
        a: Address = b.address
        # The shown visit's provider: on a cover that's the covering provider, not the booking's.
        p = providers.get(shown.provider_id)
        covering = shown.performer.kind == "cover" or shown.provider_id != b.provider_id
        regular = providers.get(b.provider_id) if covering else None
        features.append(
            JobFeature(
                id=booking_id,
                geometry=point(a.lat, a.lng),
                properties=JobPin(
                    booking_id=booking_id,
                    booking_ref=b.ref,
                    category_id=b.category_id,
                    category_name=names.get(b.category_id, b.category_id),
                    area=a.area,
                    district=a.district,
                    provider_id=shown.provider_id,
                    provider_short=p.short if p else "",
                    covering_for=regular.short if regular else None,
                    own_customer=b.source == "own_customer" and not covering,
                    visits=len(vs),
                    visit_date=shown.local_date,
                    price_pence=shown.price_pence,
                ),
            )
        )
    features.sort(key=lambda f: (f.properties.visit_date, f.id), reverse=latest)
    return JobLayer(features=features, visits=sum(f.properties.visits for f in features))


async def _visits(db: Db, flt: dict) -> tuple[list[Visit], dict[str, Booking]]:
    visits = await Visits(db).find(flt)
    ids = list({v.booking_id for v in visits})
    return visits, {b.id: b for b in await Bookings(db).find({"_id": {"$in": ids}})}


def _providers(providers: list[Provider], names: dict[str, str]) -> tuple[ProviderLayer, ReachLayer]:
    pins, reach = [], []
    for p in sorted(providers, key=lambda p: p.short):
        at, placed = place_home(p.home.postcode, p.home.location)
        covers = p.status in TAKES_JOBS
        pins.append(
            ProviderFeature(
                id=p.id,
                geometry=point(at.lat, at.lng),
                properties=ProviderPin(
                    provider_id=p.id,
                    short=p.short,
                    initials=p.initials,
                    status=p.status,
                    area=p.home.area,
                    district=p.home.district,
                    travel_radius_miles=p.travel_radius_miles,
                    placed_at=placed,
                    covers=covers,
                    jobs=[names[s] for s in p.skills if s in names],
                ),
            )
        )
        reach.append(
            ReachFeature(
                id=p.id,
                geometry=PolygonGeometry(coordinates=[circle(at.lat, at.lng, p.travel_radius_miles)]),
                properties=ReachArea(
                    provider_id=p.id, status=p.status, travel_radius_miles=p.travel_radius_miles, covers=covers
                ),
            )
        )
    return ProviderLayer(features=pins), ReachLayer(features=reach)


def _points(layer: RequestLayer | JobLayer) -> list[tuple[float, float, int]]:
    out = []
    for f in layer.features:
        lng, lat = f.geometry.coordinates
        out.append((lat, lng, f.properties.visits if isinstance(f.properties, JobPin) else 1))
    return out


async def map_data(
    db: Db,
    layers: set[MapLayerName],
    shade_by: ShadeBy,
    start: date,
    end: date,
    now: datetime | None = None,
) -> MapData:
    """The chosen layers, and the concentration grid of the job layer chosen to shade by. Only
    what's asked for is read. `start` and `end` (London days, inclusive) apply to completed jobs."""
    now = now or utcnow()
    today = london_today(now)
    names = {c.id: c.name for c in await Categories(db).all()}
    providers = await Providers(db).find({})
    by_id = {p.id: p for p in providers}
    out = MapData(
        generated_at=now,
        from_date=start,
        to_date=end,
        waiting_after_minutes=int(WAITING_AFTER.total_seconds() // 60),
    )
    wanted = set(layers) | ({shade_by} if shade_by != "none" else set())

    if wanted & {"open", "uncovered"}:
        pins = await _requests(db, providers, names, now)
        if "open" in layers or shade_by == "open":
            out.open = RequestLayer(features=pins)
        if "uncovered" in layers:
            out.uncovered = RequestLayer(features=[f for f in pins if f.properties.uncovered])
    if "booked" in wanted:
        visits, bookings = await _visits(db, {"status": {"$in": UPCOMING}, "local_date": {"$gte": today.isoformat()}})
        out.booked = _jobs(visits, bookings, by_id, names, latest=False)
    if "completed" in wanted:
        visits, bookings = await _visits(
            db, {"status": "finished", "local_date": {"$gte": start.isoformat(), "$lte": end.isoformat()}}
        )
        out.completed = _jobs(visits, bookings, by_id, names, latest=True)
    if "providers" in layers:
        out.providers, out.reach = _providers(providers, names)

    if shade_by != "none":
        source = {"open": out.open, "booked": out.booked, "completed": out.completed}[shade_by]
        out.hexes = hex_grid(shade_by, _points(source) if source else [])
    # A layer read only for shading isn't sent as pins.
    for name in ("open", "booked", "completed"):
        if name not in layers:
            setattr(out, name, None)
    return out
