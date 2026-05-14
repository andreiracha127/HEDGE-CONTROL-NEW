"""Exposure calculation service.

Centralises commercial and global exposure computation so that both
``exposures.py`` routes and ``rfq_service.py`` share a single source of truth.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.core.utils import now_utc

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.contracts import HedgeClassification, HedgeContract, HedgeContractStatus
from app.models.linkages import HedgeOrderLinkage
from app.models.orders import Order, OrderType, PriceType
from app.core.precision import quantize_mt
from app.schemas.exposure import CommercialExposureRead, GlobalExposureRead
from app.services.price_lookup_service import canonical_commodity


class _ExposureContractLike(Protocol):
    id: object
    commodity: str
    quantity_mt: Decimal
    classification: HedgeClassification


def _to_decimal(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def compute_commercial_exposure_pure(
    *,
    orders: list[tuple[Order, Decimal]],
    linkages: list[HedgeOrderLinkage],
    calculation_timestamp: datetime,
) -> list[CommercialExposureRead]:
    """Pure aggregation of commercial exposure rows over caller-shaped inputs."""
    linked_by_order: dict[object, Decimal] = {}
    for linkage in linkages:
        linked_by_order[linkage.order_id] = linked_by_order.get(
            linkage.order_id, Decimal("0")
        ) + _to_decimal(linkage.quantity_mt)

    rows: dict[str, dict[str, Decimal | int]] = {}

    def ensure_row(commodity: str) -> dict[str, Decimal | int]:
        key = canonical_commodity(commodity) or commodity
        if key not in rows:
            rows[key] = {
                "pre_active": Decimal("0"),
                "pre_passive": Decimal("0"),
                "residual_active": Decimal("0"),
                "residual_passive": Decimal("0"),
                "reduction_active": Decimal("0"),
                "reduction_passive": Decimal("0"),
                "order_count": 0,
            }
        return rows[key]

    for order, raw_quantity in orders:
        if order.price_type != PriceType.variable:
            continue

        quantity = _to_decimal(raw_quantity)
        item = ensure_row(order.commodity)
        item["order_count"] = int(item["order_count"]) + 1
        linked_qty = linked_by_order.get(order.id, Decimal("0"))
        residual = quantity - linked_qty
        if quantize_mt(residual) < Decimal("0"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Residual exposure cannot be negative",
            )

        if order.order_type == OrderType.sales:
            item["pre_active"] = Decimal(item["pre_active"]) + quantity
            item["residual_active"] = Decimal(item["residual_active"]) + residual
            item["reduction_active"] = Decimal(item["reduction_active"]) + linked_qty
        else:
            item["pre_passive"] = Decimal(item["pre_passive"]) + quantity
            item["residual_passive"] = Decimal(item["residual_passive"]) + residual
            item["reduction_passive"] = Decimal(item["reduction_passive"]) + linked_qty

    result: list[CommercialExposureRead] = []
    for commodity in sorted(rows):
        item = rows[commodity]
        residual_active = quantize_mt(item["residual_active"])
        residual_passive = quantize_mt(item["residual_passive"])
        result.append(
            CommercialExposureRead(
                commodity=commodity,
                pre_reduction_commercial_active_mt=quantize_mt(item["pre_active"]),
                pre_reduction_commercial_passive_mt=quantize_mt(item["pre_passive"]),
                reduction_applied_active_mt=quantize_mt(item["reduction_active"]),
                reduction_applied_passive_mt=quantize_mt(item["reduction_passive"]),
                commercial_active_mt=residual_active,
                commercial_passive_mt=residual_passive,
                commercial_net_mt=quantize_mt(residual_active - residual_passive),
                calculation_timestamp=calculation_timestamp,
                order_count_considered=int(item["order_count"]),
            )
        )
    return result


def compute_global_exposure_pure(
    *,
    orders: list[tuple[Order, Decimal]],
    contracts: list[_ExposureContractLike],
    virtual_contracts: list[_ExposureContractLike],
    linkages: list[HedgeOrderLinkage],
    calculation_timestamp: datetime,
) -> list[GlobalExposureRead]:
    """Pure aggregation of global exposure rows over caller-shaped inputs."""
    linked_by_order: dict[object, Decimal] = {}
    linked_by_contract: dict[object, Decimal] = {}
    for linkage in linkages:
        quantity = _to_decimal(linkage.quantity_mt)
        linked_by_order[linkage.order_id] = linked_by_order.get(
            linkage.order_id, Decimal("0")
        ) + quantity
        linked_by_contract[linkage.contract_id] = linked_by_contract.get(
            linkage.contract_id, Decimal("0")
        ) + quantity

    rows: dict[str, dict[str, Decimal | int]] = {}

    def ensure_row(commodity: str) -> dict[str, Decimal | int]:
        key = canonical_commodity(commodity) or commodity
        if key not in rows:
            rows[key] = {
                "pre_active": Decimal("0"),
                "pre_passive": Decimal("0"),
                "reduced_active": Decimal("0"),
                "reduced_passive": Decimal("0"),
                "total_hedge_long": Decimal("0"),
                "total_hedge_short": Decimal("0"),
                "unlinked_hedge_long": Decimal("0"),
                "unlinked_hedge_short": Decimal("0"),
                "entities_count": 0,
            }
        return rows[key]

    for order, raw_quantity in orders:
        if order.price_type != PriceType.variable:
            continue

        quantity = _to_decimal(raw_quantity)
        item = ensure_row(order.commodity)
        item["entities_count"] = int(item["entities_count"]) + 1
        linked_qty = linked_by_order.get(order.id, Decimal("0"))
        residual = quantity - linked_qty
        if quantize_mt(residual) < Decimal("0"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Residual exposure cannot be negative",
            )

        if order.order_type == OrderType.sales:
            item["pre_active"] = Decimal(item["pre_active"]) + quantity
            item["reduced_active"] = Decimal(item["reduced_active"]) + residual
        else:
            item["pre_passive"] = Decimal(item["pre_passive"]) + quantity
            item["reduced_passive"] = Decimal(item["reduced_passive"]) + residual

    for contract in [*contracts, *virtual_contracts]:
        item = ensure_row(contract.commodity)
        item["entities_count"] = int(item["entities_count"]) + 1
        total_qty = _to_decimal(contract.quantity_mt)
        linked_qty = linked_by_contract.get(contract.id, Decimal("0"))
        residual = total_qty - linked_qty
        if quantize_mt(residual) < Decimal("0"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Residual hedge quantity cannot be negative",
            )

        if contract.classification == HedgeClassification.long:
            item["total_hedge_long"] = (
                Decimal(item["total_hedge_long"]) + total_qty
            )
            item["unlinked_hedge_long"] = (
                Decimal(item["unlinked_hedge_long"]) + residual
            )
        else:
            item["total_hedge_short"] = (
                Decimal(item["total_hedge_short"]) + total_qty
            )
            item["unlinked_hedge_short"] = (
                Decimal(item["unlinked_hedge_short"]) + residual
            )

    result: list[GlobalExposureRead] = []
    for commodity in sorted(rows):
        item = rows[commodity]
        pre_global_active = Decimal(item["pre_active"]) + Decimal(
            item["total_hedge_short"]
        )
        pre_global_passive = Decimal(item["pre_passive"]) + Decimal(
            item["total_hedge_long"]
        )
        post_global_active = Decimal(item["reduced_active"]) + Decimal(
            item["unlinked_hedge_short"]
        )
        post_global_passive = Decimal(item["reduced_passive"]) + Decimal(
            item["unlinked_hedge_long"]
        )
        result.append(
            GlobalExposureRead(
                commodity=commodity,
                pre_reduction_global_active_mt=quantize_mt(pre_global_active),
                pre_reduction_global_passive_mt=quantize_mt(pre_global_passive),
                reduction_applied_active_mt=quantize_mt(
                    pre_global_active - post_global_active
                ),
                reduction_applied_passive_mt=quantize_mt(
                    pre_global_passive - post_global_passive
                ),
                global_active_mt=quantize_mt(post_global_active),
                global_passive_mt=quantize_mt(post_global_passive),
                global_net_mt=quantize_mt(post_global_active - post_global_passive),
                commercial_active_mt=quantize_mt(item["reduced_active"]),
                commercial_passive_mt=quantize_mt(item["reduced_passive"]),
                hedge_long_mt=quantize_mt(item["unlinked_hedge_long"]),
                hedge_short_mt=quantize_mt(item["unlinked_hedge_short"]),
                calculation_timestamp=calculation_timestamp,
                entities_count_considered=int(item["entities_count"]),
            )
        )
    return result


class ExposureService:
    """Stateless service for exposure snapshots."""

    # ------------------------------------------------------------------
    # Helpers (shared between commercial & global)
    # ------------------------------------------------------------------

    @staticmethod
    def _linked_by_order_subquery(session: Session):
        """Subquery: total linked qty per order, counting only linkages whose
        hedge contract is still live (active / partially_settled, not deleted).

        Hedge-side filter only — the order-side filter is upstream of every
        consumer (compute_commercial_snapshot already filters
        Order.deleted_at IS NULL per §3.1), so this stays focused on the
        hedge-side lifecycle which has no upstream filter (§3.4).
        """
        return (
            session.query(
                HedgeOrderLinkage.order_id.label("order_id"),
                func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0).label(
                    "linked_qty"
                ),
            )
            .join(HedgeContract, HedgeContract.id == HedgeOrderLinkage.contract_id)
            .filter(
                HedgeContract.deleted_at.is_(None),
                HedgeContract.status.in_(
                    [HedgeContractStatus.active, HedgeContractStatus.partially_settled]
                ),
            )
            .group_by(HedgeOrderLinkage.order_id)
            .subquery()
        )

    @staticmethod
    def _validate_residuals_non_negative(
        session: Session,
        residual_expr,
        linked_subquery,
        join_left,
        join_right,
        *filters,
        error_detail: str = "Residual exposure cannot be negative",
    ) -> None:
        q = session.query(func.min(residual_expr)).outerjoin(
            linked_subquery, join_left == join_right
        )
        for f in filters:
            q = q.filter(f)
        min_val = q.scalar()
        if min_val is not None and quantize_mt(min_val) < Decimal("0"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail,
            )

    # ------------------------------------------------------------------
    # Commercial snapshot
    # ------------------------------------------------------------------

    @staticmethod
    def compute_commercial_snapshot(session: Session) -> list[dict]:
        """Return commercial exposure rows by commodity."""
        orders = [
            (order, _to_decimal(order.quantity_mt))
            for order in (
                session.query(Order)
                .filter(
                    Order.price_type == PriceType.variable,
                    Order.deleted_at.is_(None),
                )
                .order_by(Order.created_at.asc())
                .all()
            )
        ]
        linkages = (
            session.query(HedgeOrderLinkage)
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
        return [
            row.model_dump()
            for row in compute_commercial_exposure_pure(
                orders=orders,
                linkages=linkages,
                calculation_timestamp=now_utc(),
            )
        ]

    # ------------------------------------------------------------------
    # Global snapshot
    # ------------------------------------------------------------------

    @staticmethod
    def compute_global_snapshot(session: Session) -> list[dict]:
        """Return global exposure rows by commodity (orders + hedge contracts).

        Mapping:
        - Short hedge → contributes to global **active** side (selling exposure)
        - Long hedge  → contributes to global **passive** side (buying exposure)
        """
        orders = [
            (order, _to_decimal(order.quantity_mt))
            for order in (
                session.query(Order)
                .filter(
                    Order.price_type == PriceType.variable,
                    Order.deleted_at.is_(None),
                )
                .order_by(Order.created_at.asc())
                .all()
            )
        ]
        contracts = (
            session.query(HedgeContract)
            .filter(
                HedgeContract.deleted_at.is_(None),
                HedgeContract.status.in_(
                    [HedgeContractStatus.active, HedgeContractStatus.partially_settled]
                ),
            )
            .order_by(HedgeContract.created_at.asc())
            .all()
        )
        linkages = (
            session.query(HedgeOrderLinkage)
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
        return [
            row.model_dump()
            for row in compute_global_exposure_pure(
                orders=orders,
                contracts=contracts,
                virtual_contracts=[],
                linkages=linkages,
                calculation_timestamp=now_utc(),
            )
        ]
