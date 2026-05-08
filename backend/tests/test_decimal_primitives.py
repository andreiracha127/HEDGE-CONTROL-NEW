from decimal import Decimal

from app.core.precision import quantize_mt, quantize_price


def test_quantize_mt_makes_decimal_addition_exact() -> None:
    total = quantize_mt(Decimal("0.1")) + quantize_mt(Decimal("0.2"))

    assert quantize_mt(total) == Decimal("0.300")


def test_quantize_price_uses_six_decimal_places() -> None:
    assert quantize_price(Decimal("2500.1234564")) == Decimal("2500.123456")
    assert quantize_price(Decimal("2500.1234565")) == Decimal("2500.123456")


# ─────────────────────────────────────────────────────────────────────────
# Phase A2 PR-1 — RFQ-side round-trips through quantize_*
# ─────────────────────────────────────────────────────────────────────────


def test_quantize_mt_handles_rfq_quantity_string_input() -> None:
    # RFQCreate accepts "1.234" string from JSON; quantize_mt round-trips it.
    assert quantize_mt("1.234") == Decimal("1.234")
    assert quantize_mt(Decimal("1.234")) == Decimal("1.234")


def test_quantize_price_handles_rfq_quote_string_input() -> None:
    assert quantize_price("100.000001") == Decimal("100.000001")
    assert quantize_price(Decimal("100.000001")) == Decimal("100.000001")


def test_decimal_subtraction_is_exact_for_rfq_spread_arithmetic() -> None:
    # Pre-PR-1: float(sell) - float(buy) drifted at the 6th decimal.
    sell = Decimal("100.000003")
    buy = Decimal("99.999998")
    assert sell - buy == Decimal("0.000005")
