"""Scenario isolation checks."""

from __future__ import annotations

from app.core.database import SessionLocal
from app.models.contracts import HedgeContract
from backend.tests.e2e._personas import as_auditor, as_risk_manager, as_service, as_trader


def test_scenario_route_requires_risk_manager() -> None:
    payload = {
        "base_date": "2026-03-31",
        "shock_type": "price",
        "shock_value": "1.000000",
    }
    for persona in (as_trader, as_auditor):
        with persona() as client:
            response = client.post("/scenario/what-if/run", json=payload)
            assert response.status_code == 403, response.text
    with as_service("service:cashflow_pipeline") as client:
        response = client.post("/scenario/what-if/run", json=payload)
        assert response.status_code == 403, response.text
    with as_risk_manager() as client:
        response = client.post("/scenario/what-if/run", json=payload)
        assert response.status_code in (200, 422, 424), response.text


def test_awarded_journey_does_not_create_extra_contracts_after_read(
    awarded_rfq,
) -> None:
    session = SessionLocal()
    try:
        before = session.query(HedgeContract).count()
    finally:
        session.close()

    assert awarded_rfq["contract_ids"]

    session = SessionLocal()
    try:
        after = session.query(HedgeContract).count()
    finally:
        session.close()
    assert after == before
