from __future__ import annotations

from datetime import date

import pytest

from app.models.audit import AuditEvent
from app.models.market_data import CashSettlementPrice
from app.services import westmetall_cash_settlement


@pytest.fixture(autouse=True)
def _westmetall_service_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_SERVICE_ACTOR_SUB", "service:westmetall_ingest")


class _FakeResponse:
    def __init__(self, html: bytes) -> None:
        self.content = html
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


def _html(rows: list[tuple[str, str]]) -> bytes:
    body = "".join(f"<tr><td>{day}</td><td>{price}</td></tr>" for day, price in rows)
    return f"<html><table>{body}</table></html>".encode()


def _mock_westmetall(monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, str]]) -> None:
    html = _html(rows)
    monkeypatch.setattr(
        westmetall_cash_settlement.httpx,
        "get",
        lambda url, timeout: _FakeResponse(html),
    )


def test_post_ingest_persists_audit_metadata_with_governance_fields(client, session, monkeypatch) -> None:
    _mock_westmetall(monkeypatch, [("30.01.2026", "2,567.50")])

    response = client.post(
        "/market-data/westmetall/aluminum/cash-settlement/ingest",
        json={
            "settlement_date": "2026-01-30",
            "provider_timestamp": "1999-01-01T00:00:00Z",
            "sequence_number": 999,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["is_canonical"] is True
    price = session.query(CashSettlementPrice).one()
    event = session.query(AuditEvent).filter(AuditEvent.entity_id == price.id).one()
    metadata = event.payload["metadata"]
    assert event.event_type == "market_data_ingested"
    assert metadata["provider"] == "westmetall"
    assert metadata["instrument"] == "LME_ALU_CASH_SETTLEMENT_DAILY"
    assert metadata["tier_at_ingest_time"] == "trusted"
    assert metadata["is_canonical"] is True
    assert metadata["replay_key"]["settlement_date"] == "2026-01-30"
    assert "batch_id" not in metadata["replay_key"]
    assert "provider_timestamp" not in metadata
    assert "sequence_number" not in metadata


def test_post_ingest_mismatch_returns_409(client, session, monkeypatch) -> None:
    _mock_westmetall(monkeypatch, [("30.01.2026", "2,567.50")])
    first = client.post(
        "/market-data/westmetall/aluminum/cash-settlement/ingest",
        json={"settlement_date": "2026-01-30"},
    )
    assert first.status_code == 200, first.text

    _mock_westmetall(monkeypatch, [("30.01.2026", "9,999.00")])
    second = client.post(
        "/market-data/westmetall/aluminum/cash-settlement/ingest",
        json={"settlement_date": "2026-01-30"},
    )

    assert second.status_code == 409
    assert "price_usd mismatch" in second.json()["detail"]
    assert session.query(CashSettlementPrice).count() == 1


def test_post_ingest_bulk_all_skip_still_persists_audit_metadata(client, session, monkeypatch) -> None:
    rows = [("02.02.2026", "2,600.00"), ("03.02.2026", "2,610.00")]
    _mock_westmetall(monkeypatch, rows)
    first = client.post(
        "/market-data/westmetall/aluminum/cash-settlement/ingest-bulk",
        json={"start_date": "2026-02-02", "end_date": "2026-02-03"},
    )
    assert first.status_code == 200, first.text

    _mock_westmetall(monkeypatch, rows)
    second = client.post(
        "/market-data/westmetall/aluminum/cash-settlement/ingest-bulk",
        json={"start_date": "2026-02-02", "end_date": "2026-02-03"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["is_canonical"] is True
    assert second.json()["ingested_count"] == 0
    assert second.json()["skipped_count"] == 2

    events = (
        session.query(AuditEvent)
        .filter(AuditEvent.event_type == "market_data_ingested")
        .order_by(AuditEvent.timestamp_utc.asc())
        .all()
    )
    assert len(events) == 2
    metadata = events[-1].payload["metadata"]
    assert metadata["outcome"] == "all_skip"
    assert metadata["replay_key"]["batch_id"] == str(events[-1].entity_id)
    assert "settlement_date" not in metadata["replay_key"]


def test_monthly_average_uses_only_canonical_rows(client, session) -> None:
    from datetime import datetime, timezone
    from decimal import Decimal

    session.add_all(
        [
            CashSettlementPrice(
                source="westmetall",
                symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                settlement_date=date(2026, 1, 2),
                price_usd=Decimal("100"),
                is_canonical=True,
                source_url="u",
                html_sha256="h",
                fetched_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
            CashSettlementPrice(
                source="audit",
                symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                settlement_date=date(2026, 1, 3),
                price_usd=Decimal("10000"),
                is_canonical=False,
                source_url="u",
                html_sha256="h",
                fetched_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
            ),
        ]
    )
    session.commit()

    response = client.get(
        "/market-data/westmetall/aluminum/cash-settlement/prices?symbol=LME_ALU_MONTHLY_AVG"
    )

    assert response.status_code == 200, response.text
    assert response.json()[0]["price_usd"] == "100.00"
    assert response.json()[0]["is_canonical"] is True
