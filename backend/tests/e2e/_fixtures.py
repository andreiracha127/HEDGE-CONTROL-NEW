"""Idempotent seeding helpers for E2E."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.market_data import CashSettlementPrice
from app.services.westmetall_cash_settlement import SOURCE_WESTMETALL, SYMBOL_DAILY
from backend.tests.e2e._personas import as_risk_manager


def trace_id_factory() -> str:
    return f"e2e-{uuid.uuid4().hex[:8]}"


def seed_counterparties(trace_id: str) -> dict[str, str]:
    """Create one counterparty per institutional type and return UUID strings."""
    type_map = {
        "customer": "customer",
        "supplier": "supplier",
        "broker": "broker",
        "bank": "bank_br",
    }
    out: dict[str, str] = {}
    with as_risk_manager() as client:
        existing = client.get("/counterparties", params={"limit": 200})
        assert existing.status_code == 200, existing.text
        by_tax_id = {
            item.get("tax_id"): item
            for item in existing.json().get("items", [])
            if item.get("tax_id")
        }
        for key, counterparty_type in type_map.items():
            tax_id = f"{trace_id}-{key}"
            current = by_tax_id.get(tax_id)
            if current is not None:
                out[key] = current["id"]
                continue
            created = client.post(
                "/counterparties",
                json={
                    "type": counterparty_type,
                    "name": f"{trace_id}-{key}-CP",
                    "country": "BRA",
                    "city": "Sao Paulo",
                    "tax_id": tax_id,
                    "whatsapp_phone": "+5511999990000",
                    "sanctions_status": "clear",
                    "risk_rating": "low",
                },
            )
            assert created.status_code == 201, created.text
            cp = created.json()
            out[key] = cp["id"]
            approved = client.post(
                f"/counterparties/{cp['id']}/kyc-status",
                json={
                    "new_status": "approved",
                    "reason": "E2E institutional seed approval",
                },
            )
            assert approved.status_code == 200, approved.text
    return out


def seed_westmetall_prices(
    trace_id: str,
    start: date,
    end: date,
    *,
    raw_floats: bool = False,
) -> int:
    """Seed deterministic Westmetall cash settlement rows across [start, end]."""
    if raw_floats:
        raise TypeError(
            "Decimal string seed values are required; raw float inputs are rejected."
        )
    count = 0
    session = SessionLocal()
    try:
        d = start
        while d <= end:
            exists = (
                session.query(CashSettlementPrice)
                .filter(
                    CashSettlementPrice.source == SOURCE_WESTMETALL,
                    CashSettlementPrice.symbol == SYMBOL_DAILY,
                    CashSettlementPrice.settlement_date == d,
                )
                .one_or_none()
            )
            if exists is None:
                session.add(
                    CashSettlementPrice(
                        source=SOURCE_WESTMETALL,
                        symbol=SYMBOL_DAILY,
                        settlement_date=d,
                        price_usd=Decimal("2450.000000"),
                        is_canonical=True,
                        source_url=f"e2e://{trace_id}/westmetall/{d.isoformat()}",
                        html_sha256=(trace_id + d.isoformat()).encode().hex()[:64],
                        fetched_at=datetime.now(timezone.utc),
                    )
                )
            count += 1
            d += timedelta(days=1)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return count


def seed_lme_calendar(start: date, end: date) -> None:
    """Validate a requested date range for systems that derive the calendar."""
    if end < start:
        raise ValueError("end must be on or after start")
