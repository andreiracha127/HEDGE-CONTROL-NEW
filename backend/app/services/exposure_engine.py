"""Exposure Engine service — reconciliation, net exposure, hedge tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.exposure import (
    Exposure,
    ExposureDirection,
    ExposureSourceType,
    ExposureStatus,
    HedgeTask,
    HedgeTaskAction,
    HedgeTaskStatus,
)
from app.models.linkages import HedgeOrderLinkage
from app.models.orders import Order, OrderType, PriceType


class ExposureEngineService:
    """Stateless service for the Exposure Engine."""

    # ------------------------------------------------------------------
    # reconcile_from_orders
    # ------------------------------------------------------------------

    @staticmethod
    def _get_linked_qty_map(session: Session) -> dict:
        """Return {order_id_str: total_linked_qty} from HedgeOrderLinkage."""
        rows = (
            session.query(
                HedgeOrderLinkage.order_id,
                func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0).label(
                    "linked_qty"
                ),
            )
            .group_by(HedgeOrderLinkage.order_id)
            .all()
        )
        return {str(r.order_id): float(r.linked_qty) for r in rows}

    @staticmethod
    def reconcile_from_orders(session: Session) -> dict:
        """Scan all active Orders and create / update Exposures.

        Computes open_tons = order.quantity_mt - linked hedge quantity.
        Returns a dict with ``created`` and ``updated`` counts.
        """
        created = 0
        updated = 0

        linked_map = ExposureEngineService._get_linked_qty_map(session)
        orders = session.query(Order).all()

        for order in orders:
            # ── Fixed-price orders have no market-price exposure ──
            if order.price_type == PriceType.fixed:
                continue

            # Map order type → exposure direction / source_type
            if order.order_type == OrderType.purchase:
                direction = ExposureDirection.long
                source_type = ExposureSourceType.purchase_order
            else:
                direction = ExposureDirection.short
                source_type = ExposureSourceType.sales_order

            # Compute hedge-adjusted open tons
            hedged_qty = linked_map.get(str(order.id), 0.0)
            open_qty = max(float(order.quantity_mt) - hedged_qty, 0.0)

            # Determine status based on hedging
            if hedged_qty <= 0:
                exp_status = ExposureStatus.open
            elif open_qty <= 0:
                exp_status = ExposureStatus.fully_hedged
            else:
                exp_status = ExposureStatus.partially_hedged

            # Check if exposure already exists for this order
            existing = (
                session.query(Exposure)
                .filter(
                    Exposure.source_id == order.id,
                    Exposure.is_deleted == False,  # noqa: E712
                )
                .first()
            )

            if existing:
                changed = False
                if float(existing.original_tons) != float(order.quantity_mt):
                    existing.original_tons = order.quantity_mt
                    changed = True
                if float(existing.open_tons) != open_qty:
                    existing.open_tons = open_qty
                    changed = True
                if existing.status != exp_status:
                    existing.status = exp_status
                    changed = True
                if changed:
                    updated += 1
            else:
                exposure = Exposure(
                    commodity="ALUMINUM",  # default commodity
                    direction=direction,
                    source_type=source_type,
                    source_id=order.id,
                    original_tons=order.quantity_mt,
                    open_tons=open_qty,
                    price_per_ton=order.avg_entry_price,
                    status=exp_status,
                )
                session.add(exposure)
                created += 1

        session.flush()
        return {
            "created": created,
            "updated": updated,
            "message": "Reconciliation completed",
        }

    # ------------------------------------------------------------------
    # compute_net_exposure
    # ------------------------------------------------------------------

    @staticmethod
    def compute_net_exposure(
        session: Session, commodity: str | None = None
    ) -> list[dict]:
        """Compute net exposure per commodity.

        Structure:
        - long_original / short_original: PO / SO original tons (commercial)
        - long_hedged / short_hedged: PO / SO hedged tons (commercial)
        - long_tons / short_tons: global hedge contract positions (not linked
          to any commercial order via HedgeOrderLinkage)
        - net_tons: overall net position.
          Convention: positive = Vendido (short), negative = Comprado (long).
          Formula: (SO_open - PO_open) + global_short - global_long
        """
        from app.models.contracts import HedgeContract, HedgeClassification

        # ── 1. Commercial exposures (from Exposure table) ──
        q = session.query(
            Exposure.commodity,
            Exposure.direction,
            func.coalesce(func.sum(Exposure.open_tons), 0).label("total_open"),
            func.coalesce(func.sum(Exposure.original_tons), 0).label("total_original"),
        ).filter(
            Exposure.is_deleted == False,  # noqa: E712
            Exposure.status.in_([ExposureStatus.open, ExposureStatus.partially_hedged]),
        )

        if commodity:
            q = q.filter(Exposure.commodity == commodity)

        q = q.group_by(Exposure.commodity, Exposure.direction)
        rows = q.all()

        # Aggregate commercial data by commodity (normalised to uppercase)
        agg: dict[str, dict] = {}
        for row in rows:
            c = row.commodity.upper() if row.commodity else row.commodity
            if c not in agg:
                agg[c] = {
                    "commodity": c,
                    "long_tons": 0.0,
                    "short_tons": 0.0,
                    "net_tons": 0.0,
                    "long_original": 0.0,
                    "short_original": 0.0,
                    "long_hedged": 0.0,
                    "short_hedged": 0.0,
                }
            open_val = float(row.total_open)
            original_val = float(row.total_original)
            hedged_val = original_val - open_val
            if row.direction == ExposureDirection.long:
                agg[c]["long_original"] += original_val
                agg[c]["long_hedged"] += hedged_val
            else:
                agg[c]["short_original"] += original_val
                agg[c]["short_hedged"] += hedged_val

        # ── 2. Global hedge contracts (not linked to any order) ──
        linked_contract_ids = (
            session.query(HedgeOrderLinkage.contract_id).distinct().scalar_subquery()
        )
        gq = session.query(
            HedgeContract.commodity,
            HedgeContract.classification,
            func.coalesce(func.sum(HedgeContract.quantity_mt), 0).label("total_qty"),
        ).filter(
            HedgeContract.deleted_at.is_(None),
            HedgeContract.status.in_(["active", "partially_settled"]),
            ~HedgeContract.id.in_(linked_contract_ids),
        )
        if commodity:
            gq = gq.filter(HedgeContract.commodity == commodity)
        gq = gq.group_by(HedgeContract.commodity, HedgeContract.classification)
        global_rows = gq.all()

        for grow in global_rows:
            c = grow.commodity.upper() if grow.commodity else grow.commodity
            if c not in agg:
                agg[c] = {
                    "commodity": c,
                    "long_tons": 0.0,
                    "short_tons": 0.0,
                    "net_tons": 0.0,
                    "long_original": 0.0,
                    "short_original": 0.0,
                    "long_hedged": 0.0,
                    "short_hedged": 0.0,
                }
            qty = float(grow.total_qty)
            if grow.classification == HedgeClassification.long:
                agg[c]["long_tons"] += qty
            else:
                agg[c]["short_tons"] += qty

        # ── 3. Net position (positive = Vendido/Short) ──
        for v in agg.values():
            so_open = v["short_original"] - v["short_hedged"]
            po_open = v["long_original"] - v["long_hedged"]
            v["net_tons"] = (so_open - po_open) + v["short_tons"] - v["long_tons"]

        return list(agg.values())

    # ------------------------------------------------------------------
    # create_hedge_tasks
    # ------------------------------------------------------------------

    @staticmethod
    def create_hedge_tasks(session: Session) -> int:
        """For open exposures, create pending HedgeTasks.

        Returns count of tasks created.
        """
        open_exposures = (
            session.query(Exposure)
            .filter(
                Exposure.is_deleted == False,  # noqa: E712
                Exposure.status == ExposureStatus.open,
                Exposure.open_tons > 0,
            )
            .all()
        )

        count = 0
        for exp in open_exposures:
            # Check if a pending task already exists for this exposure
            existing_task = (
                session.query(HedgeTask)
                .filter(
                    HedgeTask.exposure_id == exp.id,
                    HedgeTask.status == HedgeTaskStatus.pending,
                )
                .first()
            )
            if existing_task:
                continue

            task = HedgeTask(
                exposure_id=exp.id,
                recommended_tons=exp.open_tons,
                recommended_action=HedgeTaskAction.hedge_new,
                status=HedgeTaskStatus.pending,
            )
            session.add(task)
            count += 1

        session.flush()
        return count

    # ------------------------------------------------------------------
    # cancel_stale_tasks
    # ------------------------------------------------------------------

    @staticmethod
    def cancel_stale_tasks(session: Session) -> int:
        """Cancel pending tasks whose exposures are fully hedged or cancelled.

        Returns count of tasks cancelled.
        """
        stale_tasks = (
            session.query(HedgeTask)
            .join(Exposure, HedgeTask.exposure_id == Exposure.id)
            .filter(
                HedgeTask.status == HedgeTaskStatus.pending,
                Exposure.status.in_(
                    [ExposureStatus.fully_hedged, ExposureStatus.cancelled]
                ),
            )
            .all()
        )

        count = 0
        for task in stale_tasks:
            task.status = HedgeTaskStatus.cancelled
            count += 1

        session.flush()
        return count

    # ------------------------------------------------------------------
    # list_pending_tasks
    # ------------------------------------------------------------------

    @staticmethod
    def list_pending_tasks(
        session: Session,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list, str | None]:
        from app.core.pagination import paginate

        q = (
            session.query(HedgeTask)
            .filter(HedgeTask.status == HedgeTaskStatus.pending)
            .order_by(HedgeTask.created_at.desc())
        )
        return paginate(
            q,
            created_at_col=HedgeTask.created_at,
            id_col=HedgeTask.id,
            cursor=cursor,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # execute_task
    # ------------------------------------------------------------------

    @staticmethod
    def execute_task(session: Session, task_id) -> HedgeTask:
        task = session.query(HedgeTask).filter(HedgeTask.id == task_id).first()
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="HedgeTask not found"
            )
        if task.status != HedgeTaskStatus.pending:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Task is already {task.status.value}",
            )
        task.status = HedgeTaskStatus.executed
        task.executed_at = datetime.now(timezone.utc)
        session.flush()
        session.refresh(task)
        return task

    # ------------------------------------------------------------------
    # list_exposures
    # ------------------------------------------------------------------

    @staticmethod
    def list_exposures(
        session: Session,
        *,
        commodity: str | None = None,
        status_filter: str | None = None,
        settlement_month: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list, str | None]:
        from app.core.pagination import paginate

        q = session.query(Exposure).filter(Exposure.is_deleted == False)  # noqa: E712
        if commodity:
            q = q.filter(Exposure.commodity == commodity)
        if status_filter:
            q = q.filter(Exposure.status == ExposureStatus(status_filter))
        if settlement_month:
            q = q.filter(Exposure.settlement_month == settlement_month)
        q = q.order_by(Exposure.created_at.desc())
        return paginate(
            q,
            created_at_col=Exposure.created_at,
            id_col=Exposure.id,
            cursor=cursor,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # get_exposure
    # ------------------------------------------------------------------

    @staticmethod
    def get_exposure(session: Session, exposure_id) -> Exposure:
        exp = (
            session.query(Exposure)
            .filter(
                Exposure.id == exposure_id,
                Exposure.is_deleted == False,  # noqa: E712
            )
            .first()
        )
        if not exp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Exposure not found",
            )
        return exp
