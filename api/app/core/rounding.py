"""Half-up rounding, matching JavaScript's Math.round for the positive values we use.

Python's round() rounds halves to even (round(2.5) == 2), JavaScript's Math.round
rounds them up (Math.round(2.5) == 3). The prototype is JavaScript, so everything
ported from it uses these helpers with Decimal, never round() or float maths.
"""

from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 40

type Num = Decimal | int | str


def D(value: Num | float) -> Decimal:
    """Decimal from an int, str, Decimal or a float parameter read from Mongo/JSON.

    Floats go through str() so 0.11 becomes Decimal("0.11"), not its binary expansion.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def round_half_up(value: Num | float) -> int:
    """Round to the nearest integer, halves away from zero (Math.round for x >= 0)."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_half_up_to(value: Num | float, step: Num | float) -> Decimal:
    """Round to the nearest multiple of step, halves up. round_half_up_to(8.4, 0.5) == 8.5."""
    s = D(step)
    return D(round_half_up(D(value) / s)) * s


def round_to_pound(pence: Num | float) -> int:
    """Round an amount in pence to whole pounds (still returned in pence), halves up.

    The prototype computes in pounds and calls Math.round; computing in pence and
    rounding to the nearest 100 gives identical results.
    """
    return round_half_up(D(pence) / 100) * 100
