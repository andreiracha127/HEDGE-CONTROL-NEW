from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID
from uuid import uuid4

from fastapi import status

from app.core.database import SessionLocal
from app.models.cashflow import CashFlowLedgerEntry
from app.models.contracts import (
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
    VALID_STATUS_TRANSITIONS,
)
from app.models.market_data import CashSettlementPrice
from app.services.contract_service import GENERIC_STATUS_TRANSITIONS


SETTLEMENT_DETAIL = (
    "Settlement transitions must go through POST "
    "/cashflow/contracts/{contract_id}/settle"
)


def _create_contract(client) -> str:
    response = client.post(
        "/contracts/hedge",
        json={
            "commodity": "LME_AL",
            "quantity_mt": 12.0,
            "legs": [
                {"side": "buy", "price_type": "fixed"},
                {"side": "sell", "price_type": "variable"},
            ],
            "fixed_price_value": "100",
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()["id"]


def _set_contract_status(contract_id: str, target: HedgeContractStatus) -> None:
    with SessionLocal() as session:
        contract = session.get(HedgeContract, UUID(contract_id))
        assert contract is not None
        contract.status = target
        session.commit()


def _contract_status(contract_id: str) -> HedgeContractStatus:
    with SessionLocal() as session:
        contract = session.get(HedgeContract, UUID(contract_id))
        assert contract is not None
        return contract.status


def _insert_price() -> None:
    with SessionLocal() as session:
        session.add(
            CashSettlementPrice(
                source="westmetall",
                symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                settlement_date=date(2026, 1, 14),
                price_usd=Decimal("110"),
                source_url="https://example.test/source",
                html_sha256="0" * 64,
                fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()


def _settlement_payload() -> dict:
    return {
        "source_event_id": str(uuid4()),
        "cashflow_date": date(2026, 1, 15).isoformat(),
        "legs": [
            {"leg_id": "FIXED", "direction": "OUT", "amount": "1200"},
            {"leg_id": "FLOAT", "direction": "IN", "amount": "1320"},
        ],
    }


def test_patch_active_to_settled_is_rejected(client) -> None:
    contract_id = _create_contract(client)

    response = client.patch(
        f"/contracts/hedge/{contract_id}/status", json={"status": "settled"}
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"] == SETTLEMENT_DETAIL
    assert _contract_status(contract_id) == HedgeContractStatus.active


def test_patch_active_to_partially_settled_is_rejected(client) -> None:
    contract_id = _create_contract(client)

    response = client.patch(
        f"/contracts/hedge/{contract_id}/status",
        json={"status": "partially_settled"},
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"] == SETTLEMENT_DETAIL
    assert _contract_status(contract_id) == HedgeContractStatus.active


def test_patch_partially_settled_to_settled_is_rejected(client) -> None:
    contract_id = _create_contract(client)
    _set_contract_status(contract_id, HedgeContractStatus.partially_settled)

    response = client.patch(
        f"/contracts/hedge/{contract_id}/status", json={"status": "settled"}
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"] == SETTLEMENT_DETAIL
    assert _contract_status(contract_id) == HedgeContractStatus.partially_settled


def test_patch_active_to_cancelled_still_succeeds(client) -> None:
    contract_id = _create_contract(client)

    response = client.patch(
        f"/contracts/hedge/{contract_id}/status", json={"status": "cancelled"}
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "cancelled"


def test_patch_partially_settled_to_cancelled_still_succeeds(client) -> None:
    contract_id = _create_contract(client)
    _set_contract_status(contract_id, HedgeContractStatus.partially_settled)

    response = client.patch(
        f"/contracts/hedge/{contract_id}/status", json={"status": "cancelled"}
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "cancelled"


def test_canonical_settlement_path_sets_status_and_writes_ledger(client) -> None:
    _insert_price()
    contract_id = _create_contract(client)

    response = client.post(
        f"/cashflow/contracts/{contract_id}/settle", json=_settlement_payload()
    )

    assert response.status_code == status.HTTP_201_CREATED, response.text
    assert _contract_status(contract_id) == HedgeContractStatus.settled
    with SessionLocal() as session:
        assert session.query(CashFlowLedgerEntry).count() == 2


def test_generic_transitions_exclude_settlement_statuses() -> None:
    assert (
        HedgeContractStatus.settled
        not in GENERIC_STATUS_TRANSITIONS[HedgeContractStatus.active]
    )
    assert (
        HedgeContractStatus.partially_settled
        not in GENERIC_STATUS_TRANSITIONS[HedgeContractStatus.active]
    )
    assert (
        HedgeContractStatus.settled
        not in GENERIC_STATUS_TRANSITIONS[HedgeContractStatus.partially_settled]
    )


def test_model_valid_transitions_remain_unchanged() -> None:
    assert VALID_STATUS_TRANSITIONS == {
        HedgeContractStatus.active: {
            HedgeContractStatus.partially_settled,
            HedgeContractStatus.settled,
            HedgeContractStatus.cancelled,
        },
        HedgeContractStatus.partially_settled: {
            HedgeContractStatus.settled,
            HedgeContractStatus.cancelled,
        },
        HedgeContractStatus.settled: set(),
        HedgeContractStatus.cancelled: set(),
    }
