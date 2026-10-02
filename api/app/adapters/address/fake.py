"""A dozen made-up addresses around Hazlemere, Widmer End, Holmer Green, Tylers Green
and Penn. UPRNs start 99900 so they can never be mistaken for real ones; coordinates
are approximately right for each village, which is what distance matching needs.
"""

from typing import Literal

from app.adapters.address.base import AddressSuggestion
from app.core.geo import district_of
from app.models.common import Address


def _a(n: int, line1: str, locality: str, postcode: str, lat: float, lng: float) -> tuple[str, Address]:
    label = f"{line1}, {locality}, {postcode}"
    return f"fake_{n:02d}", Address(
        line1=line1,
        locality=locality,
        town="High Wycombe",
        postcode=postcode,
        district=district_of(postcode),
        uprn=f"99900{n:07d}",
        lat=lat,
        lng=lng,
        label=label,
    )


ADDRESSES: dict[str, Address] = dict(
    [
        _a(1, "12 Orchard Way", "Hazlemere", "HP15 7QT", 51.6541, -0.7139),
        _a(2, "3 Beech Tree Road", "Hazlemere", "HP15 7RB", 51.6567, -0.7108),
        _a(3, "27 Park Lane", "Hazlemere", "HP15 7HN", 51.6522, -0.7182),
        _a(4, "8 Copners Drive", "Holmer Green", "HP15 6SB", 51.6669, -0.7044),
        _a(5, "41 Earl Howe Road", "Holmer Green", "HP15 6QT", 51.6702, -0.7067),
        _a(6, "5 Cockpit Road", "Widmer End", "HP15 6NF", 51.6655, -0.7330),
        _a(7, "14 Clay Lane", "Widmer End", "HP15 6PA", 51.6631, -0.7362),
        _a(8, "22 Grays Lane", "Widmer End", "HP15 6NP", 51.6676, -0.7301),
        _a(9, "6 Hammersley Lane", "Tylers Green", "HP10 8HE", 51.6372, -0.6893),
        _a(10, "2 Church Road", "Penn", "HP10 8NX", 51.6318, -0.6726),
        _a(11, "17 Elm Road", "Penn", "HP10 8LG", 51.6345, -0.6779),
        _a(12, "Beacon Cottage, Beacon Hill", "Penn", "HP10 8ND", 51.6299, -0.6810),
    ]
)


class FakeAddressLookup:
    name: Literal["fake"] = "fake"

    async def search(self, query: str, *, limit: int = 8) -> list[AddressSuggestion]:
        words = [w for w in query.lower().replace(",", " ").split() if w]
        hits = [
            AddressSuggestion(id=k, label=a.label)
            for k, a in ADDRESSES.items()
            if words and all(w in a.label.lower() for w in words)
        ]
        return hits[:limit]

    async def resolve(self, suggestion_id: str) -> Address | None:
        return ADDRESSES.get(suggestion_id)
