"""Unit tests for mtm_snapshot_service — snapshot CRUD, idempotency, get."""

from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

import pytest
from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.market_data import CashSettlementPrice
from app.models.mtm import MTMObjectType, MTMSnapshot
from app.models.orders import Order, OrderPricingConvention, OrderType, PriceType
from app.services.mtm_snapshot_service import (
    create_mtm_snapshot_for_contract,
    create_mtm_snapshot_for_order,
    get_mtm_snapshot,
)


# ── helpers ──────────────────────────────────────────────────────────────


def _insert_price(symbol: str, settlement_date: date, price_usd: Decimal | str) -> None:
    with SessionLocal() as session:
        session.add(
            CashSettlementPrice(
                source="westmetall",
                symbol=symbol,
                settlement_date=settlement_date,
                price_usd=Decimal(str(price_usd)),
                source_url="https://example.test/source",
                html_sha256="0" * 64,
                fetched_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()


def _insert_contract(
    quantity_mt: float = 5.0,
    entry_price: float = 100.0,
    status: HedgeContractStatus = HedgeContractStatus.active,
) -> uuid.UUID:
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


def _create_variable_sales_order(client, avg_entry_price: float = 100.0) -> str:
    response = client.post(
        "/orders/sales",
        json={
            "price_type": "variable",
            "quantity_mt": 5.0,
            "pricing_convention": "AVG",
            "avg_entry_price": avg_entry_price,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _insert_variable_order(
    commodity: str, quantity_mt: float = 5.0, avg_entry_price: float = 100.0
) -> uuid.UUID:
    with SessionLocal() as session:
        order = Order(
            order_type=OrderType.sales,
            price_type=PriceType.variable,
            commodity=commodity,
            quantity_mt=quantity_mt,
            pricing_convention=OrderPricingConvention.avg,
            avg_entry_price=avg_entry_price,
        )
        session.add(order)
        session.commit()
        session.refresh(order)
        return order.id


# ── create_mtm_snapshot_for_contract ─────────────────────────────────────


def test_snapshot_contract_creates_record() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    cid = _insert_contract()
    with SessionLocal() as session:
        snap = create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )
        assert snap.object_type == MTMObjectType.hedge_contract
        assert snap.object_id == cid
        assert snap.as_of_date == date(2026, 2, 1)
        assert snap.correlation_id == "c-1"


def test_mtm_snapshot_persists_price_provenance_quadruple() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    cid = _insert_contract()
    with SessionLocal() as session:
        snap = create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 2), correlation_id="c-1"
        )
        assert snap.price_source == "westmetall"
        assert snap.price_symbol == "LME_ALU_CASH_SETTLEMENT_DAILY"
        assert snap.price_settlement_date == date(2026, 1, 30)
        assert snap.inputs_hash is not None
        assert len(snap.inputs_hash) == 64


def test_mtm_snapshot_inputs_hash_is_deterministic_over_same_inputs() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    cid = _insert_contract()
    with SessionLocal() as session:
        first = create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 2), correlation_id="c-1"
        )
        first_hash = first.inputs_hash
        second = create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 2), correlation_id="c-2"
        )
        assert second.inputs_hash == first_hash


def test_mtm_snapshot_persists_price_symbol_distinguishing_multi_commodity_same_source_same_date() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    _insert_price("LME_CU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 9300.0)
    cid = _insert_contract()
    with SessionLocal() as session:
        snap = create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 2), correlation_id="c-1"
        )
        assert snap.price_symbol == "LME_ALU_CASH_SETTLEMENT_DAILY"


def test_mtm_snapshot_legacy_null_provenance_does_not_violate_check() -> None:
    cid = _insert_contract()
    with SessionLocal() as session:
        session.add(
            MTMSnapshot(
                object_type=MTMObjectType.hedge_contract,
                object_id=cid,
                as_of_date=date(2026, 2, 1),
                mtm_value=Decimal("1"),
                price_d1=Decimal("2"),
                entry_price=Decimal("3"),
                quantity_mt=Decimal("4"),
                correlation_id="legacy",
            )
        )
        session.commit()


def test_snapshot_contract_idempotent_same_values() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    cid = _insert_contract()
    with SessionLocal() as session:
        first = create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )
        second = create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 1), correlation_id="c-2"
        )
        assert first.id == second.id


def test_snapshot_contract_legacy_null_provenance_idempotent_when_values_match() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    cid = _insert_contract(quantity_mt=Decimal("10"), entry_price=Decimal("100"))
    with SessionLocal() as session:
        legacy = MTMSnapshot(
            object_type=MTMObjectType.hedge_contract,
            object_id=cid,
            as_of_date=date(2026, 2, 1),
            mtm_value=Decimal("100.00"),
            price_d1=Decimal("110.0"),
            entry_price=Decimal("100.0"),
            quantity_mt=Decimal("10.0"),
            correlation_id="legacy",
        )
        session.add(legacy)
        session.commit()
        session.refresh(legacy)

        replay = create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 1), correlation_id="c-2"
        )
        assert replay.id == legacy.id


def test_snapshot_contract_conflict_409() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    cid = _insert_contract()
    with SessionLocal() as session:
        session.add(
            MTMSnapshot(
                object_type=MTMObjectType.hedge_contract,
                object_id=cid,
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
                session,
                contract_id=cid,
                as_of_date=date(2026, 2, 1),
                correlation_id="c-y",
            )
        assert exc.value.status_code == 409


def test_snapshot_contract_values_correct() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    cid = _insert_contract(quantity_mt=10.0, entry_price=100.0)
    with SessionLocal() as session:
        snap = create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )
        assert snap.entry_price == Decimal("100.0")
        assert snap.price_d1 == Decimal("110.0")
        assert snap.quantity_mt == Decimal("10.0")
        # MTM = (110 - 100) × 10 = 100
        assert snap.mtm_value == Decimal("100.00")


# ── create_mtm_snapshot_for_order ────────────────────────────────────────


def test_snapshot_order_creates_record(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    oid = _create_variable_sales_order(client)
    with SessionLocal() as session:
        snap = create_mtm_snapshot_for_order(
            session,
            order_id=uuid.UUID(oid),
            as_of_date=date(2026, 2, 1),
            correlation_id="o-1",
        )
        assert snap.object_type == MTMObjectType.order
        assert snap.object_id == uuid.UUID(oid)
        assert snap.correlation_id == "o-1"


def test_create_mtm_snapshot_for_order_persists_commodity_resolved_symbol() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 2400.0)
    _insert_price("LME_CU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 9500.0)
    oid = _insert_variable_order(
        commodity="COPPER", quantity_mt=10.0, avg_entry_price=9000.0
    )

    with SessionLocal() as session:
        snap = create_mtm_snapshot_for_order(
            session,
            order_id=oid,
            as_of_date=date(2026, 2, 1),
            correlation_id="o-cu",
        )

    assert snap.price_symbol == "LME_CU_CASH_SETTLEMENT_DAILY"
    assert snap.price_source == "westmetall"
    assert snap.price_settlement_date == date(2026, 1, 30)


def test_snapshot_order_idempotent(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    oid = _create_variable_sales_order(client)
    with SessionLocal() as session:
        first = create_mtm_snapshot_for_order(
            session,
            order_id=uuid.UUID(oid),
            as_of_date=date(2026, 2, 1),
            correlation_id="o-1",
        )
        second = create_mtm_snapshot_for_order(
            session,
            order_id=uuid.UUID(oid),
            as_of_date=date(2026, 2, 1),
            correlation_id="o-2",
        )
        assert first.id == second.id


def test_snapshot_order_legacy_null_provenance_idempotent_when_values_match(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    oid = uuid.UUID(_create_variable_sales_order(client, avg_entry_price=100.0))
    with SessionLocal() as session:
        legacy = MTMSnapshot(
            object_type=MTMObjectType.order,
            object_id=oid,
            as_of_date=date(2026, 2, 1),
            mtm_value=Decimal("50.00"),
            price_d1=Decimal("110.0"),
            entry_price=Decimal("100.0"),
            quantity_mt=Decimal("5.0"),
            correlation_id="legacy",
        )
        session.add(legacy)
        session.commit()
        session.refresh(legacy)

        replay = create_mtm_snapshot_for_order(
            session,
            order_id=oid,
            as_of_date=date(2026, 2, 1),
            correlation_id="o-2",
        )
        assert replay.id == legacy.id


def test_snapshot_order_conflict_409(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    oid = _create_variable_sales_order(client)
    with SessionLocal() as session:
        session.add(
            MTMSnapshot(
                object_type=MTMObjectType.order,
                object_id=uuid.UUID(oid),
                as_of_date=date(2026, 2, 1),
                mtm_value=Decimal("999.0"),
                price_d1=Decimal("110.0"),
                entry_price=Decimal("100.0"),
                quantity_mt=Decimal("5.0"),
                correlation_id="o-x",
            )
        )
        session.commit()
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            create_mtm_snapshot_for_order(
                session,
                order_id=uuid.UUID(oid),
                as_of_date=date(2026, 2, 1),
                correlation_id="o-y",
            )
        assert exc.value.status_code == 409


# ── get_mtm_snapshot ─────────────────────────────────────────────────────


def test_get_mtm_snapshot_returns_existing() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    cid = _insert_contract()
    with SessionLocal() as session:
        created = create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )
        fetched = get_mtm_snapshot(
            session,
            object_type=MTMObjectType.hedge_contract,
            object_id=cid,
            as_of_date=date(2026, 2, 1),
        )
        assert fetched.id == created.id
        assert fetched.mtm_value == created.mtm_value


def test_get_mtm_snapshot_not_found_404() -> None:
    fake_id = uuid.uuid4()
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            get_mtm_snapshot(
                session,
                object_type=MTMObjectType.hedge_contract,
                object_id=fake_id,
                as_of_date=date(2026, 2, 1),
            )
        assert exc.value.status_code == 404


def test_get_mtm_snapshot_wrong_date_404() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    cid = _insert_contract()
    with SessionLocal() as session:
        create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )
        with pytest.raises(HTTPException) as exc:
            get_mtm_snapshot(
                session,
                object_type=MTMObjectType.hedge_contract,
                object_id=cid,
                as_of_date=date(2026, 3, 1),  # different date
            )
        assert exc.value.status_code == 404


def test_get_mtm_snapshot_wrong_type_404() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", date(2026, 1, 30), 110.0)
    cid = _insert_contract()
    with SessionLocal() as session:
        create_mtm_snapshot_for_contract(
            session, contract_id=cid, as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )
        with pytest.raises(HTTPException) as exc:
            get_mtm_snapshot(
                session,
                object_type=MTMObjectType.order,  # wrong type
                object_id=cid,
                as_of_date=date(2026, 2, 1),
            )
        assert exc.value.status_code == 404
