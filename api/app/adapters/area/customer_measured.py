"""customer_measured_v0: the customer paces the lawn out, or gives its length and width.

Paced: whole big strides, a stride counting as one metre. Measured: metres or feet (1 foot is
0.3048 m), up to two decimal places. Up to four lawns (front and back, say), each 1 to 100
metres a side. Each lawn's area is rounded half-up to whole m² and the lawns are added up, so
the figures the customer sees always add up; the total must be 5 to 2,000 m². The customer's
own figures are "Fairly close", like a band (A2). Decisions.md A26 and A27.
"""

from decimal import Decimal

from app.adapters.area.base import AreaEstimateError, AreaInput, AreaLimits, AreaOptions, LawnSides
from app.adapters.area.manual_bands import TOLERANCE_NOTE
from app.core.rounding import round_half_up
from app.models.common import Address
from app.models.quotes import Measure, MeasuredLawn

FOOT_M = Decimal("0.3048")
LIMITS = AreaLimits(side_min_m=1, side_max_m=100, total_min_m2=5, total_max_m2=2000, max_lawns=4)
CENT = Decimal("0.01")


def _range_text(unit: str) -> str:
    lo, hi = LIMITS.side_min_m, LIMITS.side_max_m
    if unit == "strides":
        return f"{lo} to {hi} strides"
    if unit == "ft":
        return f"between 3.3 and 328 feet ({lo} to {hi} metres)"
    return f"between {lo} and {hi} metres"


class CustomerMeasuredV0:
    id = "customer_measured_v0"
    # The customer's own strides or tape measure: "Fairly close", the same as a band (A26).
    confidence = "medium"
    methods = ("paced", "measured")

    async def options(self, address: Address | None) -> AreaOptions:
        return AreaOptions(
            estimator=self.id,
            confidence=self.confidence,
            methods=list(self.methods),
            limits=LIMITS,
            tolerance_note=TOLERANCE_NOTE,
        )

    async def estimate(self, address: Address | None, given: AreaInput) -> Measure:
        if given.method not in self.methods:
            raise AreaEstimateError("Pace your lawn out or give its length and width")
        if not given.lawns:
            raise AreaEstimateError("Give the length and width of your lawn")
        if len(given.lawns) > LIMITS.max_lawns:
            raise AreaEstimateError(f"Add up to {LIMITS.max_lawns} lawns", code="lawn_size_invalid")
        unit = "strides" if given.method == "paced" else given.unit
        several = len(given.lawns) > 1
        lawns = [self._lawn(i, lw, unit, several) for i, lw in enumerate(given.lawns)]
        total = sum(lw.area_m2 for lw in lawns)
        if total < LIMITS.total_min_m2:
            raise AreaEstimateError(
                f"That's only {total} m². Check the sizes: we can price lawns from {LIMITS.total_min_m2} m².",
                code="lawn_size_invalid",
            )
        if total > LIMITS.total_max_m2:
            raise AreaEstimateError(
                f"That's {total:,} m², more than the {LIMITS.total_max_m2:,} m² we can price here. Check the sizes.",
                code="lawn_size_invalid",
            )
        return Measure(
            estimator=self.id,
            method=given.method,
            area_m2=total,
            confidence=self.confidence,
            unit=unit,
            lawns=lawns,
        )

    def _lawn(self, i: int, given: LawnSides, unit: str, several: bool) -> MeasuredLawn:
        metres: dict[str, Decimal] = {}
        for side in ("length", "width"):
            value: Decimal = getattr(given, side)
            what = f"Lawn {i + 1}: the {side}" if several else f"The {side}"

            def bad(message: str, side: str = side) -> AreaEstimateError:
                return AreaEstimateError(message, code="lawn_size_invalid", lawn=i, side=side)

            if unit == "strides" and value != value.to_integral_value():
                raise bad(f"{what} is a whole number of strides.")
            if unit != "strides" and value != value.quantize(CENT):
                raise bad(f"{what} needs at most two decimal places.")
            m = value * FOOT_M if unit == "ft" else value
            if not LIMITS.side_min_m <= m <= LIMITS.side_max_m:
                raise bad(f"{what} must be {_range_text(unit)}.")
            metres[side] = m
        return MeasuredLawn(
            length=float(given.length),
            width=float(given.width),
            length_m=float(metres["length"]),
            width_m=float(metres["width"]),
            area_m2=round_half_up(metres["length"] * metres["width"]),
        )
