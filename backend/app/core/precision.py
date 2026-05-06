from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

MT_NUMERIC_PRECISION = 15
MT_NUMERIC_SCALE = 3
PRICE_NUMERIC_PRECISION = 18
PRICE_NUMERIC_SCALE = 6

MT_QUANT = Decimal("0.001")
PRICE_QUANT = Decimal("0.000001")
MONEY_QUANT = Decimal("0.000001")
RATIO_QUANT = Decimal("0.01")
DECIMAL_ZERO = Decimal("0")


def to_decimal(value: Any, default: Decimal = DECIMAL_ZERO) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_mt(value: Any) -> Decimal:
    return to_decimal(value).quantize(MT_QUANT, rounding=ROUND_HALF_EVEN)


def quantize_price(value: Any) -> Decimal:
    return to_decimal(value).quantize(PRICE_QUANT, rounding=ROUND_HALF_EVEN)


def quantize_money(value: Any) -> Decimal:
    return to_decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)


def quantize_ratio(value: Any) -> Decimal:
    return to_decimal(value).quantize(RATIO_QUANT, rounding=ROUND_HALF_EVEN)
