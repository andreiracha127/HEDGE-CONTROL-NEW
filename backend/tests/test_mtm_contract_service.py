from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

import pytest
from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.contracts import HedgeClassification, HedgeContract, HedgeContractStatus, HedgeLegSide
from app.models.market_data import CashSettlementPrice
from app.models.mtm import MTMObjectType, MTMSnapshot
from app.services.mtm_contract_service import compute_mtm_for_contract
from app.services.mtm_snapshot_service import create_mtm_snapshot_for_contract


def _insert_price(symbol: str, settlement_date: date, price_usd: float) -> None:
    with SessionLocal() as session:
        session.add(
            CashSettlementPrice(
                source="westmetall",
                symbol=symbol,
                settlement_date=settlement_date,
                price_usd=price_usd,
                source_url="https://example.test/source",
                html_sha256="0" * 64,
                fetched_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()


def _insert_contract(quantity_mt: float, entry_price: float, status: HedgeContractStatus) -> uuid.UUID:
    with SessionLocal() as session:
        contract = HedgeContract(
            commodity="LME_AL",
            quantity_mt=quantity_mt,
            fixed_leg_side=HedgeLegSide.buy,
            variable_leg_side=HedgeLegSide.sell,
            classification=HedgeClassification.long,
            fixed_price_value=entry_price,
            fixed_price_unit="USD/MT",
            float_pricing_convention="avg",
            status=status,
        )
        session.add(contract)
        session.commit()
        session.refresh(contract)
        return contract.id


def test_mtm_calculation_active_contract() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=110.0)
    contract_id = _insert_contract(quantity_mt=5.0, entry_price=100.0, status=HedgeContractStatus.active)

    with SessionLocal() as session:
        result = compute_mtm_for_contract(session, contract_id=contract_id, as_of_date=date(2026, 2, 1))
        assert result.object_type.value == MTMObjectType.hedge_contract.value
        assert Decimal(result.quantity_mt) == Decimal("5.0")
        assert result.price_d1 == Decimal("110.0")
        assert result.entry_price == Decimal("100.0")
        assert result.mtm_value == Decimal("50.00")


def test_exclude_cancelled_or_settled_contracts() -> None:
    contract_id = _insert_contract(quantity_mt=5.0, entry_price=100.0, status=HedgeContractStatus.cancelled)
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            compute_mtm_for_contract(session, contract_id=contract_id, as_of_date=date(2026, 2, 1))
        assert exc.value.status_code == 409


def test_missing_d1_price_hard_fails_424() -> None:
    contract_id = _insert_contract(quantity_mt=5.0, entry_price=100.0, status=HedgeContractStatus.active)
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            compute_mtm_for_contract(session, contract_id=contract_id, as_of_date=date(2026, 2, 1))
        assert exc.value.status_code == 424


def test_snapshot_creation_is_idempotent() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=110.0)
    contract_id = _insert_contract(quantity_mt=5.0, entry_price=100.0, status=HedgeContractStatus.active)

    with SessionLocal() as session:
        first = create_mtm_snapshot_for_contract(
            session, contract_id=contract_id, as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )
        second = create_mtm_snapshot_for_contract(
            session, contract_id=contract_id, as_of_date=date(2026, 2, 1), correlation_id="c-2"
        )
        assert first.id == second.id


def test_snapshot_conflict_different_values_409() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=110.0)
    contract_id = _insert_contract(quantity_mt=5.0, entry_price=100.0, status=HedgeContractStatus.active)

    with SessionLocal() as session:
        session.add(
            MTMSnapshot(
                object_type=MTMObjectType.hedge_contract,
                object_id=contract_id,
                as_of_date=date(2026, 2, 1),
                mtm_value=Decimal("999.0"),
                price_d1=Decimal("110.0"),
                entry_price=Decimal("100.0"),
                quantity_mt=Decimal("5.0"),
                correlation_id="c-x",
            )
        )
        session.commit()

    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            create_mtm_snapshot_for_contract(
                session, contract_id=contract_id, as_of_date=date(2026, 2, 1), correlation_id="c-y"
            )
        assert exc.value.status_code == 409
