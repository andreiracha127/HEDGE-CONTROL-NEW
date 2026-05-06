from decimal import Decimal

from app.core.precision import quantize_mt, quantize_price


def test_quantize_mt_makes_decimal_addition_exact() -> None:
    total = quantize_mt(Decimal("0.1")) + quantize_mt(Decimal("0.2"))

    assert quantize_mt(total) == Decimal("0.300")


def test_quantize_price_uses_six_decimal_places() -> None:
    assert quantize_price(Decimal("2500.1234564")) == Decimal("2500.123456")
    assert quantize_price(Decimal("2500.1234565")) == Decimal("2500.123456")
