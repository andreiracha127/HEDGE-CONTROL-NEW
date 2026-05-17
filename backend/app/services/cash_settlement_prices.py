from __future__ import annotations

import uuid
import json
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.market_data import CashSettlementPrice
from app.services.market_data_governance import (
    BulkContentMismatch,
    classify_bulk_row_replay,
    emit_bulk_content_mismatch_rejection,
    emit_bulk_idempotent_skip,
    is_canonical,
)
from app.services.westmetall_cash_settlement import (
    SOURCE_WESTMETALL,
    SYMBOL_DAILY,
    WESTMETALL_DAILY_URL,
    WestmetallFetchEvidence,
    fetch_westmetall_html,
    parse_westmetall_daily_rows,
)


def ingest_westmetall_cash_settlement_daily_for_date(
    db: Session,
    settlement_date: date,
) -> tuple[uuid.UUID | None, int, int, WestmetallFetchEvidence]:
    html, evidence = fetch_westmetall_html(WESTMETALL_DAILY_URL)
    rows = parse_westmetall_daily_rows(html)
    row = next((r for r in rows if r.settlement_date == settlement_date), None)
    if row is None:
        return None, 0, 0, evidence

    existing = (
        db.query(CashSettlementPrice.id, CashSettlementPrice.price_usd)
        .filter(
            CashSettlementPrice.source == SOURCE_WESTMETALL,
            CashSettlementPrice.symbol == SYMBOL_DAILY,
            CashSettlementPrice.settlement_date == settlement_date,
        )
        .first()
    )
    if existing is not None:
        existing_id, existing_price_usd = existing
        outcome = classify_bulk_row_replay(
            new_price_usd=row.price_usd,
            existing_price_usd=existing_price_usd,
        )
        if outcome == "idempotent_skip":
            emit_bulk_idempotent_skip(
                provider=SOURCE_WESTMETALL,
                instrument=SYMBOL_DAILY,
                settlement_date=settlement_date,
                actor_sub="service:westmetall_ingest",
            )
            return existing_id, 0, 1, evidence
        emit_bulk_content_mismatch_rejection(
            provider=SOURCE_WESTMETALL,
            instrument=SYMBOL_DAILY,
            settlement_date=settlement_date,
            new_price_usd=row.price_usd,
            existing_price_usd=existing_price_usd,
            actor_sub="service:westmetall_ingest",
        )
        raise BulkContentMismatch(
            f"price_usd mismatch for ({SOURCE_WESTMETALL}, {SYMBOL_DAILY}, "
            f"{settlement_date.isoformat()}): new={row.price_usd} "
            f"existing={existing_price_usd}"
        )

    price = CashSettlementPrice(
        source=SOURCE_WESTMETALL,
        symbol=SYMBOL_DAILY,
        settlement_date=settlement_date,
        price_usd=row.price_usd,
        is_canonical=is_canonical(SOURCE_WESTMETALL, SYMBOL_DAILY),
        source_url=evidence.source_url,
        html_sha256=evidence.html_sha256,
        fetched_at=evidence.fetched_at,
    )
    db.add(price)
    db.flush()
    return price.id, 1, 0, evidence


def _westmetall_batch_uuid(
    *,
    start_date: Optional[date],
    end_date: Optional[date],
) -> uuid.UUID:
    payload = {
        "source": SOURCE_WESTMETALL,
        "symbol": SYMBOL_DAILY,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    }
    return uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(payload, sort_keys=True))


def ingest_westmetall_cash_settlement_bulk(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> tuple[list[uuid.UUID], uuid.UUID, int, int, WestmetallFetchEvidence]:
    """Fetch Westmetall and ingest all available daily rows.

    Optionally restrict to ``[start_date, end_date]``.
    Returns ``(inserted_ids, batch_uuid, ingested_count, skipped_count, evidence)``.
    """
    html, evidence = fetch_westmetall_html(WESTMETALL_DAILY_URL)
    rows = parse_westmetall_daily_rows(html)

    if start_date:
        rows = [r for r in rows if r.settlement_date >= start_date]
    if end_date:
        rows = [r for r in rows if r.settlement_date <= end_date]

    if not rows:
        batch_uuid = _westmetall_batch_uuid(
            start_date=start_date,
            end_date=end_date,
        )
        return [], batch_uuid, 0, 0, evidence

    existing_price_by_date = {
        settlement_date: price_usd
        for settlement_date, price_usd in db.query(
            CashSettlementPrice.settlement_date,
            CashSettlementPrice.price_usd,
        )
        .filter(
            CashSettlementPrice.source == SOURCE_WESTMETALL,
            CashSettlementPrice.symbol == SYMBOL_DAILY,
            CashSettlementPrice.settlement_date.in_(
                [r.settlement_date for r in rows]
            ),
        )
        .all()
    }

    ingested = 0
    skipped = 0
    inserted_prices: list[CashSettlementPrice] = []
    canonical_flag = is_canonical(SOURCE_WESTMETALL, SYMBOL_DAILY)
    for row in rows:
        existing_price_usd = existing_price_by_date.get(row.settlement_date)
        if existing_price_usd is not None:
            outcome = classify_bulk_row_replay(
                new_price_usd=row.price_usd,
                existing_price_usd=existing_price_usd,
            )
            if outcome == "idempotent_skip":
                emit_bulk_idempotent_skip(
                    provider=SOURCE_WESTMETALL,
                    instrument=SYMBOL_DAILY,
                    settlement_date=row.settlement_date,
                    actor_sub="service:westmetall_ingest",
                )
                skipped += 1
                continue
            emit_bulk_content_mismatch_rejection(
                provider=SOURCE_WESTMETALL,
                instrument=SYMBOL_DAILY,
                settlement_date=row.settlement_date,
                new_price_usd=row.price_usd,
                existing_price_usd=existing_price_usd,
                actor_sub="service:westmetall_ingest",
            )
            raise BulkContentMismatch(
                f"price_usd mismatch for ({SOURCE_WESTMETALL}, {SYMBOL_DAILY}, "
                f"{row.settlement_date.isoformat()}): new={row.price_usd} "
                f"existing={existing_price_usd}"
            )
        price = CashSettlementPrice(
            source=SOURCE_WESTMETALL,
            symbol=SYMBOL_DAILY,
            settlement_date=row.settlement_date,
            price_usd=row.price_usd,
            is_canonical=canonical_flag,
            source_url=evidence.source_url,
            html_sha256=evidence.html_sha256,
            fetched_at=evidence.fetched_at,
        )
        db.add(price)
        inserted_prices.append(price)
        ingested += 1

    if ingested:
        db.flush()

    batch_uuid = _westmetall_batch_uuid(
        start_date=start_date,
        end_date=end_date,
    )
    return [price.id for price in inserted_prices], batch_uuid, ingested, skipped, evidence
