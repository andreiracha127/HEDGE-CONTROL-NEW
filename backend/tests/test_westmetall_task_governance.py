from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.westmetall_cash_settlement import WestmetallFetchEvidence
from app.tasks.westmetall_task import run_westmetall_ingestion


def test_scheduler_ingest_attributes_governance_metadata() -> None:
    batch_uuid = uuid.uuid4()
    inserted_id = uuid.uuid4()
    evidence = WestmetallFetchEvidence(
        source_url="https://example.test",
        html_sha256="a" * 64,
        fetched_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )
    mock_session = MagicMock()

    with patch("app.tasks.westmetall_task.SessionLocal", return_value=mock_session), patch(
        "app.tasks.westmetall_task.ingest_westmetall_cash_settlement_bulk",
        return_value=([inserted_id], batch_uuid, 1, 0, evidence),
    ), patch("app.tasks.westmetall_task.AuditTrailService.record_worker_event") as record:
        run_westmetall_ingestion()

    metadata = record.call_args.kwargs["metadata"]
    assert record.call_args.kwargs["event_type"] == "market_data_ingested"
    assert metadata["provider"] == "westmetall"
    assert metadata["instrument"] == "LME_ALU_CASH_SETTLEMENT_DAILY"
    assert metadata["tier_at_ingest_time"] == "trusted"
    assert metadata["is_canonical"] is True
    assert metadata["actor_sub"] == "service:westmetall_ingest"
    assert metadata["inserted_ids"] == [str(inserted_id)]
    assert metadata["source_url"] == evidence.source_url
    assert metadata["html_sha256"] == evidence.html_sha256
    assert metadata["batch_uuid"] == str(batch_uuid)
    mock_session.commit.assert_called_once()
    mock_session.close.assert_called_once()
