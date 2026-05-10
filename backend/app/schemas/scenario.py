from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Union
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from app.schemas.cashflow import CashFlowAnalyticResponse
from app.schemas.exposure import CommercialExposureRead, GlobalExposureRead
from app.schemas.mtm import MTMResultResponse
from app.services.price_lookup_service import resolve_symbol


class ScenarioDeltaBase(BaseModel):
    delta_type: str = Field(..., max_length=64)


class AddUnlinkedHedgeContractDelta(ScenarioDeltaBase):
    delta_type: Literal["add_unlinked_hedge_contract"]
    contract_id: UUID
    commodity: str = Field(..., max_length=64)
    quantity_mt: Decimal
    fixed_leg_side: Literal["buy", "sell"]
    variable_leg_side: Literal["buy", "sell"]
    fixed_price_value: Decimal
    fixed_price_unit: Literal["USD/MT"]
    float_pricing_convention: str = Field(..., max_length=64)

    @model_validator(mode="after")
    def validate(self) -> "AddUnlinkedHedgeContractDelta":
        if self.quantity_mt <= 0:
            raise ValueError("quantity_mt must be greater than zero")
        if self.fixed_price_value <= 0:
            raise ValueError("fixed_price_value must be greater than zero")
        try:
            resolve_symbol(self.commodity)
        except HTTPException as exc:
            raise ValueError(
                f"commodity {self.commodity!r} has no settlement-symbol mapping"
            ) from exc
        return self


class AdjustOrderQuantityDelta(ScenarioDeltaBase):
    delta_type: Literal["adjust_order_quantity_mt"]
    order_id: UUID
    new_quantity_mt: Decimal

    @model_validator(mode="after")
    def validate_quantity(self) -> "AdjustOrderQuantityDelta":
        if self.new_quantity_mt <= 0:
            raise ValueError("new_quantity_mt must be greater than zero")
        return self


class AddCashSettlementPriceOverrideDelta(ScenarioDeltaBase):
    delta_type: Literal["add_cash_settlement_price_override"]
    symbol: str = Field(..., max_length=64)
    settlement_date: date
    price_usd: Decimal

    @model_validator(mode="after")
    def validate_price(self) -> "AddCashSettlementPriceOverrideDelta":
        if self.price_usd <= 0:
            raise ValueError("price_usd must be greater than zero")
        return self


ScenarioDelta = Annotated[
    Union[
        AddUnlinkedHedgeContractDelta,
        AdjustOrderQuantityDelta,
        AddCashSettlementPriceOverrideDelta,
    ],
    Field(discriminator="delta_type"),
]


class ScenarioWhatIfRunRequest(BaseModel):
    as_of_date: date
    period_start: date
    period_end: date
    deltas: list[ScenarioDelta] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_period(self) -> "ScenarioWhatIfRunRequest":
        if self.period_end < self.period_start:
            raise ValueError("period_end must be greater than or equal to period_start")
        return self


class ScenarioCashflowSnapshot(BaseModel):
    analytic: CashFlowAnalyticResponse


class ScenarioPLSnapshotItem(BaseModel):
    entity_type: Literal["hedge_contract"]
    entity_id: UUID
    period_start: date
    period_end: date
    realized_pl: Decimal
    unrealized_mtm: Decimal


class ScenarioWhatIfRunResponse(BaseModel):
    commercial_exposure_snapshot: list[CommercialExposureRead]
    global_exposure_snapshot: list[GlobalExposureRead]
    mtm_snapshot: list[MTMResultResponse]
    cashflow_snapshot: ScenarioCashflowSnapshot
    pl_snapshot: list[ScenarioPLSnapshotItem]
