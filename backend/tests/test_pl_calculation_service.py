from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from app.core.database import SessionLocal
from app.models.contracts import HedgeClassification, HedgeContract, HedgeContractStatus, HedgeLegSide
from app.models.market_data import CashSettlementPrice
from app.models.cashflow import CashFlowLedgerEntry
from app.services.cashflow_ledger_service import ingest_hedge_contract_settlement
from app.schemas.cashflow import HedgeContractSettlementCreate
from app.services.pl_calculation_service import compute_pl


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


def _insert_contract(quantity_mt: float, entry_price: float, status: HedgeContractStatus) -> HedgeContract:
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
        return contract


def _settlement_payload(source_event_id: str) -> HedgeContractSettlementCreate:
    return HedgeContractSettlementCreate(
        source_event_id=source_event_id,
        cashflow_date=date(2026, 1, 15),
        legs=[
            {"leg_id": "FIXED", "direction": "OUT", "amount": Decimal("500.000000")},
            {"leg_id": "FLOAT", "direction": "IN", "amount": Decimal("550.000000")},
        ],
    )


def _insert_realized_ledger_entries(contract_id) -> None:
    source_event_id = uuid4()
    with SessionLocal() as session:
        session.add_all(
            [
                CashFlowLedgerEntry(
                    hedge_contract_id=contract_id,
                    source_event_type="HEDGE_CONTRACT_SETTLED",
                    source_event_id=source_event_id,
                    leg_id="FIXED",
                    cashflow_date=date(2026, 1, 15),
                    currency="USD",
                    direction="OUT",
                    amount=Decimal("500.000000"),
                ),
                CashFlowLedgerEntry(
                    hedge_contract_id=contract_id,
                    source_event_type="HEDGE_CONTRACT_SETTLED",
                    source_event_id=source_event_id,
                    leg_id="FLOAT",
                    cashflow_date=date(2026, 1, 15),
                    currency="USD",
                    direction="IN",
                    amount=Decimal("550.000000"),
                    price_source="westmetall",
                    price_symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                    price_settlement_date=date(2026, 1, 14),
                    price_value=Decimal("110.000000"),
                ),
            ]
        )
        session.commit()


def test_realized_pl_from_ledger() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 14), price_usd=110.0)
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=110.0)
    contract = _insert_contract(quantity_mt=5.0, entry_price=100.0, status=HedgeContractStatus.active)
    payload = _settlement_payload(str(uuid4()))

    with SessionLocal() as session:
        ingest_hedge_contract_settlement(session, contract.id, payload)

    with SessionLocal() as session:
        result = compute_pl(
            session,
            entity_type="hedge_contract",
            entity_id=contract.id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert result.realized_pl == Decimal("50.000000")


def test_realized_pl_idempotent_on_reprocess() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 14), price_usd=110.0)
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=110.0)
    contract = _insert_contract(quantity_mt=5.0, entry_price=100.0, status=HedgeContractStatus.active)
    source_event_id = str(uuid4())
    payload = _settlement_payload(source_event_id)

    with SessionLocal() as session:
        ingest_hedge_contract_settlement(session, contract.id, payload)

    with SessionLocal() as session:
        ingest_hedge_contract_settlement(session, contract.id, payload)

    with SessionLocal() as session:
        result = compute_pl(
            session,
            entity_type="hedge_contract",
            entity_id=contract.id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert result.realized_pl == Decimal("50.000000")


def test_realized_pl_orders_hard_fail() -> None:
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            compute_pl(
                session,
                entity_type="order",
                entity_id=uuid4(),
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
            )
        assert exc.value.status_code in {status.HTTP_424_FAILED_DEPENDENCY, status.HTTP_422_UNPROCESSABLE_ENTITY}
        assert "Realized cashflow ledger not implemented for orders" in exc.value.detail


def test_compute_pl_collects_provenance_from_ledger_entries_in_realized_path() -> None:
    contract = _insert_contract(quantity_mt=5.0, entry_price=100.0, status=HedgeContractStatus.settled)
    with SessionLocal() as session:
        session.add(
            CashFlowLedgerEntry(
                hedge_contract_id=contract.id,
                source_event_type="HEDGE_CONTRACT_SETTLED",
                source_event_id=uuid4(),
                leg_id="FLOAT",
                cashflow_date=date(2026, 1, 15),
                currency="USD",
                direction="IN",
                amount=Decimal("550.000000"),
                price_source="westmetall",
                price_symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                price_settlement_date=date(2026, 1, 14),
                price_value=Decimal("110.000000"),
            )
        )
        session.commit()
        result = compute_pl(
            session,
            entity_type="hedge_contract",
            entity_id=contract.id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert result.price_references[0].symbol == "LME_ALU_CASH_SETTLEMENT_DAILY"
        assert result.price_references[0].source == "westmetall"
        assert result.price_references[0].settlement_date == date(2026, 1, 14)
        assert result.price_references[0].value == Decimal("110.000000")


def test_compute_pl_collects_only_priced_ledger_entries_into_price_references() -> None:
    contract = _insert_contract(quantity_mt=5.0, entry_price=100.0, status=HedgeContractStatus.settled)
    source_event_id = uuid4()
    with SessionLocal() as session:
        session.add_all(
            [
                CashFlowLedgerEntry(
                    hedge_contract_id=contract.id,
                    source_event_type="HEDGE_CONTRACT_SETTLED",
                    source_event_id=source_event_id,
                    leg_id="FIXED",
                    cashflow_date=date(2026, 1, 15),
                    currency="USD",
                    direction="OUT",
                    amount=Decimal("500.000000"),
                ),
                CashFlowLedgerEntry(
                    hedge_contract_id=contract.id,
                    source_event_type="HEDGE_CONTRACT_SETTLED",
                    source_event_id=source_event_id,
                    leg_id="FLOAT",
                    cashflow_date=date(2026, 1, 15),
                    currency="USD",
                    direction="IN",
                    amount=Decimal("550.000000"),
                    price_source="westmetall",
                    price_symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                    price_settlement_date=date(2026, 1, 14),
                    price_value=Decimal("110.000000"),
                ),
            ]
        )
        session.commit()
        result = compute_pl(
            session,
            entity_type="hedge_contract",
            entity_id=contract.id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert result.realized_pl == Decimal("50.000000")
        assert len(result.price_references) == 1


def test_partially_settled_contract_includes_remaining_unrealized_mtm_and_ledger_pl() -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol=symbol, settlement_date=date(2026, 1, 30), price_usd=112.0)
    contract = _insert_contract(
        quantity_mt=5.0,
        entry_price=100.0,
        status=HedgeContractStatus.partially_settled,
    )
    _insert_realized_ledger_entries(contract.id)

    with SessionLocal() as session:
        result = compute_pl(
            session,
            entity_type="hedge_contract",
            entity_id=contract.id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

    assert result.realized_pl == Decimal("50.000000")
    assert result.unrealized_mtm == Decimal("60.000000")
    assert any(
        reference.symbol == symbol
        and reference.source == "westmetall"
        and reference.settlement_date == date(2026, 1, 30)
        and reference.value == Decimal("112.000000")
        for reference in result.price_references
    )


def test_partially_settled_missing_price_hard_fails_424() -> None:
    contract = _insert_contract(
        quantity_mt=5.0,
        entry_price=100.0,
        status=HedgeContractStatus.partially_settled,
    )

    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            compute_pl(
                session,
                entity_type="hedge_contract",
                entity_id=contract.id,
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 31),
            )

    assert exc.value.status_code == status.HTTP_424_FAILED_DEPENDENCY
    assert "cash settlement" in exc.value.detail.lower()


def test_settled_contract_returns_realized_only_without_period_end_price() -> None:
    contract = _insert_contract(
        quantity_mt=5.0,
        entry_price=100.0,
        status=HedgeContractStatus.settled,
    )
    _insert_realized_ledger_entries(contract.id)

    with SessionLocal() as session:
        result = compute_pl(
            session,
            entity_type="hedge_contract",
            entity_id=contract.id,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
        )

    assert result.realized_pl == Decimal("0")
    assert result.unrealized_mtm == Decimal("0")


def test_settled_contract_preserves_realized_pl_and_references_without_period_end_price() -> None:
    contract = _insert_contract(
        quantity_mt=5.0,
        entry_price=100.0,
        status=HedgeContractStatus.settled,
    )
    _insert_realized_ledger_entries(contract.id)

    with SessionLocal() as session:
        result = compute_pl(
            session,
            entity_type="hedge_contract",
            entity_id=contract.id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

    assert result.realized_pl == Decimal("50.000000")
    assert result.unrealized_mtm == Decimal("0")
    assert len(result.price_references) == 1
    assert result.price_references[0].settlement_date == date(2026, 1, 14)


def test_cancelled_contract_hard_fails_instead_of_silent_zero() -> None:
    contract = _insert_contract(
        quantity_mt=5.0,
        entry_price=100.0,
        status=HedgeContractStatus.cancelled,
    )

    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            compute_pl(
                session,
                entity_type="hedge_contract",
                entity_id=contract.id,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
            )

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert "cancelled" in exc.value.detail
