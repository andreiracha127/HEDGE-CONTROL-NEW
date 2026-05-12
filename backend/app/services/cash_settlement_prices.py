from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.market_data import CashSettlementPrice
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
        db.query(CashSettlementPrice)
        .filter(
            CashSettlementPrice.source == SOURCE_WESTMETALL,
            CashSettlementPrice.symbol == SYMBOL_DAILY,
            CashSettlementPrice.settlement_date == settlement_date,
        )
        .first()
    )
    if existing is not None:
        return None, 0, 1, evidence

    price = CashSettlementPrice(
        source=SOURCE_WESTMETALL,
        symbol=SYMBOL_DAILY,
        settlement_date=settlement_date,
        price_usd=row.price_usd,
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
    html_sha256: str,
    inserted_dates: list[date],
) -> uuid.UUID:
    dates = ",".join(d.isoformat() for d in sorted(inserted_dates))
    canonical_batch_key = (
        f"source={SOURCE_WESTMETALL}|start={start_date.isoformat() if start_date else ''}|"
        f"end={end_date.isoformat() if end_date else ''}|html_sha256={html_sha256}|"
        f"inserted_dates={dates}"
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, canonical_batch_key)


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
            html_sha256=evidence.html_sha256,
            inserted_dates=[],
        )
        return [], batch_uuid, 0, 0, evidence

    # Fetch existing dates in one query to avoid N+1
    existing_dates = set(
        d
        for (d,) in db.query(CashSettlementPrice.settlement_date)
        .filter(
            CashSettlementPrice.source == SOURCE_WESTMETALL,
            CashSettlementPrice.symbol == SYMBOL_DAILY,
            CashSettlementPrice.settlement_date.in_(
                [r.settlement_date for r in rows]
            ),
        )
        .all()
    )

    ingested = 0
    skipped = 0
    inserted_prices: list[CashSettlementPrice] = []
    inserted_dates: list[date] = []
    for row in rows:
        if row.settlement_date in existing_dates:
            skipped += 1
            continue
        price = CashSettlementPrice(
            source=SOURCE_WESTMETALL,
            symbol=SYMBOL_DAILY,
            settlement_date=row.settlement_date,
            price_usd=row.price_usd,
            source_url=evidence.source_url,
            html_sha256=evidence.html_sha256,
            fetched_at=evidence.fetched_at,
        )
        db.add(price)
        inserted_prices.append(price)
        inserted_dates.append(row.settlement_date)
        ingested += 1

    if ingested:
        db.flush()

    batch_uuid = _westmetall_batch_uuid(
        start_date=start_date,
        end_date=end_date,
        html_sha256=evidence.html_sha256,
        inserted_dates=inserted_dates,
    )
    return [price.id for price in inserted_prices], batch_uuid, ingested, skipped, evidence
