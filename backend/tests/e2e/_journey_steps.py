"""Reusable journey primitives."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from backend.tests.e2e._personas import as_auditor, as_risk_manager


def _canonical_rfq(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["canonical_id"] = payload["rfq_number"]
    return out


def step_create_rfq(
    trace_id: str,
    supplier_ids: list[str],
    *,
    quantity_mt: str = "5.000000",
    commodity: str = "LME_AL",
) -> dict[str, Any]:
    """Risk manager creates a global-position RFQ and asserts canonical id."""
    with as_risk_manager() as client:
        response = client.post(
            "/rfqs",
            json={
                "intent": "GLOBAL_POSITION",
                "commodity": commodity,
                "quantity_mt": quantity_mt,
                "delivery_window_start": "2026-03-01",
                "delivery_window_end": "2026-03-31",
                "direction": "BUY",
                "order_id": None,
                "invitations": [
                    {"counterparty_id": supplier_id} for supplier_id in supplier_ids
                ],
                "text_en": f"{trace_id} buy {quantity_mt}MT {commodity}",
                "text_pt": f"{trace_id} compra {quantity_mt}MT {commodity}",
            },
        )
        assert response.status_code == 201, response.text
        rfq = _canonical_rfq(response.json())
        assert rfq["canonical_id"].startswith("RFQ-"), rfq
        return rfq


def step_award_quote(
    rfq_id: str,
    counterparty_id: str,
    *,
    price: str = "100.000000",
) -> dict[str, Any]:
    """Submit a quote and award the RFQ, returning contract references."""
    with as_risk_manager() as client:
        quote = client.post(
            f"/rfqs/{rfq_id}/quotes",
            json={
                "rfq_id": rfq_id,
                "counterparty_id": counterparty_id,
                "fixed_price_value": price,
                "fixed_price_unit": "USD/MT",
                "float_pricing_convention": "avg",
                "received_at": datetime(2026, 2, 1, tzinfo=UTC).isoformat(),
            },
        )
        assert quote.status_code == 201, quote.text
        awarded = client.post(
            f"/rfqs/{rfq_id}/actions/award",
            json={},
            headers={"Idempotency-Key": f"e2e-award-{rfq_id}"},
        )
        assert awarded.status_code == 200, awarded.text
        rfq = _canonical_rfq(awarded.json())
        contracts = client.get("/contracts/hedge", params={"limit": 200})
        assert contracts.status_code == 200, contracts.text
        contract_ids = [
            item["id"]
            for item in contracts.json().get("items", [])
            if item.get("rfq_id") == rfq_id
        ]
        rfq["contract_ids"] = contract_ids
        return rfq


def step_link_contract(rfq_id: str) -> dict[str, Any]:
    with as_risk_manager() as client:
        response = client.get("/contracts/hedge", params={"limit": 200})
        assert response.status_code == 200, response.text
        for item in response.json().get("items", []):
            if item.get("rfq_id") == rfq_id:
                return item
    raise AssertionError(f"No hedge contract found for RFQ {rfq_id}")


def step_run_mtm(contract_id: str, *, as_of_date: date | None = None) -> dict[str, Any]:
    effective_date = as_of_date or date.today()
    with as_risk_manager() as client:
        response = client.post(
            "/mtm/snapshots",
            json={
                "object_type": "hedge_contract",
                "object_id": contract_id,
                "as_of_date": effective_date.isoformat(),
                "correlation_id": f"e2e-mtm-{contract_id}",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()


def step_compute_pl(
    contract_id: str,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict[str, Any]:
    start = period_start or date(2026, 3, 1)
    end = period_end or date(2026, 3, 31)
    with as_risk_manager() as client:
        response = client.post(
            "/pl/snapshots",
            json={
                "entity_type": "hedge_contract",
                "entity_id": contract_id,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
            },
        )
        assert response.status_code == 201, response.text
        return response.json()


def step_compute_cashflow_baseline(*, as_of_date: date | None = None) -> dict[str, Any]:
    effective_date = as_of_date or date.today()
    with as_risk_manager() as client:
        response = client.post(
            "/cashflow/baseline/snapshots",
            json={
                "as_of_date": effective_date.isoformat(),
                "correlation_id": f"e2e-cashflow-{effective_date.isoformat()}",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()


def step_read_audit_trail(
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    params = {"limit": 200}
    if entity_type is not None:
        params["entity_type"] = entity_type
    if entity_id is not None:
        params["entity_id"] = entity_id
    with as_auditor() as client:
        response = client.get("/audit/events", params=params)
        assert response.status_code == 200, response.text
        events = response.json().get("events", [])
        for event in events:
            assert event.get("checksum")
            assert event.get("signature")
        return events
