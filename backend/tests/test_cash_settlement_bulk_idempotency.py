from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from structlog.testing import capture_logs

from app.models.market_data import CashSettlementPrice
from app.services import cash_settlement_prices as service
from app.services.market_data_governance import BulkContentMismatch
from app.services.westmetall_cash_settlement import (
    SOURCE_WESTMETALL,
    SYMBOL_DAILY,
    WestmetallDailyRow,
    WestmetallFetchEvidence,
)


def _evidence(html_sha256: str = "a" * 64) -> WestmetallFetchEvidence:
    return WestmetallFetchEvidence(
        source_url="https://example.test/westmetall",
        html_sha256=html_sha256,
        fetched_at=datetime(2026, 5, 16, 12, tzinfo=timezone.utc),
    )


def _row(day: int, price: str) -> WestmetallDailyRow:
    return WestmetallDailyRow(date(2026, 1, day), Decimal(price))


def _mock_provider(monkeypatch: pytest.MonkeyPatch, rows, html_sha256: str = "a" * 64) -> None:
    monkeypatch.setattr(
        service,
        "fetch_westmetall_html",
        lambda _url: (b"<html></html>", _evidence(html_sha256)),
    )
    monkeypatch.setattr(service, "parse_westmetall_daily_rows", lambda _html: rows)


def _seed(session, day: int, price: str, html_sha256: str = "seed") -> CashSettlementPrice:
    row = CashSettlementPrice(
        source=SOURCE_WESTMETALL,
        symbol=SYMBOL_DAILY,
        settlement_date=date(2026, 1, day),
        price_usd=Decimal(price),
        is_canonical=True,
        source_url="https://seed.test",
        html_sha256=html_sha256,
        fetched_at=datetime(2026, 1, day, tzinfo=timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


def test_daily_for_date_first_insert_persists_decimal_price(session, monkeypatch) -> None:
    _mock_provider(monkeypatch, [_row(30, "2567.50")])

    inserted_id, ingested, skipped, _ = service.ingest_westmetall_cash_settlement_daily_for_date(
        session, date(2026, 1, 30)
    )

    assert inserted_id is not None
    assert (ingested, skipped) == (1, 0)
    row = session.get(CashSettlementPrice, inserted_id)
    assert row is not None
    assert isinstance(row.price_usd, Decimal)
    assert row.price_usd == Decimal("2567.50")
    assert row.is_canonical is True


def test_daily_for_date_matching_existing_emits_idempotent_skip(session, monkeypatch) -> None:
    existing = _seed(session, 30, "2567.50")
    _mock_provider(monkeypatch, [_row(30, "2567.50")])

    with capture_logs() as logs:
        inserted_id, ingested, skipped, _ = service.ingest_westmetall_cash_settlement_daily_for_date(
            session, date(2026, 1, 30)
        )

    assert inserted_id == existing.id
    assert (ingested, skipped) == (0, 1)
    assert logs[-1]["event"] == "market_data_bulk_idempotent_skip"


def test_daily_for_date_differing_existing_raises_bulk_content_mismatch(session, monkeypatch) -> None:
    existing = _seed(session, 30, "2567.50")
    _mock_provider(monkeypatch, [_row(30, "2700.00")])

    with capture_logs() as logs:
        with pytest.raises(BulkContentMismatch):
            service.ingest_westmetall_cash_settlement_daily_for_date(
                session, date(2026, 1, 30)
            )

    session.refresh(existing)
    assert existing.price_usd == Decimal("2567.50")
    assert logs[-1]["event"] == "market_data_replay_rejected"
    assert logs[-1]["reason"] == "bulk_content_mismatch"


def test_bulk_ingest_mixed_existing_and_new_persists_only_new(session, monkeypatch) -> None:
    _seed(session, 28, "2500.00")
    _seed(session, 29, "2501.00")
    _mock_provider(
        monkeypatch,
        [
            _row(26, "2498.00"),
            _row(27, "2499.00"),
            _row(28, "2500.00"),
            _row(29, "2501.00"),
            _row(30, "2502.00"),
        ],
    )

    with capture_logs() as logs:
        inserted_ids, _batch_uuid, ingested, skipped, _ = service.ingest_westmetall_cash_settlement_bulk(session)

    assert len(inserted_ids) == 3
    assert (ingested, skipped) == (3, 2)
    assert sum(1 for event in logs if event["event"] == "market_data_bulk_idempotent_skip") == 2
    assert session.query(CashSettlementPrice).count() == 5


def test_bulk_ingest_mismatch_in_middle_rejects_entire_batch(session, monkeypatch) -> None:
    _seed(session, 28, "2500.00")
    session.commit()
    _mock_provider(
        monkeypatch,
        [_row(27, "2499.00"), _row(28, "2600.00"), _row(29, "2501.00")],
    )

    with pytest.raises(BulkContentMismatch):
        service.ingest_westmetall_cash_settlement_bulk(session)
    session.rollback()

    assert session.query(CashSettlementPrice).count() == 1


def test_bulk_ingest_sets_is_canonical_true_for_westmetall(session, monkeypatch) -> None:
    _mock_provider(monkeypatch, [_row(29, "2501.00"), _row(30, "2502.00")])

    inserted_ids, _batch_uuid, ingested, skipped, _ = service.ingest_westmetall_cash_settlement_bulk(session)

    assert len(inserted_ids) == 2
    assert (ingested, skipped) == (2, 0)
    assert all(session.get(CashSettlementPrice, row_id).is_canonical is True for row_id in inserted_ids)


def test_html_sha256_not_used_for_row_idempotency(session, monkeypatch) -> None:
    existing = _seed(session, 30, "2567.50", html_sha256="hashA")
    _mock_provider(monkeypatch, [_row(30, "2567.50")], html_sha256="hashB")

    with capture_logs() as logs:
        inserted_id, ingested, skipped, _ = service.ingest_westmetall_cash_settlement_daily_for_date(
            session, date(2026, 1, 30)
        )

    assert inserted_id == existing.id
    assert (ingested, skipped) == (0, 1)
    assert logs[-1]["event"] == "market_data_bulk_idempotent_skip"


def test_westmetall_batch_uuid_stable_across_content_changes() -> None:
    batch_a = service._westmetall_batch_uuid(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    batch_b = service._westmetall_batch_uuid(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    assert batch_a == batch_b
