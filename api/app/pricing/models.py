"""Pricing models: a direct port of PRICING_MODELS in docs/design/prototype.jsx.

Each model is a pure function (answers, params) -> Estimate. Params come from the live
pricing version (pricing_versions collection), never from code, and are in pence.
Wherever the prototype calls Math.round we round half-up with Decimal:
  - on minutes:            round_half_up(...)
  - on whole-pound prices: round_to_pound(...)   (prototype pounds -> our pence)
  - on half hours:         round_half_up_to(..., 0.5)
Multiplications come before divisions so the arithmetic stays exact.

tests/shared/test_pricing_prototype.py checks every model against the prototype's own
JavaScript over hundreds of random answers, so keep the structure line-for-line.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from app.core.rounding import D, round_half_up, round_half_up_to, round_to_pound

type Confidence = Literal["high", "medium", "low"]
type Unit = Literal["a visit", "one-off", "a clean", "a walk"]
type Answers = Mapping[str, Any]
type Params = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Estimate:
    price_pence: int
    mins: int
    spread: tuple[Decimal, Decimal]
    # None for measured categories (lawns): the area estimator decides, and engine.price applies it.
    confidence: Confidence | None
    unit: Unit
    first_pence: int | None = None
    first_mins: int | None = None
    first_reason: str | None = None
    note: str | None = None
    conf_note: str | None = None

    @property
    def low_pence(self) -> int:
        return round_to_pound(D(self.price_pence) * self.spread[0])

    @property
    def high_pence(self) -> int:
        return round_to_pound(D(self.price_pence) * self.spread[1])


def _spread(value: Any) -> tuple[Decimal, Decimal]:
    lo, hi = value
    return D(lo), D(hi)


def _get(table: Mapping[str, Any], key: Any, default: Any) -> Decimal:
    """JS `table[key] ?? default`."""
    v = table.get(key) if isinstance(key, str) else None
    return D(default if v is None else v)


def lawn_area_v1(a: Answers, p: Params) -> Estimate:
    growth = _get(p["growth"], a.get("grassState"), p["growth_default"])
    base = D(p["base_mins"]) + D(a["area"]) * D(p["mins_per_m2"])
    waste = a.get("waste")
    waste_mins = _get(p["waste_mins"], waste, 0)
    disposal = _get(p["disposal_pence"], waste, 0)
    frequency = a.get("frequency")
    discount = _get(p["discount"], frequency, 0)
    recurring = frequency != "oneoff"
    routine = round_half_up(base + waste_mins)
    first_mins = round_half_up(base * growth + waste_mins)

    def cost(m: int, d: Decimal) -> int:
        return max(int(p["min_pence"]), round_to_pound((D(m) * D(p["hourly_pence"]) / 60 + disposal) * (1 - d)))

    common: dict[str, Any] = {
        "spread": _spread(p["spread"]),
        # How sure we are depends on how the area was found, not on this model: the
        # AreaEstimator's confidence is applied by engine.price (decisions.md, after F review).
        "confidence": None,
        "conf_note": p.get("conf_note"),
    }
    if recurring and growth > 1:
        return Estimate(
            price_pence=cost(routine, discount),
            first_pence=cost(first_mins, D(0)),
            mins=routine,
            first_mins=first_mins,
            first_reason=p["first_reason"],
            unit="a visit",
            **common,
        )
    return Estimate(
        price_pence=cost(first_mins, discount if recurring else D(0)),
        mins=first_mins,
        unit="a visit" if recurring else "one-off",
        **common,
    )


def hedge_length_v1(a: Answers, p: Params) -> Estimate:
    per_m = _get(p["per_m_mins"], a.get("height"), p["per_m_default"])
    length = D(a["length"])
    sides = D(p["both_sides_mult"]) if a.get("sides") == "both" else D(1)
    mins = round_half_up(D(p["base_mins"]) + length * per_m * sides)
    disposal = (
        D(p["disposal_base_pence"]) + length * D(p["disposal_per_m_pence"]) if a.get("waste") == "takeaway" else D(0)
    )
    price = max(int(p["min_pence"]), round_to_pound(D(mins) * D(p["hourly_pence"]) / 60 + disposal))
    return Estimate(
        price_pence=price,
        mins=mins,
        spread=_spread(p["spread"]),
        confidence=p["confidence"],
        conf_note=p.get("conf_note"),
        unit="one-off",
    )


def photo_review_v1(a: Answers, p: Params) -> Estimate:
    volume = a.get("volume")
    base = _get(p["base_pence"], volume, p["base_default_pence"])
    mins = _get(p["mins"], volume, p["mins_default"])
    price = round_to_pound(base * D(p["bag_it_mult"]) if a.get("waste") == "bags" else base)
    return Estimate(
        price_pence=price,
        mins=int(mins),
        spread=_spread(p["spread"]),
        confidence=p["confidence"],
        unit="one-off",
    )


def area_rate_v1(a: Answers, p: Params) -> Estimate:
    resand = a.get("resand") == "yes"
    extra = D(p["resand_pence"]) if resand else D(0)
    area = D(a["area"])
    rate = _get(p["rates_pence"], a.get("surface"), p["rate_default_pence"])
    price = max(int(p["min_pence"]), round_to_pound(area * (rate + extra)))
    mins = round_half_up((D(p["base_mins"]) + area * D(p["mins_per_m2"])) * (D(p["resand_mins_mult"]) if resand else 1))
    return Estimate(
        price_pence=price,
        mins=mins,
        spread=_spread(p["spread"]),
        confidence=p["confidence"],
        unit="one-off",
    )


def size_base_v1(a: Answers, p: Params) -> Estimate:
    key = a.get(p["base_key"])
    price = _get(p["base_pence"], key, 0)
    mins = _get(p["mins"], key, p["mins_default"])
    for k, v in (p.get("add_if") or {}).items():
        if a.get(k) == "yes":
            price += D(v["pence"])
            mins += D(v["mins"])
    for e in a.get("extras") or []:
        extra = (p.get("extras") or {}).get(e) or {}
        price += D(extra.get("pence") or 0)
        mins += D(extra.get("mins") or 0)
    return Estimate(
        price_pence=round_to_pound(price),
        mins=round_half_up(mins),
        spread=_spread(p["spread"]),
        confidence=p.get("confidence") or "medium",
        unit="one-off",
    )


def window_round_v1(a: Answers, p: Params) -> Estimate:
    both = D(p["both_sides_mult"]) if a.get("sides") == "both" else D(1)
    conservatory = a.get("conservatory") == "yes"
    size = a["size"]
    price = round_to_pound(D(p["base_pence"][size]) * both + (D(p["conservatory_pence"]) if conservatory else 0))
    mins = round_half_up(D(p["mins"][size]) * both + (D(p["conservatory_mins"]) if conservatory else 0))
    first_mult = D(p["first_mult"])
    common: dict[str, Any] = {"spread": _spread(p["spread"]), "confidence": p["confidence"]}
    if a.get("frequency") == "oneoff":
        return Estimate(
            price_pence=round_to_pound(D(price) * first_mult),
            mins=round_half_up(D(mins) * first_mult),
            unit="one-off",
            **common,
        )
    return Estimate(
        price_pence=price,
        first_pence=round_to_pound(D(price) * first_mult),
        mins=mins,
        first_mins=round_half_up(D(mins) * first_mult),
        first_reason=p["first_reason"],
        unit="a clean",
        **common,
    )


def rooms_hours_v1(a: Answers, p: Params) -> Estimate:
    beds = a.get("bedrooms")
    baths = a.get("bathrooms")
    hours = (
        D(p["base_hours"])
        + D(p["beds_default"] if beds is None else beds) * D(p["per_bed"])
        + D(p["baths_default"] if baths is None else baths) * D(p["per_bath"])
    )
    furnished = D(p["furnished_mult"]) if a.get("furnished") == "furnished" else D(1)
    hours *= _get(p.get("type_mult") or {}, a.get("type"), 1) * furnished
    for e in a.get("extras") or []:
        hours += _get(p.get("extras_hours") or {}, e, 0)
    hours = max(D(p["min_hours"]), round_half_up_to(hours, "0.5"))
    supplies = D(p["supplies_pence"]) if a.get("supplies") == "bring" else D(0)
    rate = D(p["rate_pence"])
    price = round_to_pound(hours * rate + supplies)
    frequency = a.get("frequency")
    if frequency and frequency != "oneoff":
        first_hours = round_half_up_to(hours * D(p["first_hours_mult"]), "0.5")
        return Estimate(
            price_pence=price,
            first_pence=round_to_pound(first_hours * rate + supplies),
            mins=round_half_up(hours * 60),
            first_mins=round_half_up(first_hours * 60),
            first_reason=p["first_reason"],
            spread=_spread(p["recurring_spread"]),
            confidence=p["recurring_confidence"],
            unit="a clean",
        )
    return Estimate(
        price_pence=price,
        mins=round_half_up(hours * 60),
        spread=_spread(p["spread"]),
        confidence=p.get("confidence") or "medium",
        unit="one-off",
    )


def decorating_v1(a: Answers, p: Params) -> Estimate:
    per = _get(p["size_hours"], a.get("size"), p["size_hours_default"])
    parts = a.get("parts") or ["walls"]
    hours = (
        (per if "walls" in parts else D(0))
        + (per * D(p["ceiling_mult"]) if "ceiling" in parts else D(0))
        + (per * D(p["woodwork_mult"]) if "woodwork" in parts else D(0))
    )
    prep = D(p["prep_mult"]) if a.get("condition") == "prep" else D(1)
    hours = round_half_up_to(hours * D(a["rooms"]) * prep, "0.5")
    return Estimate(
        price_pence=round_to_pound(hours * D(p["rate_pence"])),
        mins=round_half_up(hours * 60),
        spread=_spread(p["spread"]),
        confidence=p["confidence"],
        unit="one-off",
        note=p["notes"]["provider" if a.get("paint") == "provider" else "mine"],
    )


def counts_v1(a: Answers, p: Params) -> Estimate:
    price, mins = D(0), D(0)
    for k, n in (a.get("items") or {}).items():
        each = p["each"].get(k) or {}
        price += D(each.get("pence") or 0) * D(n)
        mins += D(each.get("mins") or 0) * D(n)
    for k, v in (p.get("add_if") or {}).items():
        if a.get(k) == "yes":
            price += D(v["pence"])
            mins += D(v["mins"])
    unsure_key = p.get("unsure_key")
    unsure = bool(unsure_key) and a.get(unsure_key) == "unsure"
    return Estimate(
        price_pence=max(int(p["min_pence"]), round_to_pound(price)),
        mins=max(int(p["min_mins"]), round_half_up(mins)),
        spread=_spread(p["unsure_spread"] if unsure else p["spread"]),
        confidence=p["unsure_confidence"] if unsure else p["confidence"],
        unit="one-off",
        note=p.get("note"),
    )


def hours_estimate_v1(a: Answers, p: Params) -> Estimate:
    choice = a.get(p["key"])
    hours = _get(p["hours"], choice, p["hours_default"])
    unsure = choice == "unsure"
    return Estimate(
        price_pence=max(int(p["min_pence"]), round_to_pound(hours * D(p["rate_pence"]))),
        mins=round_half_up(hours * 60),
        spread=_spread(p["unsure_spread"] if unsure else p["spread"]),
        confidence="low" if unsure else (p.get("confidence") or "medium"),
        unit="one-off",
    )


def per_visit_v1(a: Answers, p: Params) -> Estimate:
    length = a.get("length")
    dogs = a.get("dogs")
    price = _get(p["base_pence"], length, 0) + (D(1 if dogs is None else dogs) - 1) * D(p["extra_dog_pence"])
    return Estimate(
        price_pence=round_to_pound(price),
        mins=int(_get(p["mins"], length, p["mins_default"])),
        spread=_spread(p["spread"]),
        confidence=p["confidence"],
        unit="one-off" if a.get("frequency") == "oneoff" else "a walk",
    )


PRICING_MODELS: dict[str, Callable[[Answers, Params], Estimate]] = {
    "lawn_area_v1": lawn_area_v1,
    "hedge_length_v1": hedge_length_v1,
    "photo_review_v1": photo_review_v1,
    "area_rate_v1": area_rate_v1,
    "size_base_v1": size_base_v1,
    "window_round_v1": window_round_v1,
    "rooms_hours_v1": rooms_hours_v1,
    "decorating_v1": decorating_v1,
    "counts_v1": counts_v1,
    "hours_estimate_v1": hours_estimate_v1,
    "per_visit_v1": per_visit_v1,
}
