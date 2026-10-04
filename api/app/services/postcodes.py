"""Where a postcode is, as against where an address in it is (A33).

The admin map plots a provider at their home postcode's centroid, never at their home address,
which is what `Home.location` holds for anyone who signed up through the address look-up. The
table covers the demo's postcodes: a seeded provider is given only a postcode and its position
(seed/people.json), so those positions are the centroids, as approximate as the fake addresses.
Real centroids come from the ONS Postcode Directory (Open Government Licence); loading them is
parked (A33). A postcode the table doesn't know is placed at the home rounded to about 1 km
(`geo.approximate`, as providers see a job before booking it), which is coarser than a postcode,
so a home address is never shown.
"""

from typing import Literal

from app.core.geo import approximate, normalise_postcode
from app.models.common import GeoPoint

Placed = Literal["postcode", "approximate"]

CENTROIDS: dict[str, tuple[float, float]] = {
    "HP10 8LN": (51.633, -0.675),  # Penn
    "HP10 8NE": (51.631, -0.68),  # Penn
    "HP12 3RS": (51.623, -0.767),  # Cressex
    "HP12 4QT": (51.613, -0.781),  # Booker
    "HP12 4RD": (51.615, -0.783),  # Booker
    "HP13 5AB": (51.642, -0.738),  # Terriers
    "HP13 5UH": (51.647, -0.779),  # Downley
    "HP15 6NT": (51.666, -0.732),  # Widmer End
    "HP15 6TA": (51.669, -0.7),  # Holmer Green
    "HP15 7LH": (51.6455, -0.6935),  # Hazlemere
    "HP9 1QD": (51.607, -0.644),  # Beaconsfield
    "SL7 1AB": (51.571, -0.776),  # Marlow
}


def centroid(postcode: str) -> GeoPoint | None:
    try:
        known = CENTROIDS.get(normalise_postcode(postcode))
    except ValueError:
        return None
    return GeoPoint(lat=known[0], lng=known[1]) if known else None


def place_home(postcode: str, home: GeoPoint) -> tuple[GeoPoint, Placed]:
    """Where to show someone who lives at `home` in `postcode`: the postcode's centroid, or the
    home rounded to about 1 km when the centroid isn't known."""
    if (c := centroid(postcode)) is not None:
        return c, "postcode"
    lat, lng = approximate(home.lat, home.lng)
    return GeoPoint(lat=lat, lng=lng), "approximate"
