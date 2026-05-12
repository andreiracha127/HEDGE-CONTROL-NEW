"""Scheduled background task for daily Westmetall cash-settlement scraping.

Runs every day at 18:00 UTC (after LME close).  Uses bulk ingestion so that
any missed days are automatically backfilled from the Westmetall page (which
contains several years of history).

The scheduler is isolated: a failure inside the task never propagates to the
FastAPI request/response cycle.
"""

from __future__ import annotations

from datetime import date

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.services.cash_settlement_prices import (
    ingest_westmetall_cash_settlement_bulk,
)
from app.services.westmetall_cash_settlement import (
    CircuitOpenError,
    WestmetallLayoutError,
)

logger = get_logger()


def run_westmetall_ingestion() -> None:
    """Execute one Westmetall ingestion cycle.

    Uses bulk ingestion so all available prices are persisted in a single pass.
    Already-existing dates are skipped (idempotent).

    Creates its own DB session so it is fully independent of the request cycle.
    All exceptions are caught and logged — the scheduler must never crash.
    """
    logger.info("westmetall_task_start")
    session = SessionLocal()
    try:
        _, _, ingested, skipped, evidence = ingest_westmetall_cash_settlement_bulk(
            session
        )
        if ingested:
            session.commit()
        logger.info(
            "westmetall_task_success",
            ingested_count=ingested,
            skipped_count=skipped,
            source_url=evidence.source_url,
        )
    except WestmetallLayoutError as exc:
        logger.error(
            "westmetall_task_layout_error",
            error=str(exc),
        )
    except CircuitOpenError as exc:
        logger.warning(
            "westmetall_task_circuit_open",
            error=str(exc),
        )
    except Exception as exc:  # pragma: no cover — safety net
        logger.error(
            "westmetall_task_unexpected_error",
            error=str(exc),
            exc_info=True,
        )
    finally:
        session.close()
