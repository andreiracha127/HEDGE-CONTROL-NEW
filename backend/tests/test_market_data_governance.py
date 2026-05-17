from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from structlog.testing import capture_logs

from app.services.market_data_governance import (
    BulkContentMismatch,
    MarketDataAuditMetadata,
    ReplayWindowViolation,
    canonical_provider_for_instrument,
    check_replay_window,
    classify_bulk_row_replay,
    compute_normalized_drift,
    drift_threshold_for,
    emit_bulk_content_mismatch_rejection,
    emit_bulk_idempotent_skip,
    emit_drift_alert_if_breach,
    emit_stale_feed_if_breach,
    is_canonical,
    max_gap_hours_for,
    replay_window_minutes_for,
    tier_for_provider,
)


INSTRUMENT = "LME_ALU_CASH_SETTLEMENT_DAILY"


def test_tier_for_provider_returns_trusted_for_westmetall() -> None:
    assert tier_for_provider("westmetall") == "trusted"


def test_tier_for_provider_raises_on_unknown() -> None:
    with pytest.raises(ValueError, match="constitutional tier"):
        tier_for_provider("unknown_provider")


def test_canonical_provider_default_lookup() -> None:
    assert canonical_provider_for_instrument(INSTRUMENT) == "westmetall"


def test_canonical_provider_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MARKET_DATA_CANONICAL_PROVIDER_LME_ALU_CASH_SETTLEMENT_DAILY",
        "fakeprovider",
    )
    assert canonical_provider_for_instrument(INSTRUMENT) == "fakeprovider"


def test_canonical_provider_raises_on_unknown_instrument() -> None:
    with pytest.raises(ValueError, match="no canonical provider"):
        canonical_provider_for_instrument("UNKNOWN")


def test_is_canonical_true_for_westmetall() -> None:
    assert is_canonical("westmetall", INSTRUMENT) is True


def test_is_canonical_false_for_other_provider() -> None:
    assert is_canonical("fakeprovider", INSTRUMENT) is False


def test_replay_window_default_30_minutes() -> None:
    assert replay_window_minutes_for("westmetall") == 30


def test_replay_window_per_provider_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKET_DATA_REPLAY_WINDOW_WESTMETALL_MINUTES", "10")
    assert replay_window_minutes_for("westmetall") == 10


def test_replay_window_global_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKET_DATA_REPLAY_WINDOW_MINUTES", "5")
    assert replay_window_minutes_for("westmetall") == 5


def test_check_replay_window_accepts_within_tolerance() -> None:
    now = datetime(2026, 5, 16, 12, tzinfo=timezone.utc)
    check_replay_window(
        provider="westmetall",
        instrument=INSTRUMENT,
        provider_timestamp=now - timedelta(minutes=15),
        sequence_number=1,
        actor_sub="service:westmetall_ingest",
        now=now,
    )


def test_check_replay_window_rejects_outside_tolerance() -> None:
    now = datetime(2026, 5, 16, 12, tzinfo=timezone.utc)
    with capture_logs() as logs:
        with pytest.raises(ReplayWindowViolation):
            check_replay_window(
                provider="westmetall",
                instrument=INSTRUMENT,
                provider_timestamp=now - timedelta(minutes=45),
                sequence_number=1,
                actor_sub="service:westmetall_ingest",
                now=now,
            )
    assert logs[-1]["event"] == "market_data_replay_rejected"
    assert logs[-1]["reason"] == "timestamp_out_of_window"


def test_classify_bulk_row_replay_idempotent_skip_on_match() -> None:
    assert (
        classify_bulk_row_replay(
            new_price_usd=Decimal("100.00"),
            existing_price_usd=Decimal("100.00"),
        )
        == "idempotent_skip"
    )


def test_classify_bulk_row_replay_content_mismatch_on_diff() -> None:
    assert (
        classify_bulk_row_replay(
            new_price_usd=Decimal("100.00"),
            existing_price_usd=Decimal("100.01"),
        )
        == "content_mismatch"
    )


def test_classify_bulk_row_replay_rejects_float_new_price() -> None:
    with pytest.raises(TypeError):
        classify_bulk_row_replay(
            new_price_usd=100.0,  # type: ignore[arg-type]
            existing_price_usd=Decimal("100.00"),
        )


def test_classify_bulk_row_replay_rejects_float_existing_price() -> None:
    with pytest.raises(TypeError):
        classify_bulk_row_replay(
            new_price_usd=Decimal("100.00"),
            existing_price_usd=100.0,  # type: ignore[arg-type]
        )


def test_classify_bulk_row_replay_exact_compare_not_tolerance() -> None:
    assert (
        classify_bulk_row_replay(
            new_price_usd=Decimal("100.000001"),
            existing_price_usd=Decimal("100.000000"),
        )
        == "content_mismatch"
    )


def test_emit_bulk_idempotent_skip_has_no_reason_field() -> None:
    with capture_logs() as logs:
        emit_bulk_idempotent_skip(
            provider="westmetall",
            instrument=INSTRUMENT,
            settlement_date=date(2026, 5, 16),
            actor_sub="service:westmetall_ingest",
        )
    assert logs[-1]["event"] == "market_data_bulk_idempotent_skip"
    assert "reason" not in logs[-1]


def test_emit_bulk_content_mismatch_rejection_has_reason_bulk_content_mismatch() -> None:
    with capture_logs() as logs:
        emit_bulk_content_mismatch_rejection(
            provider="westmetall",
            instrument=INSTRUMENT,
            settlement_date=date(2026, 5, 16),
            new_price_usd=Decimal("101"),
            existing_price_usd=Decimal("100"),
            actor_sub="service:westmetall_ingest",
        )
    assert logs[-1]["event"] == "market_data_replay_rejected"
    assert logs[-1]["reason"] == "bulk_content_mismatch"


def test_compute_normalized_drift_basic() -> None:
    assert compute_normalized_drift(
        canonical_price=Decimal("100"),
        audit_price=Decimal("101"),
    ) == Decimal("0.01")


def test_compute_normalized_drift_zero_canonical_returns_none() -> None:
    assert compute_normalized_drift(
        canonical_price=Decimal("0"),
        audit_price=Decimal("101"),
    ) is None


def test_drift_threshold_default_one_percent() -> None:
    assert drift_threshold_for(INSTRUMENT) == Decimal("0.01")


def test_drift_threshold_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKET_DATA_DRIFT_THRESHOLD_LME_ALU_CASH_SETTLEMENT_DAILY", "0.05")
    assert drift_threshold_for(INSTRUMENT) == Decimal("0.05")


def test_emit_drift_alert_below_threshold_returns_false() -> None:
    with capture_logs() as logs:
        result = emit_drift_alert_if_breach(
            instrument=INSTRUMENT,
            observation_key="2026-05-16",
            canonical_provider="westmetall",
            audit_provider="audit",
            canonical_price=Decimal("100"),
            audit_price=Decimal("100.5"),
        )
    assert result is False
    assert logs == []


def test_emit_drift_alert_above_threshold_returns_true_and_emits() -> None:
    with capture_logs() as logs:
        result = emit_drift_alert_if_breach(
            instrument=INSTRUMENT,
            observation_key="2026-05-16",
            canonical_provider="westmetall",
            audit_provider="audit",
            canonical_price=Decimal("100"),
            audit_price=Decimal("105"),
        )
    assert result is True
    assert logs[-1]["event"] == "market_data_drift_alert"


def test_emit_drift_alert_zero_canonical_returns_false() -> None:
    with capture_logs() as logs:
        result = emit_drift_alert_if_breach(
            instrument=INSTRUMENT,
            observation_key="2026-05-16",
            canonical_provider="westmetall",
            audit_provider="audit",
            canonical_price=Decimal("0"),
            audit_price=Decimal("105"),
        )
    assert result is False
    assert logs == []


def test_max_gap_hours_default_westmetall_aluminum() -> None:
    assert max_gap_hours_for("westmetall", INSTRUMENT) == 96


def test_max_gap_hours_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKET_DATA_MAX_GAP_HOURS_WESTMETALL_LME_ALU_CASH_SETTLEMENT_DAILY", "12")
    assert max_gap_hours_for("westmetall", INSTRUMENT) == 12


def test_max_gap_hours_raises_on_unknown_pair() -> None:
    with pytest.raises(ValueError, match="No max_gap_hours"):
        max_gap_hours_for("unknown", INSTRUMENT)


def test_emit_stale_feed_below_threshold_returns_false() -> None:
    now = datetime(2026, 5, 16, 12, tzinfo=timezone.utc)
    with capture_logs() as logs:
        result = emit_stale_feed_if_breach(
            provider="westmetall",
            instrument=INSTRUMENT,
            last_ingest_at=now - timedelta(hours=1),
            now=now,
        )
    assert result is False
    assert logs == []


def test_emit_stale_feed_above_threshold_returns_true_and_emits() -> None:
    now = datetime(2026, 5, 16, 12, tzinfo=timezone.utc)
    with capture_logs() as logs:
        result = emit_stale_feed_if_breach(
            provider="westmetall",
            instrument=INSTRUMENT,
            last_ingest_at=now - timedelta(hours=100),
            now=now,
        )
    assert result is True
    assert logs[-1]["event"] == "market_data_stale_feed"


def test_emit_stale_feed_no_last_ingest_at_returns_true() -> None:
    with capture_logs() as logs:
        result = emit_stale_feed_if_breach(
            provider="westmetall",
            instrument=INSTRUMENT,
            last_ingest_at=None,
        )
    assert result is True
    assert logs[-1]["event"] == "market_data_stale_feed"


def test_market_data_audit_metadata_as_dict_live_fields() -> None:
    metadata = MarketDataAuditMetadata(
        provider="westmetall",
        instrument=INSTRUMENT,
        actor_sub="service:westmetall_ingest",
        tier_at_ingest_time="trusted",
        is_canonical=True,
        provider_timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
        sequence_number=42,
    ).as_metadata_dict()

    assert metadata["provider_timestamp"] == "2026-05-16T00:00:00+00:00"
    assert metadata["sequence_number"] == 42
    assert "replay_key" not in metadata


def test_market_data_audit_metadata_post_init_rejects_empty_identifiers() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        MarketDataAuditMetadata(
            provider="westmetall",
            instrument=INSTRUMENT,
            actor_sub="service:westmetall_ingest",
            tier_at_ingest_time="trusted",
            is_canonical=True,
        )


def test_market_data_audit_metadata_post_init_rejects_partial_live() -> None:
    with pytest.raises(ValueError, match="provided together"):
        MarketDataAuditMetadata(
            provider="westmetall",
            instrument=INSTRUMENT,
            actor_sub="service:westmetall_ingest",
            tier_at_ingest_time="trusted",
            is_canonical=True,
            provider_timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
        )


def test_market_data_audit_metadata_as_dict_single_date_replay_key() -> None:
    metadata = MarketDataAuditMetadata(
        provider="westmetall",
        instrument=INSTRUMENT,
        actor_sub="service:westmetall_ingest",
        tier_at_ingest_time="trusted",
        is_canonical=True,
        single_date_replay_key=date(2026, 5, 16),
    ).as_metadata_dict()

    assert metadata["replay_key"] == {
        "source": "westmetall",
        "symbol": INSTRUMENT,
        "settlement_date": "2026-05-16",
    }


def test_market_data_audit_metadata_as_dict_batch_replay_id() -> None:
    metadata = MarketDataAuditMetadata(
        provider="westmetall",
        instrument=INSTRUMENT,
        actor_sub="service:westmetall_ingest",
        tier_at_ingest_time="trusted",
        is_canonical=True,
        batch_replay_id="batch-uuid-abc",
    ).as_metadata_dict()

    assert metadata["replay_key"] == {
        "source": "westmetall",
        "symbol": INSTRUMENT,
        "batch_id": "batch-uuid-abc",
    }
    assert "settlement_date" not in metadata["replay_key"]


def test_market_data_audit_metadata_post_init_rejects_both_replay_keys() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        MarketDataAuditMetadata(
            provider="westmetall",
            instrument=INSTRUMENT,
            actor_sub="service:westmetall_ingest",
            tier_at_ingest_time="trusted",
            is_canonical=True,
            single_date_replay_key=date(2026, 5, 16),
            batch_replay_id="x",
        )


def test_bulk_content_mismatch_exception_is_available() -> None:
    assert str(BulkContentMismatch("x")) == "x"
