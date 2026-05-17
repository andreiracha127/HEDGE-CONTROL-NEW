from datetime import datetime
from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.models.market_data import CashSettlementPrice
from app.services import westmetall_cash_settlement


@pytest.fixture(autouse=True)
def _westmetall_service_actor(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_ACTOR_SUB", "service:westmetall_ingest")


class _FakeResponse:
    def __init__(self, html: bytes) -> None:
        self.content = html
        self.status_code = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")


def _fake_get_factory(html: bytes):
    def _fake_get(url: str, timeout: float):
        _ = url, timeout
        return _FakeResponse(html)

    return _fake_get


def test_ingest_inserts_then_skips_idempotently(client, monkeypatch) -> None:
    html = b"""
    <html><body>
      <table>
        <tr><th>Date</th><th>Cash Settlement</th></tr>
        <tr><td>30.01.2026</td><td>2,567.50</td></tr>
      </table>
    </body></html>
    """
    monkeypatch.setattr(westmetall_cash_settlement.httpx, "get", _fake_get_factory(html))

    resp1 = client.post(
        "/market-data/westmetall/aluminum/cash-settlement/ingest",
        json={"settlement_date": "2026-01-30"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["ingested_count"] == 1
    assert resp1.json()["skipped_count"] == 0

    # Different HTML value is a content mismatch, not an idempotent skip.
    html_changed = b"""
    <html><body>
      <table>
        <tr><th>Date</th><th>Cash Settlement</th></tr>
        <tr><td>30.01.2026</td><td>9,999.00</td></tr>
      </table>
    </body></html>
    """
    monkeypatch.setattr(westmetall_cash_settlement.httpx, "get", _fake_get_factory(html_changed))
    resp2 = client.post(
        "/market-data/westmetall/aluminum/cash-settlement/ingest",
        json={"settlement_date": "2026-01-30"},
    )
    assert resp2.status_code == 409

    with SessionLocal() as session:
        row = session.query(CashSettlementPrice).first()
        assert row is not None
        assert row.price_usd == Decimal("2567.500000")
        assert row.is_canonical is True
        assert row.source == "westmetall"
        assert row.symbol == "LME_ALU_CASH_SETTLEMENT_DAILY"
        assert row.source_url.startswith("https://")
        assert len(row.html_sha256) == 64
        assert isinstance(row.fetched_at, datetime)


def test_layout_error_hard_fails(client, monkeypatch) -> None:
    monkeypatch.setattr(westmetall_cash_settlement.httpx, "get", _fake_get_factory(b"<html></html>"))
    resp = client.post(
        "/market-data/westmetall/aluminum/cash-settlement/ingest",
        json={"settlement_date": "2026-01-30"},
    )
    assert resp.status_code == 502
