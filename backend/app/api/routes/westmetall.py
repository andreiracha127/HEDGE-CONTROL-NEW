import calendar
import uuid as _uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import require_any_role, require_service_identity
from app.core.database import get_session
from app.core.rate_limit import RATE_LIMIT_SCRAPING, limiter
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.models.market_data import CashSettlementPrice
from app.services.cash_settlement_prices import (
    ingest_westmetall_cash_settlement_bulk,
    ingest_westmetall_cash_settlement_daily_for_date,
)
from app.services.market_data_governance import (
    BulkContentMismatch,
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
from app.schemas.market_data import (
    CashSettlementBulkIngestRequest,
    CashSettlementBulkIngestResponse,
    CashSettlementIngestRequest,
    CashSettlementIngestResponse,
    CashSettlementPriceRead,
)

SYMBOL_MONTHLY_AVG = "LME_ALU_MONTHLY_AVG"
_NS_MONTHLY = _uuid.UUID("b3a1c2d4-e5f6-4890-abcd-ef1234567890")

router = APIRouter()


def _compute_monthly_averages(
    session: Session,
    start_date: Optional[date],
    end_date: Optional[date],
    limit: int,
) -> list[CashSettlementPriceRead]:
    """Compute monthly-average prices from daily LME_ALU_CASH_SETTLEMENT_DAILY rows."""
    q = session.query(CashSettlementPrice).filter(
        CashSettlementPrice.symbol == SYMBOL_DAILY,
        CashSettlementPrice.is_canonical.is_(True),
    )
    if start_date:
        q = q.filter(CashSettlementPrice.settlement_date >= start_date)
    if end_date:
        q = q.filter(CashSettlementPrice.settlement_date <= end_date)
    rows = q.order_by(CashSettlementPrice.settlement_date.asc()).all()

    # Group by (year, month)
    monthly: dict[tuple[int, int], list[Decimal]] = defaultdict(list)
    for r in rows:
        key = (r.settlement_date.year, r.settlement_date.month)
        monthly[key].append(r.price_usd)

    now = datetime.now(timezone.utc)
    results: list[CashSettlementPriceRead] = []
    for (year, month), prices in sorted(monthly.items(), reverse=True):
        if not prices:
            continue
        last_day = calendar.monthrange(year, month)[1]
        avg_price = sum(prices, Decimal("0")) / Decimal(len(prices))
        month_id = _uuid.uuid5(_NS_MONTHLY, f"{year}-{month:02d}")
        results.append(
            CashSettlementPriceRead(
                id=month_id,
                source="computed",
                symbol=SYMBOL_MONTHLY_AVG,
                settlement_date=date(year, month, last_day),
                price_usd=avg_price.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_EVEN
                ),
                is_canonical=True,
                source_url="computed_from_daily",
                html_sha256="n/a",
                fetched_at=now,
                created_at=now,
            )
        )
    return results[:limit]


@router.get(
    "/aluminum/cash-settlement/prices",
    response_model=list[CashSettlementPriceRead],
    status_code=status.HTTP_200_OK,
)
def list_cash_settlement_prices(
    start_date: Optional[date] = Query(
        None, description="Start of date range (inclusive)"
    ),
    end_date: Optional[date] = Query(None, description="End of date range (inclusive)"),
    symbol: Optional[str] = Query(None, description="Symbol filter"),
    limit: int = Query(500, ge=1, le=5000),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> list[CashSettlementPriceRead]:
    # Monthly average: compute dynamically from daily prices
    if symbol and symbol.upper() == SYMBOL_MONTHLY_AVG:
        return _compute_monthly_averages(session, start_date, end_date, limit)

    q = session.query(CashSettlementPrice)
    if start_date:
        q = q.filter(CashSettlementPrice.settlement_date >= start_date)
    if end_date:
        q = q.filter(CashSettlementPrice.settlement_date <= end_date)
    if symbol:
        q = q.filter(CashSettlementPrice.symbol.ilike(f"%{symbol}%"))
    q = q.order_by(CashSettlementPrice.settlement_date.desc()).limit(limit)
    rows = q.all()
    return [CashSettlementPriceRead.model_validate(r) for r in rows]


@router.post(
    "/aluminum/cash-settlement/ingest",
    response_model=CashSettlementIngestResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit(RATE_LIMIT_SCRAPING)
def ingest_cash_settlement_daily(
    payload: CashSettlementIngestRequest,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="cash_settlement_price",
            event_type="market_data_ingested",
        )
    ),
    __: None = Depends(require_service_identity("westmetall_ingest")),
    session: Session = Depends(get_session),
) -> CashSettlementIngestResponse:
    try:
        with unit_of_work(session, request=request):
            row_id, ingested_count, skipped_count, evidence = (
                ingest_westmetall_cash_settlement_daily_for_date(
                    session, payload.settlement_date
                )
            )
            if row_id is not None:
                metadata = MarketDataAuditMetadata(
                    provider=SOURCE_WESTMETALL,
                    instrument=SYMBOL_DAILY,
                    actor_sub="service:westmetall_ingest",
                    tier_at_ingest_time=tier_for_provider(SOURCE_WESTMETALL),
                    is_canonical=is_canonical_provider(SOURCE_WESTMETALL, SYMBOL_DAILY),
                    single_date_replay_key=payload.settlement_date,
                )
                mark_audit_success(
                    request,
                    row_id,
                    metadata=metadata.as_metadata_dict(),
                )
    except BulkContentMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except WestmetallLayoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    except CircuitOpenError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return CashSettlementIngestResponse(
        ingested_count=ingested_count,
        skipped_count=skipped_count,
        source=SOURCE_WESTMETALL,
        symbol=SYMBOL_DAILY,
        settlement_date=payload.settlement_date,
        source_url=evidence.source_url,
        html_sha256=evidence.html_sha256,
        fetched_at=evidence.fetched_at,
        is_canonical=is_canonical_provider(SOURCE_WESTMETALL, SYMBOL_DAILY),
    )


@router.post(
    "/aluminum/cash-settlement/ingest-bulk",
    response_model=CashSettlementBulkIngestResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit(RATE_LIMIT_SCRAPING)
def ingest_cash_settlement_bulk(
    payload: CashSettlementBulkIngestRequest,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="cash_settlement_price",
            event_type="market_data_ingested",
        )
    ),
    __: None = Depends(require_service_identity("westmetall_ingest")),
    session: Session = Depends(get_session),
) -> CashSettlementBulkIngestResponse:
    try:
        with unit_of_work(session, request=request):
            inserted_ids, batch_uuid, ingested_count, skipped_count, evidence = (
                ingest_westmetall_cash_settlement_bulk(
                    session,
                    start_date=payload.start_date,
                    end_date=payload.end_date,
                )
            )
            metadata = MarketDataAuditMetadata(
                provider=SOURCE_WESTMETALL,
                instrument=SYMBOL_DAILY,
                actor_sub="service:westmetall_ingest",
                tier_at_ingest_time=tier_for_provider(SOURCE_WESTMETALL),
                is_canonical=is_canonical_provider(SOURCE_WESTMETALL, SYMBOL_DAILY),
                batch_replay_id=str(batch_uuid),
            ).as_metadata_dict()
            if ingested_count > 0:
                metadata["outcome"] = "ingested"
            elif skipped_count > 0:
                metadata["outcome"] = "all_skip"
            else:
                metadata["outcome"] = "empty_range"
            mark_audit_success(request, batch_uuid, metadata=metadata)
    except BulkContentMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except WestmetallLayoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    except CircuitOpenError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return CashSettlementBulkIngestResponse(
        ingested_count=ingested_count,
        skipped_count=skipped_count,
        source=SOURCE_WESTMETALL,
        symbol=SYMBOL_DAILY,
        source_url=evidence.source_url,
        html_sha256=evidence.html_sha256,
        fetched_at=evidence.fetched_at,
        is_canonical=is_canonical_provider(SOURCE_WESTMETALL, SYMBOL_DAILY),
    )
