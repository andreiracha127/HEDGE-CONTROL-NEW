from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.market_data import CashSettlementPrice


# ── Domain exception ──────────────────────────────────────────────────
# Raised when a market reference price cannot be proven for the
# requested (symbol, as_of_date) — e.g. no row within the lookback
# window. PR-8 (J-A1-01) hard-fail surface: callers in deal_engine.py
# (compute_deal_pnl, _order_value, _get_market_price) MUST propagate
# this to the route layer instead of returning None / Decimal("0") /
# falling back to avg_entry_price.
class PriceReferenceUnprovable(Exception):
    """No cash-settlement reference price within the lookback window.

    This is a domain hard-fail (per governance §2.6 — "price reference
    cannot be proven → hard-fail"). The route layer catches this and
    returns 422; service callers must NOT silence it.
    """

    def __init__(
        self,
        message: str,
        *,
        commodity: str | None = None,
        symbol: str | None = None,
        as_of_date: date | None = None,
    ) -> None:
        super().__init__(message)
        self.commodity = commodity
        self.symbol = symbol
        self.as_of_date = as_of_date


# ── Structured price-lookup result ────────────────────────────────────
@dataclass(frozen=True)
class PriceQuote:
    """Structured result of a cash-settlement price lookup.

    Carries the actual settlement_date used (which may differ from
    as_of_date - 1 due to weekend / holiday lookback up to 5 days),
    the source string from CashSettlementPrice.source, the resolved
    symbol, and the value as Decimal. Used by P&L provenance
    persistence (DealPNLSnapshot.price_references).
    """

    value: Decimal
    source: str
    settlement_date: date
    symbol: str

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
    """Return the most recent cash-settlement price as a PriceQuote.

    Falls back up to 5 calendar days to handle weekends / holidays.

    The returned PriceQuote.settlement_date is the ACTUAL row's
    settlement_date (may be earlier than ``as_of_date - 1`` when the
    nominal D-1 was a weekend/holiday). PriceQuote.source is the row's
    ``source`` column verbatim (e.g. ``"westmetall"``); upstream
    persistence in DealPNLSnapshot.price_references uses this string
    as the canonical evidence of the lookup origin.

    Raises
    ------
    PriceReferenceUnprovable
        When no row exists within the 5-day lookback window. This is
        the domain hard-fail signal — callers MUST propagate it.
    """
    price_date = as_of_date - timedelta(days=1)
    lookback_limit = price_date - timedelta(days=5)

    row = (
        db.query(CashSettlementPrice)
        .filter(
            CashSettlementPrice.symbol == symbol,
            CashSettlementPrice.settlement_date <= price_date,
            CashSettlementPrice.settlement_date >= lookback_limit,
        )
        .order_by(CashSettlementPrice.settlement_date.desc())
        .first()
    )

    if not row:
        raise PriceReferenceUnprovable(
            f"No cash settlement price for {symbol} on or before {price_date}",
            symbol=symbol,
            as_of_date=as_of_date,
        )

    return PriceQuote(
        value=Decimal(str(row.price_usd)),
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
