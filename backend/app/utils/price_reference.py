from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class PriceReferenceUnprovable(Exception):
    """Raised when a required market reference price cannot be proven."""

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


@dataclass(frozen=True)
class PriceQuote:
    """Structured result of a cash-settlement price lookup."""

    value: Decimal
    source: str
    settlement_date: date
    symbol: str
