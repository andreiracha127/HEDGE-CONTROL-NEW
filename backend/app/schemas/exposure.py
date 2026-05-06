from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas._types import MTQuantity


class ExposureType(str, Enum):
    active = "active"
    passive = "passive"


class ExposureBase(BaseModel):
    source_order_id: UUID = Field(..., description="Originating order ID")
    exposure_type: ExposureType = Field(
        ..., description="Active for SO, passive for PO"
    )
    quantity_mt: MTQuantity = Field(..., description="Quantity in metric tons (MT)")
    as_of: datetime = Field(..., description="State timestamp for exposure")


class ExposureRead(ExposureBase):
    id: UUID


class CommercialExposureRead(BaseModel):
    commodity: str = Field(..., description="Commodity identifier")
    pre_reduction_commercial_active_mt: MTQuantity = Field(
        ..., description="Sum of variable-price SO quantity before linkage (MT)"
    )
    pre_reduction_commercial_passive_mt: MTQuantity = Field(
        ..., description="Sum of variable-price PO quantity before linkage (MT)"
    )
    reduction_applied_active_mt: MTQuantity = Field(
        ..., description="Reduction applied to active exposure via linkages (MT)"
    )
    reduction_applied_passive_mt: MTQuantity = Field(
        ..., description="Reduction applied to passive exposure via linkages (MT)"
    )
    commercial_active_mt: MTQuantity = Field(
        ..., description="Residual variable-price SO exposure (MT)"
    )
    commercial_passive_mt: MTQuantity = Field(
        ..., description="Residual variable-price PO exposure (MT)"
    )
    commercial_net_mt: MTQuantity = Field(..., description="Active minus Passive (MT)")
    calculation_timestamp: datetime = Field(
        ..., description="UTC calculation timestamp"
    )
    order_count_considered: int = Field(
        ..., description="Count of variable-price orders considered"
    )


class GlobalExposureRead(BaseModel):
    commodity: str = Field(..., description="Commodity identifier")
    pre_reduction_global_active_mt: MTQuantity = Field(
        ..., description="Global active before linkage reduction (MT)"
    )
    pre_reduction_global_passive_mt: MTQuantity = Field(
        ..., description="Global passive before linkage reduction (MT)"
    )
    reduction_applied_active_mt: MTQuantity = Field(
        ..., description="Reduction applied to global active via linkages (MT)"
    )
    reduction_applied_passive_mt: MTQuantity = Field(
        ..., description="Reduction applied to global passive via linkages (MT)"
    )
    global_active_mt: MTQuantity = Field(
        ..., description="Reduced global active exposure (MT)"
    )
    global_passive_mt: MTQuantity = Field(
        ..., description="Reduced global passive exposure (MT)"
    )
    global_net_mt: MTQuantity = Field(
        ..., description="Global active minus global passive (MT)"
    )
    commercial_active_mt: MTQuantity = Field(
        ..., description="Reduced commercial active exposure (MT)"
    )
    commercial_passive_mt: MTQuantity = Field(
        ..., description="Reduced commercial passive exposure (MT)"
    )
    hedge_long_mt: MTQuantity = Field(
        ..., description="Unlinked hedge long quantity (MT)"
    )
    hedge_short_mt: MTQuantity = Field(
        ..., description="Unlinked hedge short quantity (MT)"
    )
    calculation_timestamp: datetime = Field(
        ..., description="UTC calculation timestamp"
    )
    entities_count_considered: int = Field(
        ..., description="Count of variable-price orders and hedge contracts considered"
    )
