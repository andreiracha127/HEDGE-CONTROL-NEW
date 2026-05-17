from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.cashflow import CashFlowLedgerEntry
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.market_data import CashSettlementPrice
from app.models.orders import Order, OrderPricingConvention, OrderType, PriceType
from app.schemas.cashflow import (
    HedgeContractSettlementCreate,
    HedgeContractSettlementLeg,
    LedgerDirection,
    LedgerLegId,
)
from app.services.cashflow_baseline_service import create_cashflow_baseline_snapshot
from app.services.cashflow_ledger_service import ingest_hedge_contract_settlement


def _insert_price(settlement_date: date, price_usd: Decimal | str) -> None:
    with SessionLocal() as session:
        session.add(
            CashSettlementPrice(
                source="westmetall",
                symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                settlement_date=settlement_date,
                price_usd=Decimal(str(price_usd)),
                source_url="https://example.test/source",
                html_sha256="0" * 64,
                fetched_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()


def _create_variable_sales_order(client, avg_entry_price: float) -> str:
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


def _insert_contract(
    *,
    quantity_mt: str = "5.0",
    fixed_price_value: str = "100.0",
    status: HedgeContractStatus = HedgeContractStatus.active,
    deleted: bool = False,
) -> UUID:
    with SessionLocal() as session:
        contract = HedgeContract(
            commodity="LME_AL",
            quantity_mt=Decimal(quantity_mt),
            fixed_leg_side=HedgeLegSide.buy,
            variable_leg_side=HedgeLegSide.sell,
            classification=HedgeClassification.long,
            fixed_price_value=Decimal(fixed_price_value),
            fixed_price_unit="USD/MT",
            float_pricing_convention="avg",
            status=status,
            deleted_at=(
                datetime(2026, 1, 15, tzinfo=timezone.utc) if deleted else None
            ),
        )
        session.add(contract)
        session.commit()
        session.refresh(contract)
        return contract.id


def _insert_variable_order(
    *,
    quantity_mt: str = "5.0",
    avg_entry_price: str = "100.0",
    deleted: bool = False,
) -> UUID:
    with SessionLocal() as session:
        order = Order(
            order_type=OrderType.sales,
            price_type=PriceType.variable,
            commodity="ALUMINUM",
            quantity_mt=Decimal(quantity_mt),
            pricing_convention=OrderPricingConvention.avg,
            avg_entry_price=Decimal(avg_entry_price),
            deleted_at=(
                datetime(2026, 1, 15, tzinfo=timezone.utc) if deleted else None
            ),
        )
        session.add(order)
        session.commit()
        session.refresh(order)
        return order.id


def test_snapshot_creation_is_idempotent(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        first = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 1), correlation_id="c-1")
        second = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 1), correlation_id="c-2")
        assert first.id == second.id


def test_snapshot_conflict_returns_409(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        snapshot = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 1), correlation_id="c-1")
        snapshot.total_net_cashflow = Decimal("999.0")
        session.commit()

    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 1), correlation_id="c-2")
        assert exc.value.status_code == 409


def test_query_existing_snapshot(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    response = client.post(
        "/cashflow/baseline/snapshots",
        json={"as_of_date": "2026-02-01", "correlation_id": "c-1"},
    )
    assert response.status_code == 201

    get_resp = client.get("/cashflow/baseline/snapshots", params={"as_of_date": "2026-02-01"})
    assert get_resp.status_code == 200
    assert get_resp.json()["as_of_date"] == "2026-02-01"


def test_propagate_424_if_d1_price_missing(client) -> None:
    _create_variable_sales_order(client, avg_entry_price=100.0)
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 1), correlation_id="c-1")
        assert exc.value.status_code == 424


def test_cashflow_baseline_inputs_hash_is_deterministic(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        first = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 2), correlation_id="c-1")
        second = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 2), correlation_id="c-2")
        assert second.id == first.id
        assert second.inputs_hash == first.inputs_hash
        assert len(first.inputs_hash) == 64


def test_cashflow_baseline_per_row_provenance_inside_unrealized_items(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        snapshot = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 2), correlation_id="c-1")
        item = snapshot.snapshot_data["unrealized_items"][0]
        assert item["price_source"] == "westmetall"
        assert item["price_symbol"] == "LME_ALU_CASH_SETTLEMENT_DAILY"
        assert item["price_settlement_date"] == "2026-01-30"
        assert item["price_value"] == "110.000000"


def test_cashflow_baseline_snapshot_uses_baseline_payload_contract(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        snapshot = create_cashflow_baseline_snapshot(
            session, as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )

    assert snapshot.snapshot_data["view"] == "baseline"
    assert set(snapshot.snapshot_data) == {
        "view",
        "as_of_date",
        "unrealized_items",
        "realized_ledger_entries",
        "reconciliation",
    }
    assert "cashflow" + "_items" not in snapshot.snapshot_data


def test_cashflow_baseline_service_does_not_import_analytic() -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "cashflow_baseline_service.py"
    )
    source = source_path.read_text()
    assert "compute_cashflow_analytic" not in source
    assert "analytic.model_dump" not in source


def test_cashflow_baseline_persists_realized_ledger_reconciliation() -> None:
    _insert_price(settlement_date=date(2026, 1, 29), price_usd=105.0)
    contract_id = _insert_contract()
    event_id = uuid4()

    payload = HedgeContractSettlementCreate(
        source_event_id=event_id,
        cashflow_date=date(2026, 1, 30),
        currency="USD",
        legs=[
            HedgeContractSettlementLeg(
                leg_id=LedgerLegId.fixed,
                direction=LedgerDirection.out,
                amount=Decimal("500.000000"),
            ),
            HedgeContractSettlementLeg(
                leg_id=LedgerLegId.float,
                direction=LedgerDirection.in_,
                amount=Decimal("525.000000"),
            ),
        ],
    )

    with SessionLocal() as session:
        ingest_hedge_contract_settlement(session, contract_id, payload)
        snapshot = create_cashflow_baseline_snapshot(
            session, as_of_date=date(2026, 2, 2), correlation_id="c-1"
        )

    realized_entries = snapshot.snapshot_data["realized_ledger_entries"]
    assert len(realized_entries) == 2
    assert {entry["leg_id"] for entry in realized_entries} == {"FIXED", "FLOAT"}
    assert {entry["source_event_type"] for entry in realized_entries} == {
        "HEDGE_CONTRACT_SETTLED"
    }
    assert all(entry["currency"] == "USD" for entry in realized_entries)
    assert {entry["price_source"] for entry in realized_entries} == {
        None,
        "westmetall",
    }

    reconciliation = snapshot.snapshot_data["reconciliation"]
    realized_total = sum(
        Decimal(entry["signed_amount_usd"]) for entry in realized_entries
    )
    assert realized_total == Decimal("25.000000")
    assert Decimal(reconciliation["realized_total_usd"]) == realized_total
    assert Decimal(reconciliation["total_net_cashflow"]) == (
        Decimal(reconciliation["unrealized_total_usd"]) + realized_total
    )
    assert Decimal(str(snapshot.total_net_cashflow)) == Decimal(
        reconciliation["total_net_cashflow"]
    )


def test_cashflow_baseline_includes_partially_settled_unrealized_tail() -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    contract_id = _insert_contract(status=HedgeContractStatus.partially_settled)

    with SessionLocal() as session:
        snapshot = create_cashflow_baseline_snapshot(
            session, as_of_date=date(2026, 2, 2), correlation_id="c-1"
        )

    unrealized_items = snapshot.snapshot_data["unrealized_items"]
    realized_entries = snapshot.snapshot_data["realized_ledger_entries"]
    assert [item["object_id"] for item in unrealized_items] == [str(contract_id)]
    assert unrealized_items[0]["price_source"] == "westmetall"
    assert unrealized_items[0]["price_symbol"] == "LME_ALU_CASH_SETTLEMENT_DAILY"
    assert realized_entries == []


def test_cashflow_baseline_excludes_deleted_unrealized_sources() -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    live_contract_id = _insert_contract()
    deleted_contract_id = _insert_contract(deleted=True)
    live_order_id = _insert_variable_order()
    deleted_order_id = _insert_variable_order(deleted=True)

    with SessionLocal() as session:
        snapshot = create_cashflow_baseline_snapshot(
            session, as_of_date=date(2026, 2, 2), correlation_id="c-1"
        )

    item_ids = {item["object_id"] for item in snapshot.snapshot_data["unrealized_items"]}
    assert item_ids == {str(live_contract_id), str(live_order_id)}
    assert str(deleted_contract_id) not in item_ids
    assert str(deleted_order_id) not in item_ids
    assert Decimal(
        snapshot.snapshot_data["reconciliation"]["unrealized_total_usd"]
    ) == Decimal("100.000000")


def test_cashflow_baseline_unsupported_ledger_direction_hard_fails() -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    contract_id = _insert_contract()
    with SessionLocal() as session:
        session.add(
            CashFlowLedgerEntry(
                hedge_contract_id=contract_id,
                source_event_type="MANUAL_ADJUSTMENT",
                source_event_id=None,
                leg_id="ADJ",
                cashflow_date=date(2026, 1, 30),
                currency="USD",
                direction="SIDEWAYS",
                amount=Decimal("1.000000"),
            )
        )
        session.commit()

    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            create_cashflow_baseline_snapshot(
                session, as_of_date=date(2026, 2, 2), correlation_id="c-1"
            )

    assert exc.value.status_code == 422
    assert "Unsupported ledger direction" in exc.value.detail


def test_cashflow_baseline_existing_snapshot_missing_hash_returns_409(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        snapshot = create_cashflow_baseline_snapshot(
            session, as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )
        snapshot.inputs_hash = None
        session.commit()

    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            create_cashflow_baseline_snapshot(
                session, as_of_date=date(2026, 2, 1), correlation_id="c-2"
            )

    assert exc.value.status_code == 409
    assert "missing inputs_hash" in exc.value.detail


def test_cashflow_baseline_hash_canonicalizes_unrealized_and_ledger_arrays() -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    contract_id = _insert_contract()
    order_id = _insert_variable_order()

    with SessionLocal() as session:
        session.add_all(
            [
                CashFlowLedgerEntry(
                    hedge_contract_id=contract_id,
                    source_event_type="MANUAL_ADJUSTMENT",
                    source_event_id=uuid4(),
                    leg_id="B",
                    cashflow_date=date(2026, 1, 30),
                    currency="USD",
                    direction="IN",
                    amount=Decimal("2.000000"),
                ),
                CashFlowLedgerEntry(
                    hedge_contract_id=contract_id,
                    source_event_type="MANUAL_ADJUSTMENT",
                    source_event_id=None,
                    leg_id="A",
                    cashflow_date=date(2026, 1, 30),
                    currency="USD",
                    direction="OUT",
                    amount=Decimal("1.000000"),
                ),
            ]
        )
        session.commit()
        snapshot = create_cashflow_baseline_snapshot(
            session, as_of_date=date(2026, 2, 2), correlation_id="c-1"
        )
        original_hash = snapshot.inputs_hash
        reordered_payload = dict(snapshot.snapshot_data)
        reordered_payload["unrealized_items"] = list(
            reversed(reordered_payload["unrealized_items"])
        )
        reordered_payload["realized_ledger_entries"] = list(
            reversed(reordered_payload["realized_ledger_entries"])
        )
        snapshot.snapshot_data = reordered_payload
        session.commit()

    with SessionLocal() as session:
        second = create_cashflow_baseline_snapshot(
            session, as_of_date=date(2026, 2, 2), correlation_id="c-2"
        )

    assert second.inputs_hash == original_hash
    assert {item["object_id"] for item in second.snapshot_data["unrealized_items"]} == {
        str(contract_id),
        str(order_id),
    }
    assert any(
        entry["source_event_id"] is None
        for entry in second.snapshot_data["realized_ledger_entries"]
    )
