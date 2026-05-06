"""Exposure calculation service.

Centralises commercial and global exposure computation so that both
``exposures.py`` routes and ``rfq_service.py`` share a single source of truth.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.core.utils import now_utc

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.contracts import HedgeClassification, HedgeContract
from app.models.linkages import HedgeOrderLinkage
from app.models.orders import Order, OrderType, PriceType
from app.core.precision import quantize_mt


class ExposureService:
    """Stateless service for exposure snapshots."""

    # ------------------------------------------------------------------
    # Helpers (shared between commercial & global)
    # ------------------------------------------------------------------

    @staticmethod
    def _linked_by_order_subquery(session: Session):
        """Subquery: total linked qty per order."""
        return (
            session.query(
                HedgeOrderLinkage.order_id.label("order_id"),
                func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0).label(
                    "linked_qty"
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
    def compute_commercial_snapshot(session: Session) -> dict:
        """Return commercial exposure dict (variable-price orders only)."""
        pre_active = quantize_mt(
            session.query(func.coalesce(func.sum(Order.quantity_mt), 0.0))
            .filter(
                Order.order_type == OrderType.sales,
                Order.price_type == PriceType.variable,
            )
            .scalar()
            or Decimal("0")
        )
        pre_passive = quantize_mt(
            session.query(func.coalesce(func.sum(Order.quantity_mt), 0.0))
            .filter(
                Order.order_type == OrderType.purchase,
                Order.price_type == PriceType.variable,
            )
            .scalar()
            or Decimal("0")
        )

        linked = ExposureService._linked_by_order_subquery(session)
        residual_qty = Order.quantity_mt - func.coalesce(linked.c.linked_qty, 0.0)

        # Validate no negative residuals
        ExposureService._validate_residuals_non_negative(
            session,
            residual_qty,
            linked,
            Order.id,
            linked.c.order_id,
            Order.price_type == PriceType.variable,
        )

        residual_active = quantize_mt(
            session.query(func.coalesce(func.sum(residual_qty), 0.0))
            .outerjoin(linked, Order.id == linked.c.order_id)
            .filter(
                Order.order_type == OrderType.sales,
                Order.price_type == PriceType.variable,
            )
            .scalar()
            or Decimal("0")
        )
        residual_passive = quantize_mt(
            session.query(func.coalesce(func.sum(residual_qty), 0.0))
            .outerjoin(linked, Order.id == linked.c.order_id)
            .filter(
                Order.order_type == OrderType.purchase,
                Order.price_type == PriceType.variable,
            )
            .scalar()
            or Decimal("0")
        )

        reduction_active = quantize_mt(
            session.query(func.coalesce(func.sum(linked.c.linked_qty), 0.0))
            .select_from(Order)
            .outerjoin(linked, Order.id == linked.c.order_id)
            .filter(
                Order.order_type == OrderType.sales,
                Order.price_type == PriceType.variable,
            )
            .scalar()
            or Decimal("0")
        )
        reduction_passive = quantize_mt(
            session.query(func.coalesce(func.sum(linked.c.linked_qty), 0.0))
            .select_from(Order)
            .outerjoin(linked, Order.id == linked.c.order_id)
            .filter(
                Order.order_type == OrderType.purchase,
                Order.price_type == PriceType.variable,
            )
            .scalar()
            or Decimal("0")
        )

        order_count = int(
            session.query(func.count(Order.id))
            .filter(Order.price_type == PriceType.variable)
            .scalar()
            or 0
        )

        return {
            "pre_reduction_commercial_active_mt": pre_active,
            "pre_reduction_commercial_passive_mt": pre_passive,
            "reduction_applied_active_mt": reduction_active,
            "reduction_applied_passive_mt": reduction_passive,
            "commercial_active_mt": residual_active,
            "commercial_passive_mt": residual_passive,
            "commercial_net_mt": quantize_mt(residual_active - residual_passive),
            "calculation_timestamp": now_utc(),
            "order_count_considered": order_count,
        }

    # ------------------------------------------------------------------
    # Global snapshot
    # ------------------------------------------------------------------

    @staticmethod
    def compute_global_snapshot(session: Session) -> dict:
        """Return global exposure dict (orders + hedge contracts).

        Mapping:
        - Short hedge → contributes to global **active** side (selling exposure)
        - Long hedge  → contributes to global **passive** side (buying exposure)
        """

        # --- Commercial (variable-price orders) ---
        pre_commercial_active = quantize_mt(
            session.query(func.coalesce(func.sum(Order.quantity_mt), 0.0))
            .filter(
                Order.order_type == OrderType.sales,
                Order.price_type == PriceType.variable,
            )
            .scalar()
            or Decimal("0")
        )
        pre_commercial_passive = quantize_mt(
            session.query(func.coalesce(func.sum(Order.quantity_mt), 0.0))
            .filter(
                Order.order_type == OrderType.purchase,
                Order.price_type == PriceType.variable,
            )
            .scalar()
            or Decimal("0")
        )

        linked_by_order = ExposureService._linked_by_order_subquery(session)
        residual_order_qty = Order.quantity_mt - func.coalesce(
            linked_by_order.c.linked_qty, 0.0
        )

        ExposureService._validate_residuals_non_negative(
            session,
            residual_order_qty,
            linked_by_order,
            Order.id,
            linked_by_order.c.order_id,
            Order.price_type == PriceType.variable,
        )

        commercial_active = quantize_mt(
            session.query(func.coalesce(func.sum(residual_order_qty), 0.0))
            .outerjoin(linked_by_order, Order.id == linked_by_order.c.order_id)
            .filter(
                Order.order_type == OrderType.sales,
                Order.price_type == PriceType.variable,
            )
            .scalar()
            or Decimal("0")
        )
        commercial_passive = quantize_mt(
            session.query(func.coalesce(func.sum(residual_order_qty), 0.0))
            .outerjoin(linked_by_order, Order.id == linked_by_order.c.order_id)
            .filter(
                Order.order_type == OrderType.purchase,
                Order.price_type == PriceType.variable,
            )
            .scalar()
            or Decimal("0")
        )

        # --- Hedge contracts ---
        linked_by_contract = (
            session.query(
                HedgeOrderLinkage.contract_id.label("contract_id"),
                func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0).label(
                    "linked_qty"
                ),
            )
            .group_by(HedgeOrderLinkage.contract_id)
            .subquery()
        )

        residual_contract_qty = HedgeContract.quantity_mt - func.coalesce(
            linked_by_contract.c.linked_qty, 0.0
        )

        min_contract_residual = (
            session.query(func.min(residual_contract_qty))
            .outerjoin(
                linked_by_contract, HedgeContract.id == linked_by_contract.c.contract_id
            )
            .scalar()
        )
        if (
            min_contract_residual is not None
            and quantize_mt(min_contract_residual) < Decimal("0")
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Residual hedge quantity cannot be negative",
            )

        hedge_long = quantize_mt(
            session.query(func.coalesce(func.sum(residual_contract_qty), 0.0))
            .outerjoin(
                linked_by_contract, HedgeContract.id == linked_by_contract.c.contract_id
            )
            .filter(HedgeContract.classification == HedgeClassification.long)
            .scalar()
            or Decimal("0")
        )
        hedge_short = quantize_mt(
            session.query(func.coalesce(func.sum(residual_contract_qty), 0.0))
            .outerjoin(
                linked_by_contract, HedgeContract.id == linked_by_contract.c.contract_id
            )
            .filter(HedgeContract.classification == HedgeClassification.short)
            .scalar()
            or Decimal("0")
        )

        total_hedge_long = quantize_mt(
            session.query(func.coalesce(func.sum(HedgeContract.quantity_mt), 0.0))
            .filter(HedgeContract.classification == HedgeClassification.long)
            .scalar()
            or Decimal("0")
        )
        total_hedge_short = quantize_mt(
            session.query(func.coalesce(func.sum(HedgeContract.quantity_mt), 0.0))
            .filter(HedgeContract.classification == HedgeClassification.short)
            .scalar()
            or Decimal("0")
        )

        # --- Counts ---
        order_count = int(
            session.query(func.count(Order.id))
            .filter(Order.price_type == PriceType.variable)
            .scalar()
            or 0
        )
        hedge_count = int(session.query(func.count(HedgeContract.id)).scalar() or 0)

        # --- Derived values ---
        # Short hedges → active side; Long hedges → passive side
        commercial_reduction_active = quantize_mt(
            pre_commercial_active - commercial_active
        )
        commercial_reduction_passive = quantize_mt(
            pre_commercial_passive - commercial_passive
        )
        hedge_reduction_short = quantize_mt(total_hedge_short - hedge_short)
        hedge_reduction_long = quantize_mt(total_hedge_long - hedge_long)

        global_active = quantize_mt(commercial_active + hedge_short)
        global_passive = quantize_mt(commercial_passive + hedge_long)
        pre_global_active = quantize_mt(pre_commercial_active + total_hedge_short)
        pre_global_passive = quantize_mt(pre_commercial_passive + total_hedge_long)
        reduction_active = quantize_mt(commercial_reduction_active + hedge_reduction_short)
        reduction_passive = quantize_mt(
            commercial_reduction_passive + hedge_reduction_long
        )

        return {
            "pre_reduction_global_active_mt": pre_global_active,
            "pre_reduction_global_passive_mt": pre_global_passive,
            "reduction_applied_active_mt": reduction_active,
            "reduction_applied_passive_mt": reduction_passive,
            "global_active_mt": global_active,
            "global_passive_mt": global_passive,
            "global_net_mt": quantize_mt(global_active - global_passive),
            "commercial_active_mt": commercial_active,
            "commercial_passive_mt": commercial_passive,
            "hedge_long_mt": hedge_long,
            "hedge_short_mt": hedge_short,
            "calculation_timestamp": now_utc(),
            "entities_count_considered": order_count + hedge_count,
        }
