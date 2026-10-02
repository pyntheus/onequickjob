"""The one place fees are worked out. Money is integer pence everywhere.

Standard fee (customers we found): round half-up of price x FEE_STANDARD_RATE (15%).
Own-customer fee (customers a provider brings): max(FEE_OWN_MIN_PENCE, round half-up of
price x FEE_OWN_RATE), i.e. 5% with a 100p minimum, only when that provider or their
registered helper does the visit; a cover provider pays the standard fee. Tips carry no fee.
The provider always receives price minus fee.

Rates come from config so they can change without code changes; the rounding rule
does not. Nothing else in the codebase may compute a fee.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.core.config import Settings, get_settings
from app.core.rounding import round_half_up

type FeeMode = Literal["standard", "own_customer", "tip"]
type BookingSource = Literal["platform", "own_customer"]
type PerformerKind = Literal["provider", "helper", "cover"]


@dataclass(frozen=True, slots=True)
class Split:
    price_pence: int
    fee_pence: int
    provider_pence: int
    mode: FeeMode
    rate: Decimal

    @property
    def rate_percent(self) -> int:
        return int(self.rate * 100)


def _check(price_pence: int) -> None:
    if not isinstance(price_pence, int) or isinstance(price_pence, bool):
        raise TypeError("money must be integer pence")
    if price_pence < 0:
        raise ValueError("price cannot be negative")


def standard_fee(price_pence: int, settings: Settings | None = None) -> int:
    _check(price_pence)
    s = settings or get_settings()
    return round_half_up(Decimal(price_pence) * s.fee_standard_rate)


def own_customer_fee(price_pence: int, settings: Settings | None = None) -> int:
    _check(price_pence)
    s = settings or get_settings()
    return max(s.fee_own_min_pence, round_half_up(Decimal(price_pence) * s.fee_own_rate))


def split(price_pence: int, mode: FeeMode = "standard", settings: Settings | None = None) -> Split:
    """Fee and provider share for a price. mode follows the booking source."""
    s = settings or get_settings()
    if mode == "standard":
        fee, rate = standard_fee(price_pence, s), s.fee_standard_rate
    elif mode == "own_customer":
        fee, rate = own_customer_fee(price_pence, s), s.fee_own_rate
    elif mode == "tip":
        _check(price_pence)
        fee, rate = 0, Decimal(0)
    else:  # pragma: no cover - guarded by the type
        raise ValueError(f"unknown fee mode {mode!r}")
    # A fee floor can exceed a tiny price; the provider never receives a negative amount.
    fee = min(fee, price_pence)
    return Split(price_pence=price_pence, fee_pence=fee, provider_pence=price_pence - fee, mode=mode, rate=rate)


def mode_for_source(source: BookingSource) -> FeeMode:
    return "own_customer" if source == "own_customer" else "standard"


def split_for_source(price_pence: int, source: BookingSource, settings: Settings | None = None) -> Split:
    return split(price_pence, mode_for_source(source), settings)


def mode_for_visit(source: BookingSource, performer: PerformerKind) -> FeeMode:
    """The fee for one visit. The own-customer rate applies only when the visit is done by the
    provider who brought the customer, or by that provider's registered helper. A cover
    provider didn't bring the customer, so a covered visit pays the standard rate."""
    if source == "own_customer" and performer in ("provider", "helper"):
        return "own_customer"
    return "standard"


def split_for_visit(
    price_pence: int, source: BookingSource, performer: PerformerKind, settings: Settings | None = None
) -> Split:
    """Use this to charge a visit (L2) and to show its split: fee mode from mode_for_visit."""
    return split(price_pence, mode_for_visit(source, performer), settings)


def refund_split(original: Split, refund_pence: int) -> Split:
    """How a refund of part (or all) of a charge divides between our fee and the provider.

    The fee refunded is proportional: round half-up of refund x original fee / original
    price, so a full refund returns exactly the fee and the provider's share. Refunds are
    provider-funded: the provider's share of the refund comes back out of their earnings.
    """
    _check(refund_pence)
    if refund_pence > original.price_pence:
        raise ValueError("cannot refund more than was charged")
    if original.price_pence == 0:
        return Split(0, 0, 0, original.mode, original.rate)
    fee = round_half_up(Decimal(refund_pence) * original.fee_pence / original.price_pence)
    return Split(refund_pence, fee, refund_pence - fee, original.mode, original.rate)


def format_pounds(pence: int) -> str:
    """£30, £25.50, £1,742 - as the prototype's fmt(), for outbox message bodies."""
    _check(abs(pence))
    sign = "-" if pence < 0 else ""
    pounds, p = divmod(abs(pence), 100)
    whole = f"{pounds:,}"
    return f"{sign}£{whole}" if p == 0 else f"{sign}£{whole}.{p:02d}"
