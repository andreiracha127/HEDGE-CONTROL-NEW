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
from app.services.price_lookup_service import canonical_commodity


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
    def compute_commercial_snapshot(session: Session) -> list[dict]:
        """Return commercial exposure rows by commodity."""
        rows: dict[str, dict] = {}

        def ensure_row(commodity: str) -> dict:
            commodity = canonical_commodity(commodity) or commodity
            if commodity not in rows:
                rows[commodity] = {
                    "commodity": commodity,
                    "pre_reduction_commercial_active_mt": Decimal("0.000"),
                    "pre_reduction_commercial_passive_mt": Decimal("0.000"),
                    "reduction_applied_active_mt": Decimal("0.000"),
                    "reduction_applied_passive_mt": Decimal("0.000"),
                    "commercial_active_mt": Decimal("0.000"),
                    "commercial_passive_mt": Decimal("0.000"),
                    "commercial_net_mt": Decimal("0.000"),
                    "calculation_timestamp": now_utc(),
                    "order_count_considered": 0,
                }
            return rows[commodity]

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

        pre_rows = (
            session.query(
                Order.commodity,
                Order.order_type,
                func.coalesce(func.sum(Order.quantity_mt), 0.0).label("quantity"),
                func.count(Order.id).label("order_count"),
            )
            .filter(Order.price_type == PriceType.variable)
            .group_by(Order.commodity, Order.order_type)
            .all()
        )
        for row in pre_rows:
            item = ensure_row(row.commodity)
            if row.order_type == OrderType.sales:
                item["pre_reduction_commercial_active_mt"] += quantize_mt(row.quantity)
            else:
                item["pre_reduction_commercial_passive_mt"] += quantize_mt(
                    row.quantity
                )
            item["order_count_considered"] += int(row.order_count)

        residual_rows = (
            session.query(
                Order.commodity,
                Order.order_type,
                func.coalesce(func.sum(residual_qty), 0.0).label("quantity"),
            )
            .outerjoin(linked, Order.id == linked.c.order_id)
            .filter(Order.price_type == PriceType.variable)
            .group_by(Order.commodity, Order.order_type)
            .all()
        )
        for row in residual_rows:
            item = ensure_row(row.commodity)
            if row.order_type == OrderType.sales:
                item["commercial_active_mt"] += quantize_mt(row.quantity)
            else:
                item["commercial_passive_mt"] += quantize_mt(row.quantity)

        reduction_rows = (
            session.query(
                Order.commodity,
                Order.order_type,
                func.coalesce(func.sum(linked.c.linked_qty), 0.0).label("quantity"),
            )
            .select_from(Order)
            .outerjoin(linked, Order.id == linked.c.order_id)
            .filter(Order.price_type == PriceType.variable)
            .group_by(Order.commodity, Order.order_type)
            .all()
        )
        for row in reduction_rows:
            item = ensure_row(row.commodity)
            if row.order_type == OrderType.sales:
                item["reduction_applied_active_mt"] += quantize_mt(row.quantity)
            else:
                item["reduction_applied_passive_mt"] += quantize_mt(row.quantity)

        for item in rows.values():
            item["commercial_net_mt"] = quantize_mt(
                item["commercial_active_mt"] - item["commercial_passive_mt"]
            )

        return [rows[key] for key in sorted(rows)]

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
        rows: dict[str, dict] = {}

        def ensure_row(commodity: str) -> dict:
            commodity = canonical_commodity(commodity) or commodity
            if commodity not in rows:
                rows[commodity] = {
                    "commodity": commodity,
                    "pre_reduction_global_active_mt": Decimal("0.000"),
                    "pre_reduction_global_passive_mt": Decimal("0.000"),
                    "reduction_applied_active_mt": Decimal("0.000"),
                    "reduction_applied_passive_mt": Decimal("0.000"),
                    "global_active_mt": Decimal("0.000"),
                    "global_passive_mt": Decimal("0.000"),
                    "global_net_mt": Decimal("0.000"),
                    "commercial_active_mt": Decimal("0.000"),
                    "commercial_passive_mt": Decimal("0.000"),
                    "hedge_long_mt": Decimal("0.000"),
                    "hedge_short_mt": Decimal("0.000"),
                    "calculation_timestamp": now_utc(),
                    "entities_count_considered": 0,
                }
            return rows[commodity]

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

        pre_order_rows = (
            session.query(
                Order.commodity,
                Order.order_type,
                func.coalesce(func.sum(Order.quantity_mt), 0.0).label("quantity"),
                func.count(Order.id).label("order_count"),
            )
            .filter(Order.price_type == PriceType.variable)
            .group_by(Order.commodity, Order.order_type)
            .all()
        )
        for row in pre_order_rows:
            item = ensure_row(row.commodity)
            if row.order_type == OrderType.sales:
                item["pre_reduction_global_active_mt"] += quantize_mt(row.quantity)
            else:
                item["pre_reduction_global_passive_mt"] += quantize_mt(row.quantity)
            item["entities_count_considered"] += int(row.order_count)

        residual_order_rows = (
            session.query(
                Order.commodity,
                Order.order_type,
                func.coalesce(func.sum(residual_order_qty), 0.0).label("quantity"),
            )
            .outerjoin(linked_by_order, Order.id == linked_by_order.c.order_id)
            .filter(Order.price_type == PriceType.variable)
            .group_by(Order.commodity, Order.order_type)
            .all()
        )
        for row in residual_order_rows:
            item = ensure_row(row.commodity)
            if row.order_type == OrderType.sales:
                item["commercial_active_mt"] += quantize_mt(row.quantity)
            else:
                item["commercial_passive_mt"] += quantize_mt(row.quantity)

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

        residual_hedge_rows = (
            session.query(
                HedgeContract.commodity,
                HedgeContract.classification,
                func.coalesce(func.sum(residual_contract_qty), 0.0).label("quantity"),
            )
            .outerjoin(
                linked_by_contract, HedgeContract.id == linked_by_contract.c.contract_id
            )
            .group_by(HedgeContract.commodity, HedgeContract.classification)
            .all()
        )
        for row in residual_hedge_rows:
            item = ensure_row(row.commodity)
            if row.classification == HedgeClassification.long:
                item["hedge_long_mt"] += quantize_mt(row.quantity)
            else:
                item["hedge_short_mt"] += quantize_mt(row.quantity)

        total_hedge_rows = (
            session.query(
                HedgeContract.commodity,
                HedgeContract.classification,
                func.coalesce(func.sum(HedgeContract.quantity_mt), 0.0).label(
                    "quantity"
                ),
                func.count(HedgeContract.id).label("hedge_count"),
            )
            .group_by(HedgeContract.commodity, HedgeContract.classification)
            .all()
        )
        for row in total_hedge_rows:
            item = ensure_row(row.commodity)
            if row.classification == HedgeClassification.long:
                item["pre_reduction_global_passive_mt"] += quantize_mt(row.quantity)
            else:
                item["pre_reduction_global_active_mt"] += quantize_mt(row.quantity)
            item["entities_count_considered"] += int(row.hedge_count)

        for item in rows.values():
            item["global_active_mt"] = quantize_mt(
                item["commercial_active_mt"] + item["hedge_short_mt"]
            )
            item["global_passive_mt"] = quantize_mt(
                item["commercial_passive_mt"] + item["hedge_long_mt"]
            )
            item["reduction_applied_active_mt"] = quantize_mt(
                item["pre_reduction_global_active_mt"] - item["global_active_mt"]
            )
            item["reduction_applied_passive_mt"] = quantize_mt(
                item["pre_reduction_global_passive_mt"] - item["global_passive_mt"]
            )
            item["global_net_mt"] = quantize_mt(
                item["global_active_mt"] - item["global_passive_mt"]
            )

        return [rows[key] for key in sorted(rows)]
