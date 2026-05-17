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
from app.services.audit_trail_service import AuditTrailService
from app.services.cash_settlement_prices import (
    ingest_westmetall_cash_settlement_bulk,
)
from app.services.market_data_governance import (
    MarketDataAuditMetadata,
    is_canonical as is_canonical_provider,
    tier_for_provider,
)
from app.services.westmetall_cash_settlement import (
    CircuitOpenError,
    SOURCE_WESTMETALL,
    SYMBOL_DAILY,
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
        inserted_ids, batch_uuid, ingested, skipped, evidence = (
            ingest_westmetall_cash_settlement_bulk(session)
        )
        metadata = MarketDataAuditMetadata(
            provider=SOURCE_WESTMETALL,
            instrument=SYMBOL_DAILY,
            actor_sub="service:westmetall_ingest",
            tier_at_ingest_time=tier_for_provider(SOURCE_WESTMETALL),
            is_canonical=is_canonical_provider(SOURCE_WESTMETALL, SYMBOL_DAILY),
            batch_replay_id=str(batch_uuid),
        ).as_metadata_dict()
        metadata["inserted_ids"] = [str(inserted_id) for inserted_id in inserted_ids]
        metadata["source_url"] = evidence.source_url
        metadata["html_sha256"] = evidence.html_sha256
        metadata["batch_uuid"] = str(batch_uuid)
        AuditTrailService.record_worker_event(
            session,
            entity_type="cash_settlement_price",
            entity_id=batch_uuid,
            event_type="market_data_ingested",
            actor="service:westmetall_ingest",
            source="westmetall_task",
            metadata=metadata,
        )
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
