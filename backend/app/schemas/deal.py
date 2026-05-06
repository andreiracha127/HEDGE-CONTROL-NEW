"""Schemas for Deal Engine (component 1.5)."""

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas._types import MTQuantity, Price


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DealStatus(str, Enum):
    open = "open"
    partially_hedged = "partially_hedged"
    fully_hedged = "fully_hedged"
    settled = "settled"
    closed = "closed"


class DealLinkedType(str, Enum):
    sales_order = "sales_order"
    purchase_order = "purchase_order"
    hedge = "hedge"
    contract = "contract"


# ---------------------------------------------------------------------------
# Create / Update
# ---------------------------------------------------------------------------


class DealCreate(BaseModel):
    name: str
    commodity: str
    links: list["DealLinkCreate"] = []


class DealLinkCreate(BaseModel):
    linked_type: DealLinkedType
    linked_id: UUID


class DealLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    deal_id: UUID
    linked_type: DealLinkedType
    linked_id: UUID
    created_at: datetime


class DealPNLSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    deal_id: UUID
    snapshot_date: date
    physical_revenue: Price
    physical_cost: Price
    hedge_pnl_realized: Price
    hedge_pnl_mtm: Price
    total_pnl: Price
    inputs_hash: str
    # Per-commodity provenance: {commodity: {value, source, settlement_date}}.
    # NULL when no market price was consulted (fixed-price-only deal,
    # no active hedges) OR for legacy pre-PR-8 rows (column added by
    # 030_pnl_provenance; never backfilled — see dispatch §3.4.3).
    price_references: Optional[dict] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class DealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str
    name: str
    commodity: str
    status: DealStatus
    total_physical_tons: MTQuantity
    total_hedge_tons: MTQuantity
    hedge_ratio: Price
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_deleted: bool


class DealDetailRead(DealRead):
    """Deal detail with links and latest P&L snapshot."""

    links: list[DealLinkRead] = []
    latest_pnl: Optional[DealPNLSnapshotRead] = None


class DealListResponse(BaseModel):
    items: list[DealRead]
    next_cursor: Optional[str] = None


class DealPNLHistoryResponse(BaseModel):
    items: list[DealPNLSnapshotRead]


# ---------------------------------------------------------------------------
# P&L Breakdown (batch computation with line-item detail)
# ---------------------------------------------------------------------------


class PnlBreakdownRequest(BaseModel):
    deal_ids: list[UUID] = []
    snapshot_date: date


class PnlPhysicalItem(BaseModel):
    id: UUID
    order_type: str  # "SO" / "PO"
    commodity: str
    quantity_mt: MTQuantity
    price: Price
    value: Price


class PnlFinancialItem(BaseModel):
    id: UUID
    reference: Optional[str] = None
    classification: str
    status: str
    quantity_mt: MTQuantity
    entry_price: Price
    market_price: Optional[Price] = None
    pnl: Price


class DealPnlBreakdown(BaseModel):
    deal_id: UUID
    deal_reference: str
    deal_name: str
    commodity: str
    physical_revenue: Price
    physical_cost: Price
    hedge_pnl_realized: Price
    hedge_pnl_mtm: Price
    total_pnl: Price
    physical_items: list[PnlPhysicalItem]
    financial_items: list[PnlFinancialItem]


class PnlBreakdownTotals(BaseModel):
    physical_revenue: Price
    physical_cost: Price
    hedge_pnl_realized: Price
    hedge_pnl_mtm: Price
    total_pnl: Price


class PnlBreakdownResponse(BaseModel):
    deals: list[DealPnlBreakdown]
    totals: PnlBreakdownTotals
