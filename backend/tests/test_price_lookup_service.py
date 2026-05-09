from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.market_data import CashSettlementPrice
from app.services.price_lookup_service import (
    PriceReferenceUnprovable,
    get_cash_settlement_price_d1,
    get_cash_settlement_price_d1_with_provenance,
    resolve_symbol,
)
from app.utils.market_calendar import (
    _CANONICAL_SOURCE_BY_SYMBOL,
    _LME_HOLIDAYS_BY_YEAR,
    _canonical_source_for_symbol,
    _market_calendar_for_symbol,
    _prior_business_day,
)


def _insert_price(symbol: str, settlement_date: date, price_usd: float, source: str = "westmetall") -> None:
    with SessionLocal() as session:
        session.add(
            CashSettlementPrice(
                source=source,
                symbol=symbol,
                settlement_date=settlement_date,
                price_usd=price_usd,
                source_url="https://example.test/source",
                html_sha256="0" * 64,
                fetched_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()


def test_d1_price_exists_returns_decimal() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=2567.50)

    with SessionLocal() as session:
        value = get_cash_settlement_price_d1(session, symbol=symbol, as_of_date=date(2026, 2, 1))
        assert value == Decimal("2567.5")


def test_d1_price_missing_raises_http_424() -> None:
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            get_cash_settlement_price_d1(
                session,
                symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                as_of_date=date(2026, 2, 1),
            )
        assert exc.value.status_code == 424


def test_as_of_date_2026_02_01_uses_business_d1_2026_01_30() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=111.0)

    with SessionLocal() as session:
        value = get_cash_settlement_price_d1(session, symbol=symbol, as_of_date=date(2026, 2, 1))
        assert value == Decimal("111.0")


def test_weekend_d1_is_skipped_even_if_price_exists() -> None:
    # as_of_date 2026-02-02 is Monday; business D-1 is 2026-01-30 (Friday)
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 2, 1), price_usd=222.0)
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=111.0)

    with SessionLocal() as session:
        value = get_cash_settlement_price_d1(session, symbol=symbol, as_of_date=date(2026, 2, 2))
        assert value == Decimal("111.000000")


def test_lookup_skips_weekend_correctly_to_friday() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=333.0)

    with SessionLocal() as session:
        quote = get_cash_settlement_price_d1_with_provenance(
            session, symbol=symbol, as_of_date=date(2026, 2, 2)
        )
        assert quote.settlement_date == date(2026, 1, 30)
        assert quote.value == Decimal("333.0")


def test_lookup_at_start_of_year_uses_prior_business_day_in_adjacent_covered_year() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2025, 12, 31), price_usd=444.0)

    with SessionLocal() as session:
        quote = get_cash_settlement_price_d1_with_provenance(
            session, symbol=symbol, as_of_date=date(2026, 1, 2)
        )
        assert quote.settlement_date == date(2025, 12, 31)
        assert quote.value == Decimal("444.0")


def test_lookup_after_2026_uses_prior_business_day_in_extended_lme_calendar() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 12, 31), price_usd=555.0)

    with SessionLocal() as session:
        quote = get_cash_settlement_price_d1_with_provenance(
            session, symbol=symbol, as_of_date=date(2027, 1, 4)
        )
        assert quote.settlement_date == date(2026, 12, 31)
        assert quote.value == Decimal("555.0")


def test_missing_prior_business_day_raises_even_when_older_business_day_exists() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=333.0)

    with SessionLocal() as session:
        with pytest.raises(PriceReferenceUnprovable):
            get_cash_settlement_price_d1_with_provenance(
                session, symbol=symbol, as_of_date=date(2026, 2, 3)
            )


def test_lookup_filters_by_canonical_source_excluding_other_sources() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=999.0, source="bloomberg")
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=333.0, source="westmetall")

    with SessionLocal() as session:
        quote = get_cash_settlement_price_d1_with_provenance(
            session, symbol=symbol, as_of_date=date(2026, 2, 2)
        )
        assert quote.source == "westmetall"
        assert quote.value == Decimal("333.0")


def test_canonical_source_for_symbol_returns_westmetall_for_resolved_lme_symbols() -> None:
    expected = {
        "LME_ALU_CASH_SETTLEMENT_DAILY",
        "LME_CU_CASH_SETTLEMENT_DAILY",
        "LME_ZN_CASH_SETTLEMENT_DAILY",
        "LME_NI_CASH_SETTLEMENT_DAILY",
        "LME_PB_CASH_SETTLEMENT_DAILY",
        "LME_SN_CASH_SETTLEMENT_DAILY",
    }
    assert set(_CANONICAL_SOURCE_BY_SYMBOL) == expected
    assert {_canonical_source_for_symbol(symbol) for symbol in expected} == {"westmetall"}


def test_canonical_source_lookup_chain_works_for_short_code_input() -> None:
    assert _canonical_source_for_symbol(resolve_symbol("LME_AL")) == "westmetall"


def test_canonical_source_for_symbol_raises_for_unknown_symbol() -> None:
    with pytest.raises(PriceReferenceUnprovable):
        _canonical_source_for_symbol("XYZ_FAKE")


def test_market_calendar_is_in_repo_year_keyed_not_holidays_dependency() -> None:
    assert isinstance(_LME_HOLIDAYS_BY_YEAR, dict)
    assert 2026 in _LME_HOLIDAYS_BY_YEAR
    assert set(range(2025, 2036)).issubset(_LME_HOLIDAYS_BY_YEAR)
    assert all(isinstance(holidays, frozenset) for holidays in _LME_HOLIDAYS_BY_YEAR.values())


def test_market_calendar_fails_closed_on_year_outside_coverage() -> None:
    with pytest.raises(PriceReferenceUnprovable) as exc:
        _market_calendar_for_symbol("LME_ALU_CASH_SETTLEMENT_DAILY", 2036)
    assert "covered years" in str(exc.value)


def test_prior_business_day_fails_closed_when_walk_crosses_into_uncovered_year() -> None:
    def calendar_for_year(year: int) -> frozenset[date]:
        if year != 2026:
            raise PriceReferenceUnprovable("uncovered", symbol="LME_ALU_CASH_SETTLEMENT_DAILY")
        return frozenset()

    with pytest.raises(PriceReferenceUnprovable):
        _prior_business_day(date(2036, 1, 2), calendar_for_year)
