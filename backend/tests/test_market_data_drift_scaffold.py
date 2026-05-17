from __future__ import annotations

from decimal import Decimal

from structlog.testing import capture_logs

from app.services.market_data_governance import emit_drift_alert_if_breach


def test_drift_alert_below_threshold_silent() -> None:
    with capture_logs() as logs:
        result = emit_drift_alert_if_breach(
            instrument="LME_ALU_CASH_SETTLEMENT_DAILY",
            observation_key="2026-01-30",
            canonical_provider="westmetall",
            audit_provider="audit",
            canonical_price=Decimal("100"),
            audit_price=Decimal("100.5"),
        )

    assert result is False
    assert logs == []


def test_drift_alert_above_threshold_emitted() -> None:
    with capture_logs() as logs:
        result = emit_drift_alert_if_breach(
            instrument="LME_ALU_CASH_SETTLEMENT_DAILY",
            observation_key="2026-01-30",
            canonical_provider="westmetall",
            audit_provider="audit",
            canonical_price=Decimal("100"),
            audit_price=Decimal("105"),
        )

    assert result is True
    assert logs[-1]["event"] == "market_data_drift_alert"
    assert logs[-1]["instrument"] == "LME_ALU_CASH_SETTLEMENT_DAILY"
    assert logs[-1]["observation_key"] == "2026-01-30"
    assert logs[-1]["canonical_provider"] == "westmetall"
    assert logs[-1]["audit_provider"] == "audit"
    assert logs[-1]["canonical_price"] == "100"
    assert logs[-1]["audit_price"] == "105"
    assert logs[-1]["normalized_drift"] == "0.05"
    assert logs[-1]["threshold"] == "0.01"


def test_drift_alert_zero_canonical_skipped() -> None:
    with capture_logs() as logs:
        result = emit_drift_alert_if_breach(
            instrument="LME_ALU_CASH_SETTLEMENT_DAILY",
            observation_key="2026-01-30",
            canonical_provider="westmetall",
            audit_provider="audit",
            canonical_price=Decimal("0"),
            audit_price=Decimal("105"),
        )

    assert result is False
    assert logs == []
