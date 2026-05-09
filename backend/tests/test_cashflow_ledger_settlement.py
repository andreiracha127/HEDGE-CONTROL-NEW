from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status

from app.core.database import SessionLocal
from app.models.cashflow import CashFlowLedgerEntry
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.market_data import CashSettlementPrice
from app.schemas.cashflow import HedgeContractSettlementCreate
from app.services.cashflow_ledger_service import ingest_hedge_contract_settlement
from app.services.pl_calculation_service import compute_pl


def _create_hedge_contract(client) -> str:
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
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["id"]


def _insert_price(symbol: str, settlement_date: date, price_usd: str) -> None:
    with SessionLocal() as session:
        session.add(
            CashSettlementPrice(
                source="westmetall",
                symbol=symbol,
                settlement_date=settlement_date,
                price_usd=Decimal(price_usd),
                source_url="https://example.test/source",
                html_sha256="0" * 64,
                fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()


def _settlement_payload(source_event_id: str, amount_fixed: str = "1200", amount_float: str = "1320") -> dict:
    return {
        "source_event_id": source_event_id,
        "cashflow_date": date(2026, 1, 15).isoformat(),
        "legs": [
            {"leg_id": "FIXED", "direction": "OUT", "amount": amount_fixed},
            {"leg_id": "FLOAT", "direction": "IN", "amount": amount_float},
        ],
    }


def _insert_contract(
    *,
    quantity_mt: Decimal = Decimal("10"),
    fixed_price: Decimal = Decimal("100"),
    fixed_side: HedgeLegSide = HedgeLegSide.buy,
    variable_side: HedgeLegSide = HedgeLegSide.sell,
) -> HedgeContract:
    with SessionLocal() as session:
        contract = HedgeContract(
            commodity="LME_AL",
            quantity_mt=quantity_mt,
            fixed_leg_side=fixed_side,
            variable_leg_side=variable_side,
            classification=(
                HedgeClassification.long
                if fixed_side == HedgeLegSide.buy
                else HedgeClassification.short
            ),
            fixed_price_value=fixed_price,
            fixed_price_unit="USD/MT",
            float_pricing_convention="avg",
            status=HedgeContractStatus.active,
        )
        session.add(contract)
        session.commit()
        session.refresh(contract)
        return contract


def test_settlement_creates_event_and_ledger_entries_and_sets_status(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "110")
    contract_id = _create_hedge_contract(client)
    payload = _settlement_payload(str(uuid4()))
    response = client.post(f"/cashflow/contracts/{contract_id}/settle", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["event"]["hedge_contract_id"] == contract_id
    assert data["event"]["cashflow_date"] == payload["cashflow_date"]
    assert len(data["ledger_entries"]) == 2

    contract_response = client.get(f"/contracts/hedge/{contract_id}")
    assert contract_response.status_code == status.HTTP_200_OK
    assert contract_response.json()["status"] == "settled"


def test_settlement_is_idempotent_with_same_payload(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "110")
    contract_id = _create_hedge_contract(client)
    source_event_id = str(uuid4())
    payload = _settlement_payload(source_event_id)

    first = client.post(f"/cashflow/contracts/{contract_id}/settle", json=payload)
    assert first.status_code == status.HTTP_201_CREATED

    second = client.post(f"/cashflow/contracts/{contract_id}/settle", json=payload)
    assert second.status_code == status.HTTP_201_CREATED
    assert second.json()["event"]["id"] == source_event_id


def test_settlement_conflicts_on_different_payload(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "110")
    contract_id = _create_hedge_contract(client)
    source_event_id = str(uuid4())
    payload = _settlement_payload(source_event_id)

    first = client.post(f"/cashflow/contracts/{contract_id}/settle", json=payload)
    assert first.status_code == status.HTTP_201_CREATED

    updated_payload = _settlement_payload(source_event_id, amount_fixed="150")
    second = client.post(f"/cashflow/contracts/{contract_id}/settle", json=updated_payload)
    assert second.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_settlement_rejected_for_non_active_contract(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "110")
    contract_id = _create_hedge_contract(client)
    payload = _settlement_payload(str(uuid4()))
    first = client.post(f"/cashflow/contracts/{contract_id}/settle", json=payload)
    assert first.status_code == status.HTTP_201_CREATED

    second = client.post(f"/cashflow/contracts/{contract_id}/settle", json=_settlement_payload(str(uuid4())))
    assert second.status_code == status.HTTP_409_CONFLICT


def test_currency_must_be_usd(client) -> None:
    contract_id = _create_hedge_contract(client)
    payload = _settlement_payload(str(uuid4()))
    payload["currency"] = "BRL"
    response = client.post(f"/cashflow/contracts/{contract_id}/settle", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_amount_must_be_positive(client) -> None:
    contract_id = _create_hedge_contract(client)
    payload = _settlement_payload(str(uuid4()), amount_fixed="0")
    response = client.post(f"/cashflow/contracts/{contract_id}/settle", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_settlement_amount_derived_server_side_not_from_payload() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "110")
    contract = _insert_contract(quantity_mt=Decimal("10"), fixed_price=Decimal("100"))
    payload = HedgeContractSettlementCreate(
        source_event_id=uuid4(),
        cashflow_date=date(2026, 1, 15),
        legs=[
            {"leg_id": "FIXED", "direction": "OUT", "amount": Decimal("1000.000000")},
            {"leg_id": "FLOAT", "direction": "IN", "amount": Decimal("1100.000000")},
        ],
    )

    with SessionLocal() as session:
        _, entries = ingest_hedge_contract_settlement(session, contract.id, payload)
        by_leg = {entry.leg_id: entry for entry in entries}
        assert by_leg["FIXED"].amount == Decimal("1000.000000")
        assert by_leg["FLOAT"].amount == Decimal("1100.000000")
        assert by_leg["FIXED"].price_source is None
        assert by_leg["FLOAT"].price_source == "westmetall"
        assert by_leg["FLOAT"].price_symbol == "LME_ALU_CASH_SETTLEMENT_DAILY"
        assert by_leg["FLOAT"].price_settlement_date == date(2026, 1, 14)
        assert by_leg["FLOAT"].price_value == Decimal("110.000000")


def test_settlement_payload_amount_mismatch_raises_422() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "110")
    contract = _insert_contract()
    payload = HedgeContractSettlementCreate(
        source_event_id=uuid4(),
        cashflow_date=date(2026, 1, 15),
        legs=[
            {"leg_id": "FIXED", "direction": "OUT", "amount": Decimal("1000.000000")},
            {"leg_id": "FLOAT", "direction": "IN", "amount": Decimal("9999.000000")},
        ],
    )

    with SessionLocal() as session:
        with pytest.raises(Exception) as exc:
            ingest_hedge_contract_settlement(session, contract.id, payload)
        assert getattr(exc.value, "status_code", None) == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "amount mismatch" in str(getattr(exc.value, "detail", ""))


def test_settlement_payload_leg_direction_mismatch_raises_422() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "110")
    contract = _insert_contract()
    payload = HedgeContractSettlementCreate(
        source_event_id=uuid4(),
        cashflow_date=date(2026, 1, 15),
        legs=[
            {"leg_id": "FIXED", "direction": "IN", "amount": Decimal("1000.000000")},
            {"leg_id": "FLOAT", "direction": "IN", "amount": Decimal("1100.000000")},
        ],
    )

    with SessionLocal() as session:
        with pytest.raises(Exception) as exc:
            ingest_hedge_contract_settlement(session, contract.id, payload)
        assert getattr(exc.value, "status_code", None) == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "direction mismatch" in str(getattr(exc.value, "detail", ""))


def test_settlement_float_direction_derived_from_variable_leg_side_not_fixed_inverse() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "110")
    contract = _insert_contract(fixed_side=HedgeLegSide.buy, variable_side=HedgeLegSide.buy)
    payload = HedgeContractSettlementCreate(
        source_event_id=uuid4(),
        cashflow_date=date(2026, 1, 15),
        legs=[
            {"leg_id": "FIXED", "direction": "OUT", "amount": Decimal("1000.000000")},
            {"leg_id": "FLOAT", "direction": "OUT", "amount": Decimal("1100.000000")},
        ],
    )

    with SessionLocal() as session:
        _, entries = ingest_hedge_contract_settlement(session, contract.id, payload)
        float_entry = next(entry for entry in entries if entry.leg_id == "FLOAT")
        assert float_entry.direction == "OUT"


def test_settlement_compute_pl_realized_long_side() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "110")
    contract = _insert_contract(fixed_side=HedgeLegSide.buy, variable_side=HedgeLegSide.sell)
    payload = HedgeContractSettlementCreate(
        source_event_id=uuid4(),
        cashflow_date=date(2026, 1, 15),
        legs=[
            {"leg_id": "FIXED", "direction": "OUT", "amount": Decimal("1000.000000")},
            {"leg_id": "FLOAT", "direction": "IN", "amount": Decimal("1100.000000")},
        ],
    )
    with SessionLocal() as session:
        ingest_hedge_contract_settlement(session, contract.id, payload)
        result = compute_pl(session, "hedge_contract", contract.id, date(2026, 1, 1), date(2026, 1, 31))
        assert result.realized_pl == Decimal("100.000000")


def test_settlement_compute_pl_realized_short_side() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "110")
    contract = _insert_contract(fixed_side=HedgeLegSide.sell, variable_side=HedgeLegSide.buy)
    payload = HedgeContractSettlementCreate(
        source_event_id=uuid4(),
        cashflow_date=date(2026, 1, 15),
        legs=[
            {"leg_id": "FIXED", "direction": "IN", "amount": Decimal("1000.000000")},
            {"leg_id": "FLOAT", "direction": "OUT", "amount": Decimal("1100.000000")},
        ],
    )
    with SessionLocal() as session:
        ingest_hedge_contract_settlement(session, contract.id, payload)
        result = compute_pl(session, "hedge_contract", contract.id, date(2026, 1, 1), date(2026, 1, 31))
        assert result.realized_pl == Decimal("-100.000000")


def test_ledger_idempotency_no_op_on_fixed_leg_with_null_provenance() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "110")
    contract = _insert_contract()
    source_event_id = uuid4()
    payload = HedgeContractSettlementCreate(
        source_event_id=source_event_id,
        cashflow_date=date(2026, 1, 15),
        legs=[
            {"leg_id": "FIXED", "direction": "OUT", "amount": Decimal("1000.000000")},
            {"leg_id": "FLOAT", "direction": "IN", "amount": Decimal("1100.000000")},
        ],
    )
    with SessionLocal() as session:
        _, first_entries = ingest_hedge_contract_settlement(session, contract.id, payload)
        _, second_entries = ingest_hedge_contract_settlement(session, contract.id, payload)
        assert {entry.id for entry in first_entries} == {entry.id for entry in second_entries}
        fixed_entry = next(entry for entry in second_entries if entry.leg_id == "FIXED")
        assert fixed_entry.price_value is None


def test_settlement_amount_quantized_to_ledger_scale() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 14), "2585.123457")
    contract = _insert_contract(quantity_mt=Decimal("10.500000"), fixed_price=Decimal("100"))
    payload = HedgeContractSettlementCreate(
        source_event_id=uuid4(),
        cashflow_date=date(2026, 1, 15),
        legs=[
            {"leg_id": "FIXED", "direction": "OUT", "amount": Decimal("1050.000000")},
            {"leg_id": "FLOAT", "direction": "IN", "amount": Decimal("27143.796298")},
        ],
    )

    with SessionLocal() as session:
        _, entries = ingest_hedge_contract_settlement(session, contract.id, payload)
        float_entry = next(entry for entry in entries if entry.leg_id == "FLOAT")
        assert float_entry.amount == Decimal("27143.796298")
        stored = session.get(CashFlowLedgerEntry, float_entry.id)
        assert stored.amount == Decimal("27143.796298")
