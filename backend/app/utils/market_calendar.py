from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from app.utils.price_reference import PriceReferenceUnprovable


# LME official holidays (UK bank holidays + LME-specific).
# Source: lme.com/Trading/Holiday-calendar. Calendar is year-keyed so coverage
# gaps fail closed instead of silently degrading to weekends-only logic.
_LME_HOLIDAYS_BY_YEAR: dict[int, frozenset[date]] = {
    2024: frozenset(
        {
            date(2024, 1, 1),
            date(2024, 3, 29),
            date(2024, 4, 1),
            date(2024, 5, 6),
            date(2024, 5, 27),
            date(2024, 8, 26),
            date(2024, 12, 25),
            date(2024, 12, 26),
        }
    ),
    2025: frozenset(
        {
            date(2025, 1, 1),
            date(2025, 4, 18),
            date(2025, 4, 21),
            date(2025, 5, 5),
            date(2025, 5, 26),
            date(2025, 8, 25),
            date(2025, 12, 25),
            date(2025, 12, 26),
        }
    ),
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
    2027: frozenset(
        {
            date(2027, 1, 1),
            date(2027, 3, 26),
            date(2027, 3, 29),
            date(2027, 5, 3),
            date(2027, 5, 31),
            date(2027, 8, 30),
            date(2027, 12, 27),
            date(2027, 12, 28),
        }
    ),
    2028: frozenset(
        {
            date(2028, 1, 3),
            date(2028, 4, 14),
            date(2028, 4, 17),
            date(2028, 5, 1),
            date(2028, 5, 29),
            date(2028, 8, 28),
            date(2028, 12, 25),
            date(2028, 12, 26),
        }
    ),
    2029: frozenset(
        {
            date(2029, 1, 1),
            date(2029, 3, 30),
            date(2029, 4, 2),
            date(2029, 5, 7),
            date(2029, 5, 28),
            date(2029, 8, 27),
            date(2029, 12, 25),
            date(2029, 12, 26),
        }
    ),
    2030: frozenset(
        {
            date(2030, 1, 1),
            date(2030, 4, 19),
            date(2030, 4, 22),
            date(2030, 5, 6),
            date(2030, 5, 27),
            date(2030, 8, 26),
            date(2030, 12, 25),
            date(2030, 12, 26),
        }
    ),
    2031: frozenset(
        {
            date(2031, 1, 1),
            date(2031, 4, 11),
            date(2031, 4, 14),
            date(2031, 5, 5),
            date(2031, 5, 26),
            date(2031, 8, 25),
            date(2031, 12, 25),
            date(2031, 12, 26),
        }
    ),
    2032: frozenset(
        {
            date(2032, 1, 1),
            date(2032, 3, 26),
            date(2032, 3, 29),
            date(2032, 5, 3),
            date(2032, 5, 31),
            date(2032, 8, 30),
            date(2032, 12, 27),
            date(2032, 12, 28),
        }
    ),
    2033: frozenset(
        {
            date(2033, 1, 3),
            date(2033, 4, 15),
            date(2033, 4, 18),
            date(2033, 5, 2),
            date(2033, 5, 30),
            date(2033, 8, 29),
            date(2033, 12, 26),
            date(2033, 12, 27),
        }
    ),
    2034: frozenset(
        {
            date(2034, 1, 2),
            date(2034, 4, 7),
            date(2034, 4, 10),
            date(2034, 5, 1),
            date(2034, 5, 29),
            date(2034, 8, 28),
            date(2034, 12, 25),
            date(2034, 12, 26),
        }
    ),
    2035: frozenset(
        {
            date(2035, 1, 1),
            date(2035, 3, 23),
            date(2035, 3, 26),
            date(2035, 5, 7),
            date(2035, 5, 28),
            date(2035, 8, 27),
            date(2035, 12, 25),
            date(2035, 12, 26),
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
