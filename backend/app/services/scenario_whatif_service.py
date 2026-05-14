from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Callable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.precision import quantize_money, quantize_mt, quantize_price
from app.models.cashflow import CashFlowLedgerEntry
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.linkages import HedgeOrderLinkage
from app.models.orders import Order, OrderPricingConvention, PriceType
from app.schemas.cashflow import CashFlowAnalyticResponse, CashFlowItem
from app.schemas.exposure import CommercialExposureRead, GlobalExposureRead
from app.schemas.mtm import MTMObjectType, MTMResultResponse
from app.schemas.scenario import (
    AddCashSettlementPriceOverrideDelta,
    AddUnlinkedHedgeContractDelta,
    AdjustOrderQuantityDelta,
    ScenarioCashflowSnapshot,
    ScenarioPLSnapshotItem,
    ScenarioWhatIfRunRequest,
    ScenarioWhatIfRunResponse,
)
from app.services.cashflow_ledger_service import SOURCE_EVENT_TYPE
from app.services.exposure_service import (
    compute_commercial_exposure_pure,
    compute_global_exposure_pure,
)
from app.services.price_lookup_service import (
    PriceQuote,
    get_cash_settlement_price_d1_with_provenance,
    resolve_symbol,
)
from app.utils.market_calendar import _market_calendar_for_symbol, _prior_business_day


@dataclass(frozen=True)
class VirtualHedgeContract:
    id: UUID
    commodity: str
    quantity_mt: Decimal
    fixed_leg_side: HedgeLegSide
    variable_leg_side: HedgeLegSide
    classification: HedgeClassification
    fixed_price_value: Decimal
    fixed_price_unit: str
    float_pricing_convention: str
    status: HedgeContractStatus


def _build_price_lookup(
    overrides: dict[tuple[str, date], Decimal],
) -> Callable[[Session, str, date], PriceQuote]:
    def lookup(db: Session, symbol: str, as_of_date: date) -> PriceQuote:
        prior_bd = _prior_business_day(
            as_of_date, lambda year: _market_calendar_for_symbol(symbol, year)
        )
        key = (symbol, prior_bd)
        if key in overrides:
            return PriceQuote(
                value=overrides[key],
                source="scenario_override",
                settlement_date=prior_bd,
                symbol=symbol,
            )
        return get_cash_settlement_price_d1_with_provenance(
            db, symbol=symbol, as_of_date=as_of_date
        )

    return lookup


def _resolve_price_quote(
    db: Session,
    as_of_date: date,
    lookup: Callable[[Session, str, date], PriceQuote],
    commodity: str,
) -> PriceQuote:
    symbol = resolve_symbol(commodity)
    return lookup(db, symbol, as_of_date)


def _mtm_for_contract(
    contract_id: UUID,
    quantity_mt: Decimal,
    entry_price: Decimal,
    as_of_date: date,
    price_quote: PriceQuote,
) -> MTMResultResponse:
    quantity_mt = quantize_mt(quantity_mt)
    entry_price = quantize_price(entry_price)
    price_d1 = quantize_price(price_quote.value)
    mtm_value = quantize_money(quantity_mt * (price_d1 - entry_price))
    return MTMResultResponse(
        object_type=MTMObjectType.hedge_contract,
        object_id=str(contract_id),
        as_of_date=as_of_date,
        mtm_value=mtm_value,
        price_d1=price_d1,
        entry_price=entry_price,
        quantity_mt=quantity_mt,
        price_quote=price_quote,
    )


def _mtm_for_order(
    order: Order,
    quantity_mt: Decimal,
    as_of_date: date,
    price_quote: PriceQuote,
) -> MTMResultResponse:
    if order.price_type != PriceType.variable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MTM is not defined for fixed-price orders",
        )
    if order.pricing_convention not in (
        OrderPricingConvention.avg,
        OrderPricingConvention.avginter,
        OrderPricingConvention.c2r,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order pricing_convention is not MTM-eligible",
        )
    if order.avg_entry_price is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order avg_entry_price is missing",
        )

    quantity_mt = quantize_mt(quantity_mt)
    entry_price = quantize_price(order.avg_entry_price)
    price_d1 = quantize_price(price_quote.value)
    mtm_value = quantize_money(quantity_mt * (price_d1 - entry_price))
    return MTMResultResponse(
        object_type=MTMObjectType.order,
        object_id=str(order.id),
        as_of_date=as_of_date,
        mtm_value=mtm_value,
        price_d1=price_d1,
        entry_price=entry_price,
        quantity_mt=quantity_mt,
        price_quote=price_quote,
    )


def _apply_deltas(
    req: ScenarioWhatIfRunRequest,
    contracts: list[HedgeContract],
    orders: list[Order],
) -> tuple[
    list[VirtualHedgeContract], dict[UUID, Decimal], dict[tuple[str, date], Decimal]
]:
    contract_ids = {contract.id for contract in contracts}
    order_ids = {order.id for order in orders}
    virtual_contracts: list[VirtualHedgeContract] = []
    order_quantity_overrides: dict[UUID, Decimal] = {}
    price_overrides: dict[tuple[str, date], Decimal] = {}

    for delta in req.deltas:
        if isinstance(delta, AddUnlinkedHedgeContractDelta):
            if delta.contract_id in contract_ids:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Virtual contract_id collides with existing contract",
                )
            if delta.fixed_leg_side == delta.variable_leg_side:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="fixed_leg_side and variable_leg_side must differ",
                )
            classification = (
                HedgeClassification.long
                if delta.fixed_leg_side == "buy"
                else HedgeClassification.short
            )
            virtual_contracts.append(
                VirtualHedgeContract(
                    id=delta.contract_id,
                    commodity=delta.commodity,
                    quantity_mt=Decimal(delta.quantity_mt),
                    fixed_leg_side=HedgeLegSide(delta.fixed_leg_side),
                    variable_leg_side=HedgeLegSide(delta.variable_leg_side),
                    classification=classification,
                    fixed_price_value=Decimal(delta.fixed_price_value),
                    fixed_price_unit=delta.fixed_price_unit,
                    float_pricing_convention=delta.float_pricing_convention,
                    status=HedgeContractStatus.active,
                )
            )
        elif isinstance(delta, AdjustOrderQuantityDelta):
            if delta.order_id not in order_ids:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
                )
            order_quantity_overrides[delta.order_id] = Decimal(delta.new_quantity_mt)
        elif isinstance(delta, AddCashSettlementPriceOverrideDelta):
            price_overrides[(delta.symbol, delta.settlement_date)] = Decimal(
                delta.price_usd
            )

    return virtual_contracts, order_quantity_overrides, price_overrides


def _load_orders(
    db: Session, quantity_overrides: dict[UUID, Decimal]
) -> list[tuple[Order, Decimal]]:
    orders = (
        db.query(Order)
        .filter(Order.deleted_at.is_(None))
        .order_by(Order.created_at.asc())
        .all()
    )
    result: list[tuple[Order, Decimal]] = []
    for order in orders:
        quantity = quantity_overrides.get(order.id, Decimal(str(order.quantity_mt)))
        result.append((order, quantity))
    return result


def _load_base_orders(db: Session) -> list[Order]:
    return (
        db.query(Order)
        .filter(Order.deleted_at.is_(None))
        .order_by(Order.created_at.asc())
        .all()
    )


def _load_contracts(db: Session) -> list[HedgeContract]:
    return db.query(HedgeContract).order_by(HedgeContract.created_at.asc()).all()


def _load_exposure_contracts(db: Session) -> list[HedgeContract]:
    return (
        db.query(HedgeContract)
        .filter(
            HedgeContract.deleted_at.is_(None),
            HedgeContract.status.in_(
                [HedgeContractStatus.active, HedgeContractStatus.partially_settled]
            ),
        )
        .order_by(HedgeContract.created_at.asc())
        .all()
    )


def _load_linkages(db: Session) -> list[HedgeOrderLinkage]:
    return (
        db.query(HedgeOrderLinkage)
        .join(Order, Order.id == HedgeOrderLinkage.order_id)
        .join(HedgeContract, HedgeContract.id == HedgeOrderLinkage.contract_id)
        .filter(
            Order.deleted_at.is_(None),
            HedgeContract.deleted_at.is_(None),
            HedgeContract.status.in_(
                [HedgeContractStatus.active, HedgeContractStatus.partially_settled]
            ),
        )
        .all()
    )


def _compute_commercial_exposure(
    orders: list[tuple[Order, Decimal]],
    linkages: list[HedgeOrderLinkage],
    calculation_timestamp: datetime,
) -> list[CommercialExposureRead]:
    return compute_commercial_exposure_pure(
        orders=orders,
        linkages=linkages,
        calculation_timestamp=calculation_timestamp,
    )


def _compute_global_exposure(
    orders: list[tuple[Order, Decimal]],
    contracts: list[HedgeContract],
    virtual_contracts: list[VirtualHedgeContract],
    linkages: list[HedgeOrderLinkage],
    calculation_timestamp: datetime,
) -> list[GlobalExposureRead]:
    return compute_global_exposure_pure(
        orders=orders,
        contracts=contracts,
        virtual_contracts=virtual_contracts,
        linkages=linkages,
        calculation_timestamp=calculation_timestamp,
    )


def run_what_if(
    db: Session, req: ScenarioWhatIfRunRequest
) -> ScenarioWhatIfRunResponse:
    base_orders = _load_base_orders(db)
    base_contracts = _load_contracts(db)
    linkages = _load_linkages(db)

    virtual_contracts, order_overrides, price_overrides = _apply_deltas(
        req, base_contracts, base_orders
    )

    orders = _load_orders(db, order_overrides)
    contracts = base_contracts
    exposure_contracts = _load_exposure_contracts(db)

    lookup = _build_price_lookup(price_overrides)

    mtm_results: list[MTMResultResponse] = []
    for contract in contracts:
        if contract.status != HedgeContractStatus.active:
            continue
        if contract.fixed_price_value is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Hedge contract entry_price is missing",
            )
        mtm_results.append(
            _mtm_for_contract(
                contract_id=contract.id,
                quantity_mt=Decimal(str(contract.quantity_mt)),
                entry_price=Decimal(str(contract.fixed_price_value)),
                as_of_date=req.as_of_date,
                price_quote=_resolve_price_quote(
                    db, req.as_of_date, lookup, contract.commodity
                ),
            )
        )

    for contract in virtual_contracts:
        mtm_results.append(
            _mtm_for_contract(
                contract_id=contract.id,
                quantity_mt=contract.quantity_mt,
                entry_price=contract.fixed_price_value,
                as_of_date=req.as_of_date,
                price_quote=_resolve_price_quote(
                    db, req.as_of_date, lookup, contract.commodity
                ),
            )
        )

    for order, quantity in orders:
        if order.price_type != PriceType.variable:
            continue
        mtm_results.append(
            _mtm_for_order(
                order,
                quantity,
                req.as_of_date,
                _resolve_price_quote(db, req.as_of_date, lookup, order.commodity),
            )
        )

    cashflow_items: list[CashFlowItem] = [
        CashFlowItem(
            object_type=result.object_type.value,
            object_id=result.object_id,
            settlement_date=req.as_of_date,
            amount_usd=quantize_money(result.mtm_value),
            mtm_value=quantize_money(result.mtm_value),
        )
        for result in mtm_results
    ]
    total_cashflow = quantize_money(
        sum((item.amount_usd for item in cashflow_items), Decimal("0"))
    )
    cashflow_analytic = CashFlowAnalyticResponse(
        as_of_date=req.as_of_date,
        cashflow_items=cashflow_items,
        total_net_cashflow=total_cashflow,
    )
    cashflow_snapshot = ScenarioCashflowSnapshot(analytic=cashflow_analytic)

    calculation_timestamp = datetime.combine(
        req.as_of_date, time.min, tzinfo=timezone.utc
    )
    commercial_exposure = _compute_commercial_exposure(
        orders, linkages, calculation_timestamp
    )
    global_exposure = _compute_global_exposure(
        orders,
        exposure_contracts,
        virtual_contracts,
        linkages,
        calculation_timestamp,
    )

    pl_snapshots: list[ScenarioPLSnapshotItem] = []
    for contract in contracts:
        if contract.status != HedgeContractStatus.active:
            unrealized = Decimal("0")
        else:
            if contract.fixed_price_value is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Hedge contract entry_price is missing",
                )
            unrealized = _mtm_for_contract(
                contract_id=contract.id,
                quantity_mt=Decimal(str(contract.quantity_mt)),
                entry_price=Decimal(str(contract.fixed_price_value)),
                as_of_date=req.period_end,
                price_quote=_resolve_price_quote(
                    db, req.period_end, lookup, contract.commodity
                ),
            ).mtm_value

        realized = Decimal("0")
        ledger_entries = (
            db.query(CashFlowLedgerEntry)
            .filter(
                CashFlowLedgerEntry.hedge_contract_id == contract.id,
                CashFlowLedgerEntry.source_event_type == SOURCE_EVENT_TYPE,
                CashFlowLedgerEntry.cashflow_date >= req.period_start,
                CashFlowLedgerEntry.cashflow_date <= req.period_end,
            )
            .all()
        )
        for entry in ledger_entries:
            amount = quantize_money(entry.amount)
            if entry.direction == "IN":
                realized += amount
            elif entry.direction == "OUT":
                realized -= amount
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unsupported ledger direction: {entry.direction}",
                )

        pl_snapshots.append(
            ScenarioPLSnapshotItem(
                entity_type="hedge_contract",
                entity_id=contract.id,
                period_start=req.period_start,
                period_end=req.period_end,
                realized_pl=quantize_money(realized),
                unrealized_mtm=quantize_money(unrealized),
            )
        )

    for contract in virtual_contracts:
        unrealized = _mtm_for_contract(
            contract_id=contract.id,
            quantity_mt=contract.quantity_mt,
            entry_price=contract.fixed_price_value,
            as_of_date=req.period_end,
            price_quote=_resolve_price_quote(
                db, req.period_end, lookup, contract.commodity
            ),
        ).mtm_value
        pl_snapshots.append(
            ScenarioPLSnapshotItem(
                entity_type="hedge_contract",
                entity_id=contract.id,
                period_start=req.period_start,
                period_end=req.period_end,
                realized_pl=Decimal("0.000000"),
                unrealized_mtm=quantize_money(unrealized),
            )
        )

    return ScenarioWhatIfRunResponse(
        commercial_exposure_snapshot=commercial_exposure,
        global_exposure_snapshot=global_exposure,
        mtm_snapshot=mtm_results,
        cashflow_snapshot=cashflow_snapshot,
        pl_snapshot=pl_snapshots,
    )
