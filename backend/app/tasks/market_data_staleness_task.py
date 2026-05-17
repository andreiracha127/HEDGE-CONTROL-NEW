"""Background staleness check for market-data feeds."""

from __future__ import annotations

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.market_data import CashSettlementPrice
from app.services.market_data_governance import emit_stale_feed_if_breach
from app.services.westmetall_cash_settlement import SOURCE_WESTMETALL, SYMBOL_DAILY

logger = get_logger()

_MONITORED_PAIRS: list[tuple[str, str]] = [
    (SOURCE_WESTMETALL, SYMBOL_DAILY),
]


def run_market_data_staleness_check() -> None:
    logger.info("market_data_staleness_check_start")
    session = SessionLocal()
    try:
        for provider, instrument in _MONITORED_PAIRS:
            try:
                last_row = (
                    session.query(CashSettlementPrice)
                    .filter(
                        CashSettlementPrice.source == provider,
                        CashSettlementPrice.symbol == instrument,
                    )
                    .order_by(CashSettlementPrice.fetched_at.desc())
                    .first()
                )
                emit_stale_feed_if_breach(
                    provider=provider,
                    instrument=instrument,
                    last_ingest_at=last_row.fetched_at if last_row else None,
                )
            except Exception as exc:  # pragma: no cover
                logger.error(
                    "market_data_staleness_check_pair_error",
                    provider=provider,
                    instrument=instrument,
                    error=str(exc),
                    exc_info=True,
                )
        logger.info("market_data_staleness_check_end")
    finally:
        session.close()
