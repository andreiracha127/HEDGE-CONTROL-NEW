from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from app.utils.price_reference import PriceReferenceUnprovable


# LME official holidays (UK bank holidays + LME-specific).
# Source: lme.com/Trading/Holiday-calendar. Calendar is year-keyed so coverage
# gaps fail closed instead of silently degrading to weekends-only logic.
_LME_HOLIDAYS_BY_YEAR: dict[int, frozenset[date]] = {
    2026: frozenset(
        {
            date(2026, 1, 1),
            date(2026, 4, 3),
            date(2026, 4, 6),
            date(2026, 5, 4),
            date(2026, 5, 25),
            date(2026, 8, 31),
            date(2026, 12, 25),
            date(2026, 12, 28),
        }
    ),
}


_CANONICAL_SOURCE_BY_SYMBOL: dict[str, str] = {
    "LME_ALU_CASH_SETTLEMENT_DAILY": "westmetall",
    "LME_CU_CASH_SETTLEMENT_DAILY": "westmetall",
    "LME_ZN_CASH_SETTLEMENT_DAILY": "westmetall",
    "LME_NI_CASH_SETTLEMENT_DAILY": "westmetall",
    "LME_PB_CASH_SETTLEMENT_DAILY": "westmetall",
    "LME_SN_CASH_SETTLEMENT_DAILY": "westmetall",
}


def _market_calendar_for_symbol(symbol: str, year: int) -> frozenset[date]:
    if not symbol.startswith("LME_"):
        raise PriceReferenceUnprovable(
            f"No market calendar registered for symbol {symbol!r}; operator must extend "
            "_market_calendar_for_symbol before MTM/P&L can be computed for this commodity.",
            symbol=symbol,
        )
    holidays = _LME_HOLIDAYS_BY_YEAR.get(year)
    if holidays is None:
        covered = sorted(_LME_HOLIDAYS_BY_YEAR)
        raise PriceReferenceUnprovable(
            f"LME holiday calendar coverage does not include year {year}; covered years: "
            f"{covered}. Operator must extend `_LME_HOLIDAYS_BY_YEAR` before lookups for this period.",
            symbol=symbol,
            as_of_date=date(year, 1, 1),
        )
    return holidays


def _prior_business_day(
    price_date: date, calendar_for_year: Callable[[int], frozenset[date]]
) -> date:
    cursor = price_date - timedelta(days=1)
    while cursor.weekday() >= 5 or cursor in calendar_for_year(cursor.year):
        cursor -= timedelta(days=1)
    return cursor


def _canonical_source_for_symbol(symbol: str) -> str:
    try:
        return _CANONICAL_SOURCE_BY_SYMBOL[symbol]
    except KeyError as exc:
        raise PriceReferenceUnprovable(
            f"No canonical source registered for resolved symbol {symbol!r}; operator must extend "
            "_CANONICAL_SOURCE_BY_SYMBOL keyed by the long-form settlement symbol before MTM/P&L can be computed.",
            symbol=symbol,
        ) from exc
