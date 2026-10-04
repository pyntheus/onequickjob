"""The lawn size in words, from a Measure, for every screen that shows one (decisions.md A26).

Customer copy never says the lawn was "measured" (A6): it's the size the customer chose,
paced out or gave.
"""

from decimal import ROUND_HALF_UP, Decimal

from app.adapters.area.manual_bands import BANDS
from app.core.rounding import D
from app.models.quotes import Measure, MeasuredLawn

BAND_WORDS = {b.id: b.label.lower() for b in BANDS}
ADJUST_WORDS = {"smaller": ", a bit smaller than that", "bigger": ", a bit bigger than that"}


def metres_text(m: float) -> str:
    """A side to the nearest 10 cm, half-up: 9.144 is "9.1", 12.0 is "12"."""
    s = f"{D(m).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}"
    return s.removesuffix(".0")


def area_text(m2: int) -> str:
    return f"{m2:,} m²"


def lawn_text(lawn: MeasuredLawn) -> str:
    """ "about 12 × 8 metres (96 m²)": length by width, as the customer gave them."""
    return f"about {metres_text(lawn.length_m)} × {metres_text(lawn.width_m)} metres ({area_text(lawn.area_m2)})"


def result_text(m: Measure) -> str:
    """The lawn step's answer: "That's about 12 × 8 metres (96 m²)", or for several lawns
    "That's about 150 m² in total across 2 lawns"."""
    if not m.lawns:
        return f"That's about {area_text(m.area_m2)}"
    if len(m.lawns) == 1:
        return f"That's {lawn_text(m.lawns[0])}"
    return f"That's about {area_text(m.area_m2)} in total across {len(m.lawns)} lawns"


def size_phrase(m: Measure | None) -> str | None:
    """What a guide price is for, to follow "for": "a large lawn (about 190 m²)", "a lawn of
    about 12 × 8 metres, paced out (96 m²)", "2 lawns, about 150 m² in total"."""
    if m is None:
        return None
    if m.method == "band" or not m.lawns:
        band = BAND_WORDS.get(m.band or "")
        if band is None:
            return f"a lawn of about {area_text(m.area_m2)}"
        return f"a {band} lawn{ADJUST_WORDS.get(m.adjust or 'right', '')} (about {area_text(m.area_m2)})"
    paced = m.method == "paced"
    if len(m.lawns) == 1:
        lw = m.lawns[0]
        sides = f"{metres_text(lw.length_m)} × {metres_text(lw.width_m)} metres"
        return f"a lawn of about {sides}{', paced out' if paced else ''} ({area_text(lw.area_m2)})"
    how = " paced out" if paced else ""
    return f"{len(m.lawns)} lawns{how}, about {area_text(m.area_m2)} in total"


def fact_text(m: Measure) -> str:
    """The provider's facts grid: "About 190 m²", or "About 150 m² across 2 lawns"."""
    lawns = f" across {len(m.lawns)} lawns" if len(m.lawns) > 1 else ""
    return f"About {area_text(m.area_m2)}{lawns}"
