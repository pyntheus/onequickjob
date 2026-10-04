"""Fees (decisions.md): standard = round half-up of price x 15%; own customer =
max(100p, round half-up of price x 5%); tips carry no fee; provider gets price - fee."""

from decimal import Decimal

import pytest

from app.core import money
from app.core.config import Settings
from app.core.rounding import round_half_up, round_half_up_to, round_to_pound


def test_fee_golden_values():
    assert money.standard_fee(3000) == 450
    assert money.own_customer_fee(1500) == 100
    assert money.own_customer_fee(3000) == 150


def test_split_standard():
    s = money.split(3000)
    assert (s.price_pence, s.fee_pence, s.provider_pence, s.rate_percent) == (3000, 450, 2550, 15)


def test_split_own_customer_minimum():
    s = money.split(1500, "own_customer")
    assert (s.fee_pence, s.provider_pence, s.rate_percent) == (100, 1400, 5)
    assert money.split(2500, "own_customer").fee_pence == 125  # Mary: £25, fee £1.25


def test_tip_has_no_fee():
    s = money.split(500, "tip")
    assert (s.fee_pence, s.provider_pence) == (0, 500)


def test_fee_rounds_half_up_not_to_even():
    # 10p x 15% = 1.5p -> 2p (Python's round() would give 2 here but 0.5 -> 0, 2.5 -> 2)
    assert money.standard_fee(10) == 2
    assert money.standard_fee(30) == 5  # 4.5 -> 5 (banker's rounding would give 4)
    assert money.own_customer_fee(2030) == 102  # 101.5 -> 102
    assert money.own_customer_fee(2050) == 103  # 102.5 -> 103 (banker's: 102)


@pytest.mark.parametrize("price", [0, 1, 99, 100, 101, 1999, 3000, 3333, 123457])
@pytest.mark.parametrize("mode", ["standard", "own_customer", "tip"])
def test_fee_plus_provider_is_always_the_price(price, mode):
    s = money.split(price, mode)
    assert s.fee_pence + s.provider_pence == price
    assert s.fee_pence >= 0 and s.provider_pence >= 0


def test_source_picks_the_fee():
    assert money.split_for_source(3000, "platform").fee_pence == 450
    assert money.split_for_source(3000, "own_customer").fee_pence == 150


def test_rates_come_from_config():
    s = Settings(fee_standard_rate=Decimal("0.20"), fee_own_rate=Decimal("0.10"), fee_own_min_pence=50)
    assert money.standard_fee(3000, s) == 600
    assert money.own_customer_fee(300, s) == 50


def test_money_must_be_integer_pence():
    with pytest.raises(TypeError):
        money.split(30.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        money.split(Decimal("30"))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        money.split(-1)


def test_refund_split_is_proportional_and_exact_in_full():
    original = money.split(3000)
    full = money.refund_split(original, 3000)
    assert (full.fee_pence, full.provider_pence) == (450, 2550)
    half = money.refund_split(original, 1500)
    assert (half.fee_pence, half.provider_pence) == (225, 1275)
    odd = money.refund_split(money.split(1500, "own_customer"), 750)
    assert (odd.fee_pence, odd.provider_pence) == (50, 700)
    with pytest.raises(ValueError):
        money.refund_split(original, 3001)


def test_format_pounds():
    assert money.format_pounds(3000) == "£30"
    assert money.format_pounds(2550) == "£25.50"
    assert money.format_pounds(174200) == "£1,742"
    assert money.format_pounds(5) == "£0.05"
    assert money.format_pounds(-450) == "-£4.50"


def test_round_half_up_matches_javascript_math_round():
    assert round_half_up(Decimal("2.5")) == 3 and round(2.5) == 2
    assert round_half_up(Decimal("0.5")) == 1
    assert round_half_up(Decimal("38.46")) == 38
    assert round_half_up(0.1 + 0.2) == 0
    assert round_half_up_to(Decimal("8.4"), "0.5") == Decimal("8.5")
    assert round_half_up_to(Decimal("8.25"), "0.5") == Decimal("8.5")
    assert round_to_pound(8750) == 8800  # £87.50 -> £88 (jet wash default)
    assert round_to_pound(6050) == 6100  # £60.50 -> £61 (hedge default)


def test_own_customer_rate_only_for_the_provider_who_brought_them_or_their_helper():
    """Ruling after F review (d): a cover provider pays the standard 15%."""
    assert money.mode_for_visit("own_customer", "provider") == "own_customer"
    assert money.mode_for_visit("own_customer", "helper") == "own_customer"
    assert money.mode_for_visit("own_customer", "cover") == "standard"
    for performer in ("provider", "helper", "cover"):
        assert money.mode_for_visit("platform", performer) == "standard"


def test_covered_own_customer_visit_is_charged_the_standard_fee():
    own = money.split_for_visit(2800, "own_customer", "provider")
    helper = money.split_for_visit(2800, "own_customer", "helper")
    cover = money.split_for_visit(2800, "own_customer", "cover")
    assert (own.fee_pence, own.provider_pence) == (140, 2660)  # Pat Green: 5% of £28
    assert helper.fee_pence == 140
    assert (cover.fee_pence, cover.provider_pence, cover.mode) == (420, 2380, "standard")
    assert money.split_for_visit(1500, "own_customer", "provider").fee_pence == 100  # the 100p minimum
    assert money.split_for_visit(1500, "own_customer", "cover").fee_pence == 225


def test_partial_refunds_add_up_to_the_refund_of_their_total():
    """refund_split_after (contract-changes L3): each further refund is the difference of the
    cumulative splits, so the fees refunded always total refund_split of the whole."""
    original = money.split(3333, "standard")  # fee 500
    parts = [1000, 1111, 1, 1221]
    done, fees = 0, 0
    for amount in parts:
        part = money.refund_split_after(original, done, amount)
        assert part.price_pence == amount and part.fee_pence + part.provider_pence == amount
        done, fees = done + amount, fees + part.fee_pence
    assert done == 3333 and fees == money.refund_split(original, 3333).fee_pence == original.fee_pence
