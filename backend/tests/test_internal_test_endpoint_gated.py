"""The /internal/test/cleanup endpoint is dual-gated by env and identity."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.auth import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, get_current_user
from app.core.database import SessionLocal
from app.main import app
from app.models.counterparty import (
    Counterparty,
    CounterpartyType,
    KycStatus,
    RiskRating,
    SanctionsStatus,
)
from app.models.market_data import CashSettlementPrice
from app.models.rfqs import RFQ, RFQDirection, RFQIntent, RFQState


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _post_cleanup(trace_id: str = "x"):
    client = TestClient(app)
    client.cookies.set(CSRF_COOKIE_NAME, "test-csrf-token")
    return client.post(
        "/internal/test/cleanup",
        json={"trace_id": trace_id},
        headers={CSRF_HEADER_NAME: "test-csrf-token"},
    )


def _internal_test_routes_for_env(app_env: str) -> list[str]:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": app_env,
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "AUDIT_SIGNING_KEY": "test-signing-key-for-audit-hmac",
            "SCHEDULER_DISABLED": "1",
            "CLERK_FAPI_HOST": "clerk.test",
            "CLERK_AUDIENCE": "hedge-control",
            "SERVICE_JWT_SIGNING_KEY": "x" * 64,
            "SERVICE_JWT_PUBLIC_KEY": "x" * 64,
            "BACKEND_SERVICE_ISSUER": "https://svc.test",
            "BACKEND_SERVICE_AUDIENCE": "hedge-control",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from app.main import app; "
                "print(json.dumps([getattr(r, 'path', '') for r in app.routes "
                "if '/internal/test' in getattr(r, 'path', '')]))"
            ),
        ],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_cleanup_present_when_test_env_and_correct_identity() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "service:e2e_cleanup",
        "roles": [],
    }
    try:
        response = _post_cleanup("nonexistent")
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), dict)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_cleanup_deletes_trace_namespaced_seed_artifacts() -> None:
    trace_id = "e2e-cleanup-test"
    session = SessionLocal()
    try:
        session.add(
            Counterparty(
                type=CounterpartyType.supplier,
                name=f"{trace_id}-supplier-CP",
                tax_id=f"{trace_id}-supplier",
                country="BRA",
                kyc_status=KycStatus.approved,
                sanctions_status=SanctionsStatus.clear,
                risk_rating=RiskRating.low,
            )
        )
        session.add(
            RFQ(
                rfq_number="RFQ-E2E-CLEANUP-000001",
                intent=RFQIntent.global_position,
                commodity="LME_AL",
                quantity_mt=Decimal("5.000000"),
                delivery_window_start=date(2026, 3, 1),
                delivery_window_end=date(2026, 3, 31),
                direction=RFQDirection.buy,
                commercial_active_mt=Decimal("0.000000"),
                commercial_passive_mt=Decimal("0.000000"),
                commercial_net_mt=Decimal("0.000000"),
                commercial_reduction_applied_mt=Decimal("0.000000"),
                exposure_snapshot_timestamp=datetime.now(timezone.utc),
                state=RFQState.sent,
                text_en=f"{trace_id} buy 5MT LME_AL",
            )
        )
        session.add(
            CashSettlementPrice(
                source="westmetall",
                symbol="aluminum_cash_settlement_daily",
                settlement_date=date(2026, 3, 1),
                price_usd=Decimal("2450.000000"),
                is_canonical=True,
                source_url=f"e2e://{trace_id}/westmetall/2026-03-01",
                html_sha256=("x" * 64),
                fetched_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    finally:
        session.close()

    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "service:e2e_cleanup",
        "roles": [],
    }
    try:
        response = _post_cleanup(trace_id)
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counterparties"] == 1
    assert body["rfqs"] == 1
    assert body["cash_settlement_prices"] == 1


def test_cleanup_rejects_unauthenticated() -> None:
    response = _post_cleanup()
    assert response.status_code in (401, 403), response.text


def test_cleanup_rejects_wrong_service_identity() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "service:westmetall_ingest",
        "roles": [],
    }
    try:
        response = _post_cleanup()
        assert response.status_code == 403, response.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_cleanup_rejects_human_role_even_auditor() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "real-auditor",
        "roles": ["auditor"],
    }
    try:
        response = _post_cleanup()
        assert response.status_code == 403, response.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_cleanup_absent_when_production_env() -> None:
    assert _internal_test_routes_for_env("production") == []


def test_cleanup_absent_when_staging_env() -> None:
    assert _internal_test_routes_for_env("staging") == []
