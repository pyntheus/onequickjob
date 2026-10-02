"""Distances. Straight-line (haversine) miles; road distance is estimated by L2 for
mileage as straight-line x 1.25 (decisions.md)."""

import math
import re

EARTH_RADIUS_MILES = 3958.8
ROAD_FACTOR = 1.25

_POSTCODE = re.compile(r"^\s*([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\s*$", re.IGNORECASE)


def miles_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def normalise_postcode(raw: str) -> str:
    m = _POSTCODE.match(raw)
    if not m:
        raise ValueError("That doesn't look like a UK postcode")
    return f"{m.group(1).upper()} {m.group(2).upper()}"


def district_of(postcode: str) -> str:
    """HP15 7QT -> HP15 (the outward code, used for broadcast copy and admin tiles)."""
    return normalise_postcode(postcode).split(" ")[0]


def approximate(lat: float, lng: float) -> tuple[float, float]:
    """Coarsen a location to about 1 km so providers see the area, not the house."""
    return round(lat, 2), round(lng, 2)
