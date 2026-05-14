from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.cashflow import CashFlowLedgerEntry
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.linkages import HedgeOrderLinkage
from app.models.market_data import CashSettlementPrice
from app.models.orders import Order, OrderPricingConvention, OrderType, PriceType
from app.schemas.scenario import ScenarioWhatIfRunRequest
from app.services.cashflow_ledger_service import SOURCE_EVENT_TYPE
from app.services.exposure_service import ExposureService
from app.services.scenario_whatif_service import run_what_if


AS_OF_DATE = date(2026, 2, 1)
PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 1, 31)
CALCULATION_TIMESTAMP = datetime.combine(AS_OF_DATE, datetime.min.time(), timezone.utc)


def _scenario_request() -> ScenarioWhatIfRunRequest:
    return ScenarioWhatIfRunRequest(
        as_of_date=AS_OF_DATE,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        deltas=[],
    )


def _insert_price(session, symbol: str = "LME_ALU_CASH_SETTLEMENT_DAILY") -> None:
    session.add(
        CashSettlementPrice(
            source="westmetall",
            symbol=symbol,
            settlement_date=date(2026, 1, 30),
            price_usd=Decimal("110.000000"),
            source_url="https://example.test/source",
            html_sha256="0" * 64,
            fetched_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
        )
    )


def _order(
    session,
    *,
    order_type: OrderType,
    quantity_mt: Decimal,
    commodity: str = "ALUMINUM",
    price_type: PriceType = PriceType.variable,
    deleted: bool = False,
) -> Order:
    order = Order(
        order_type=order_type,
        price_type=price_type,
        commodity=commodity,
        quantity_mt=quantity_mt,
        pricing_convention=OrderPricingConvention.avg,
        avg_entry_price=Decimal("100.000000"),
        deleted_at=(
            datetime(2026, 1, 15, tzinfo=timezone.utc) if deleted else None
        ),
    )
    session.add(order)
    session.flush()
    return order


def _contract(
    session,
    *,
    classification: HedgeClassification,
    quantity_mt: Decimal,
    commodity: str = "ALUMINUM",
    status: HedgeContractStatus = HedgeContractStatus.active,
    deleted: bool = False,
) -> HedgeContract:
    fixed_leg_side = (
        HedgeLegSide.buy
        if classification == HedgeClassification.long
        else HedgeLegSide.sell
    )
    variable_leg_side = (
        HedgeLegSide.sell
        if classification == HedgeClassification.long
        else HedgeLegSide.buy
    )
    contract = HedgeContract(
        commodity=commodity,
        quantity_mt=quantity_mt,
        fixed_leg_side=fixed_leg_side,
        variable_leg_side=variable_leg_side,
        classification=classification,
        fixed_price_value=Decimal("100.000000"),
        fixed_price_unit="USD/MT",
        float_pricing_convention="avg",
        status=status,
        deleted_at=(
            datetime(2026, 1, 15, tzinfo=timezone.utc) if deleted else None
        ),
    )
    session.add(contract)
    session.flush()
    return contract


def _link(session, order: Order, contract: HedgeContract, quantity_mt: Decimal) -> None:
    session.add(
        HedgeOrderLinkage(
            order_id=order.id,
            contract_id=contract.id,
            quantity_mt=quantity_mt,
        )
    )
    session.flush()


def _commercial_rows(response) -> list[dict]:
    return [row.model_dump() for row in response.commercial_exposure_snapshot]


def _global_rows(response) -> list[dict]:
    return [row.model_dump() for row in response.global_exposure_snapshot]


def _row_by_commodity(rows: list[dict], commodity: str) -> dict:
    return next(row for row in rows if row["commodity"] == commodity)


def _assert_no_commodity(rows: list[dict], commodity: str) -> None:
    assert all(row["commodity"] != commodity for row in rows)


def _seed_parity_fixture(session) -> None:
    _insert_price(session)
    sales = _order(
        session,
        order_type=OrderType.sales,
        quantity_mt=Decimal("10.000000"),
    )
    _order(
        session,
        order_type=OrderType.purchase,
        quantity_mt=Decimal("6.000000"),
    )
    _order(
        session,
        order_type=OrderType.sales,
        price_type=PriceType.fixed,
        quantity_mt=Decimal("99.000000"),
    )
    hedge = _contract(
        session,
        classification=HedgeClassification.short,
        quantity_mt=Decimal("4.000000"),
    )
    _link(session, sales, hedge, Decimal("3.000000"))
    session.commit()


def test_empty_delta_commercial_parity(session, monkeypatch) -> None:
    _seed_parity_fixture(session)
    monkeypatch.setattr(
        "app.services.exposure_service.now_utc", lambda: CALCULATION_TIMESTAMP
    )

    live = ExposureService.compute_commercial_snapshot(session)
    scenario = run_what_if(session, _scenario_request())

    assert live == _commercial_rows(scenario)


def test_empty_delta_global_parity(session, monkeypatch) -> None:
    _seed_parity_fixture(session)
    monkeypatch.setattr(
        "app.services.exposure_service.now_utc", lambda: CALCULATION_TIMESTAMP
    )

    live = ExposureService.compute_global_snapshot(session)
    scenario = run_what_if(session, _scenario_request())

    assert live == _global_rows(scenario)


def test_archived_order_excluded_from_scenario(session) -> None:
    _insert_price(session)
    _order(
        session,
        order_type=OrderType.sales,
        quantity_mt=Decimal("5.000000"),
    )
    _order(
        session,
        order_type=OrderType.sales,
        quantity_mt=Decimal("7.000000"),
        commodity="ZINC",
        deleted=True,
    )
    session.commit()

    response = run_what_if(session, _scenario_request())

    _assert_no_commodity(_commercial_rows(response), "ZINC")
    _assert_no_commodity(_global_rows(response), "ZINC")


def test_settled_hedge_excluded_from_scenario_exposure(session) -> None:
    _contract(
        session,
        classification=HedgeClassification.short,
        quantity_mt=Decimal("7.000000"),
        commodity="ZINC",
        status=HedgeContractStatus.settled,
    )
    session.commit()

    response = run_what_if(session, _scenario_request())

    _assert_no_commodity(_global_rows(response), "ZINC")


def test_orphan_linkage_excluded_via_archived_order(session) -> None:
    _insert_price(session)
    archived_order = _order(
        session,
        order_type=OrderType.sales,
        quantity_mt=Decimal("10.000000"),
        deleted=True,
    )
    hedge = _contract(
        session,
        classification=HedgeClassification.short,
        quantity_mt=Decimal("10.000000"),
    )
    _link(session, archived_order, hedge, Decimal("8.000000"))
    session.commit()

    response = run_what_if(session, _scenario_request())
    row = _row_by_commodity(_global_rows(response), "ALUMINUM")

    assert row["hedge_short_mt"] == Decimal("10.000000")
    assert row["reduction_applied_active_mt"] == Decimal("0.000000")


@pytest.mark.parametrize(
    "status",
    [HedgeContractStatus.settled, HedgeContractStatus.cancelled],
)
def test_orphan_linkage_excluded_via_settled_hedge(
    session, status: HedgeContractStatus
) -> None:
    _insert_price(session)
    order = _order(
        session,
        order_type=OrderType.sales,
        quantity_mt=Decimal("10.000000"),
    )
    hedge = _contract(
        session,
        classification=HedgeClassification.short,
        quantity_mt=Decimal("10.000000"),
        status=status,
    )
    _link(session, order, hedge, Decimal("4.000000"))
    session.commit()

    response = run_what_if(session, _scenario_request())
    commercial = _row_by_commodity(_commercial_rows(response), "ALUMINUM")
    global_row = _row_by_commodity(_global_rows(response), "ALUMINUM")

    assert commercial["commercial_active_mt"] == Decimal("10.000000")
    assert commercial["reduction_applied_active_mt"] == Decimal("0.000000")
    assert global_row["commercial_active_mt"] == Decimal("10.000000")
    assert global_row["hedge_short_mt"] == Decimal("0.000000")


def test_settled_hedge_preserved_in_scenario_pl_excluded_from_exposure(
    session,
) -> None:
    _insert_price(session)
    active = _contract(
        session,
        classification=HedgeClassification.short,
        quantity_mt=Decimal("3.000000"),
    )
    settled = _contract(
        session,
        classification=HedgeClassification.short,
        quantity_mt=Decimal("7.000000"),
        status=HedgeContractStatus.settled,
    )
    session.add_all(
        [
            CashFlowLedgerEntry(
                hedge_contract_id=settled.id,
                source_event_type=SOURCE_EVENT_TYPE,
                leg_id="fixed",
                cashflow_date=date(2026, 1, 15),
                currency="USD",
                direction="IN",
                amount=Decimal("12.000000"),
            ),
            CashFlowLedgerEntry(
                hedge_contract_id=settled.id,
                source_event_type=SOURCE_EVENT_TYPE,
                leg_id="variable",
                cashflow_date=date(2026, 1, 20),
                currency="USD",
                direction="OUT",
                amount=Decimal("2.000000"),
            ),
        ]
    )
    session.commit()

    response = run_what_if(session, _scenario_request())
    global_row = _row_by_commodity(_global_rows(response), "ALUMINUM")
    settled_pl = next(
        row for row in response.pl_snapshot if row.entity_id == settled.id
    )

    assert global_row["hedge_short_mt"] == active.quantity_mt
    assert global_row["global_active_mt"] == active.quantity_mt
    assert settled_pl.unrealized_mtm == Decimal("0.000000")
    assert settled_pl.realized_pl == Decimal("10.000000")
    assert any(row.entity_id == active.id for row in response.pl_snapshot)
    assert any(row.entity_id == settled.id for row in response.pl_snapshot)
