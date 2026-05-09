from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.market_data import CashSettlementPrice
from app.utils.market_calendar import (
    _canonical_source_for_symbol,
    _market_calendar_for_symbol,
    _prior_business_day,
)
from app.utils.price_reference import PriceQuote, PriceReferenceUnprovable

# ── Commodity → Price-symbol mapping ───────────────────────────────────
# Each tradeable commodity is mapped to the symbol that its cash-settlement
# price is published under.  Adding a new commodity is a one-liner here.

COMMODITY_SYMBOL_MAP: dict[str, str] = {
    # canonical short codes
    "LME_AL": "LME_ALU_CASH_SETTLEMENT_DAILY",
    "LME_CU": "LME_CU_CASH_SETTLEMENT_DAILY",
    "LME_ZN": "LME_ZN_CASH_SETTLEMENT_DAILY",
    "LME_NI": "LME_NI_CASH_SETTLEMENT_DAILY",
    "LME_PB": "LME_PB_CASH_SETTLEMENT_DAILY",
    "LME_SN": "LME_SN_CASH_SETTLEMENT_DAILY",
    # common / human-readable aliases
    "ALUMINUM": "LME_ALU_CASH_SETTLEMENT_DAILY",
    "ALUMINIUM": "LME_ALU_CASH_SETTLEMENT_DAILY",
    "COPPER": "LME_CU_CASH_SETTLEMENT_DAILY",
    "ZINC": "LME_ZN_CASH_SETTLEMENT_DAILY",
    "NICKEL": "LME_NI_CASH_SETTLEMENT_DAILY",
    "LEAD": "LME_PB_CASH_SETTLEMENT_DAILY",
    "TIN": "LME_SN_CASH_SETTLEMENT_DAILY",
}


CANONICAL_COMMODITY_MAP: dict[str, str] = {
    "LME_AL": "ALUMINUM",
    "ALUMINUM": "ALUMINUM",
    "ALUMINIUM": "ALUMINUM",
    "LME_CU": "COPPER",
    "COPPER": "COPPER",
    "LME_ZN": "ZINC",
    "ZINC": "ZINC",
    "LME_NI": "NICKEL",
    "NICKEL": "NICKEL",
    "LME_PB": "LEAD",
    "LEAD": "LEAD",
    "LME_SN": "TIN",
    "TIN": "TIN",
}


def canonical_commodity(commodity: str | None) -> str | None:
    """Return the exposure grouping key for a commodity string."""
    if commodity is None:
        return None
    key = commodity.strip().upper()
    return CANONICAL_COMMODITY_MAP.get(key, key)


def commodity_aliases(commodity: str) -> set[str]:
    """Return known raw aliases that map to the same canonical commodity."""
    canonical = canonical_commodity(commodity)
    aliases = {
        alias
        for alias, alias_canonical in CANONICAL_COMMODITY_MAP.items()
        if alias_canonical == canonical
    }
    aliases.add(commodity)
    if canonical is not None:
        aliases.add(canonical)
    return aliases


def resolve_symbol(commodity: str) -> str:
    """Return the settlement-price symbol for *commodity*.

    Performs a case-insensitive lookup: 'aluminium', 'Aluminium' and
    'ALUMINIUM' all resolve to the same symbol.

    Raises 400 when there is no mapping.
    """
    sym = COMMODITY_SYMBOL_MAP.get(commodity.upper())
    if sym is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No price-symbol mapping for commodity '{commodity}'",
        )
    return sym


def get_cash_settlement_price_d1_with_provenance(
    db: Session, symbol: str, as_of_date: date
) -> PriceQuote:
    """Return the exact prior-business-day cash-settlement price."""
    canonical_source = _canonical_source_for_symbol(symbol)
    prior_bd = _prior_business_day(
        as_of_date, lambda year: _market_calendar_for_symbol(symbol, year)
    )

    row = (
        db.query(CashSettlementPrice)
        .filter(
            CashSettlementPrice.source == canonical_source,
            CashSettlementPrice.symbol == symbol,
            CashSettlementPrice.settlement_date == prior_bd,
        )
        .first()
    )

    if not row:
        raise PriceReferenceUnprovable(
            f"No {canonical_source} {symbol} cash settlement for prior business day {prior_bd} "
            f"(as_of={as_of_date}); older settlements and other sources are NOT considered.",
            symbol=symbol,
            as_of_date=as_of_date,
        )

    value = row.price_usd if isinstance(row.price_usd, Decimal) else Decimal(str(row.price_usd))
    return PriceQuote(
        value=value,
        source=row.source,
        settlement_date=row.settlement_date,
        symbol=symbol,
    )


def get_cash_settlement_price_d1(db: Session, symbol: str, as_of_date: date) -> Decimal:
    """Return the most recent cash-settlement price as a Decimal.

    Thin wrapper around :func:`get_cash_settlement_price_d1_with_provenance`
    preserved for backward compatibility with non-P&L callers
    (e.g., MTM services, scenario_whatif). New code requiring the
    full provenance triplet (value/source/settlement_date) MUST use
    :func:`get_cash_settlement_price_d1_with_provenance` directly.

    Raises
    ------
    HTTPException(424)
        When no row exists within the 5-day lookback window. The
        wrapper preserves the legacy 424 contract for existing
        callers; the underlying lookup raises
        :class:`PriceReferenceUnprovable` which is translated here.
    """
    try:
        return get_cash_settlement_price_d1_with_provenance(
            db, symbol=symbol, as_of_date=as_of_date
        ).value
    except PriceReferenceUnprovable as exc:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail=str(exc),
        ) from exc
