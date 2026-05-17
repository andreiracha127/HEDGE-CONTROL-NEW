from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.westmetall_cash_settlement import (
    _parse_price_decimal,
    parse_westmetall_daily_rows,
)


def test_parse_price_decimal_rejects_float_input() -> None:
    with pytest.raises(TypeError):
        _parse_price_decimal(2567.5)  # type: ignore[arg-type]


def test_parse_price_decimal_rejects_int_input() -> None:
    with pytest.raises(TypeError):
        _parse_price_decimal(2567)  # type: ignore[arg-type]


def test_parse_price_decimal_accepts_basic_decimal_string() -> None:
    assert _parse_price_decimal("2567.50") == Decimal("2567.50")


def test_parse_price_decimal_strips_thousands_separator() -> None:
    assert _parse_price_decimal("2,567.50") == Decimal("2567.50")


def test_parse_price_decimal_accepts_eu_when_both_separators_present() -> None:
    assert _parse_price_decimal("2.567,50") == Decimal("2567.50")


def test_parse_price_decimal_strips_nbsp() -> None:
    assert _parse_price_decimal("2567.50\xa0") == Decimal("2567.50")


def test_parse_price_decimal_strips_surrounding_whitespace() -> None:
    assert _parse_price_decimal("  2567.50  ") == Decimal("2567.50")


def test_parse_price_decimal_returns_none_on_empty() -> None:
    assert _parse_price_decimal("") is None
    assert _parse_price_decimal("   ") is None


def test_parse_price_decimal_returns_none_on_garbage() -> None:
    assert _parse_price_decimal("not a number") is None


def test_parse_price_decimal_preserves_precision() -> None:
    assert _parse_price_decimal("2567.500001") == Decimal("2567.500001")


def test_parse_westmetall_daily_rows_returns_decimal_price() -> None:
    rows = parse_westmetall_daily_rows(
        b"""
        <table>
          <tr><td>30.01.2026</td><td>2,567.50</td></tr>
          <tr><td>29.01.2026</td><td>2568.500001</td></tr>
        </table>
        """
    )
    assert rows
    assert all(isinstance(row.price_usd, Decimal) for row in rows)


def test_parse_westmetall_daily_rows_no_float_anywhere() -> None:
    binary64 = float
    rows = parse_westmetall_daily_rows(
        b"""
        <table>
          <tr><td>30.01.2026</td><td>2,567.50</td></tr>
        </table>
        """
    )
    assert all(not isinstance(row.price_usd, binary64) for row in rows)
