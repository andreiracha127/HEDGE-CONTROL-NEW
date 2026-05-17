from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from structlog.testing import capture_logs

from app.models.market_data import CashSettlementPrice
from app.tasks.market_data_staleness_task import run_market_data_staleness_check


def _seed(session, fetched_at: datetime) -> None:
    session.add(
        CashSettlementPrice(
            source="westmetall",
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=fetched_at.date(),
            price_usd=Decimal("100"),
            is_canonical=True,
            source_url="u",
            html_sha256="h",
            fetched_at=fetched_at,
        )
    )
    session.commit()


def test_staleness_check_emits_alert_when_no_rows() -> None:
    with capture_logs() as logs:
        run_market_data_staleness_check()

    assert any(event["event"] == "market_data_stale_feed" for event in logs)


def test_staleness_check_quiet_when_recent_row(session) -> None:
    _seed(session, datetime.now(timezone.utc) - timedelta(hours=1))

    with capture_logs() as logs:
        run_market_data_staleness_check()

    assert not any(event["event"] == "market_data_stale_feed" for event in logs)


def test_staleness_check_emits_alert_when_gap_exceeds(session) -> None:
    _seed(session, datetime.now(timezone.utc) - timedelta(hours=100))

    with capture_logs() as logs:
        run_market_data_staleness_check()

    assert any(event["event"] == "market_data_stale_feed" for event in logs)
