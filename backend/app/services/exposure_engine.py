"""Exposure Engine service — reconciliation, net exposure, hedge tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.contracts import HedgeClassification, HedgeContract, HedgeContractStatus
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
from app.models.reconciliation_run import (
    ReconciliationRun,
    ReconciliationRunStatus,
)
from app.core.precision import quantize_mt
from app.core.utils import now_utc
from app.services.price_lookup_service import canonical_commodity, commodity_aliases


class ExposureOverAllocationError(Exception):
    """Raised by reconcile when linked qty exceeds order qty (constitution §2.6).

    Replaces the previous silent ``max(open, 0)`` clamp. Carries the offending
    order id and the exact over-allocation amount so the caller can audit /
    surface the violation.
    """

    def __init__(self, order_id, linked_qty: Decimal, order_qty: Decimal) -> None:
        self.order_id = order_id
        self.linked_qty = linked_qty
        self.order_qty = order_qty
        self.over_allocation = quantize_mt(linked_qty - order_qty)
        super().__init__(
            f"Exposure would be over-allocated for order {order_id}: "
            f"linked={linked_qty} MT exceeds order quantity={order_qty} MT "
            f"by {self.over_allocation} MT"
        )


class ExposureEngineService:
    """Stateless service for the Exposure Engine."""

    # ------------------------------------------------------------------
    # reconcile_from_orders
    # ------------------------------------------------------------------

    @staticmethod
    def _get_linked_qty_map(session: Session) -> dict:
        """Return ``{str(order_id): total_linked_qty}`` from HedgeOrderLinkage.

        §3.9 dual-filter: only linkages whose hedge contract AND source order
        are both live count toward an order's hedged quantity. Mirrors
        ExposureService's §3.5 ``linked_by_contract`` for cross-consumer
        parity required by J-A1-OPUS-02.

        Keys are stringified — ``reconcile_from_orders`` calls
        ``linked_map.get(str(order.id), Decimal("0"))``; UUID keys would
        silently miss every lookup and inflate Exposure.open_tons.
        """
        rows = (
            session.query(
                HedgeOrderLinkage.order_id,
                func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0).label(
                    "linked_qty"
                ),
            )
            .join(HedgeContract, HedgeContract.id == HedgeOrderLinkage.contract_id)
            .join(Order, Order.id == HedgeOrderLinkage.order_id)
            .filter(
                HedgeContract.deleted_at.is_(None),
                HedgeContract.status.in_(
                    [HedgeContractStatus.active, HedgeContractStatus.partially_settled]
                ),
                Order.deleted_at.is_(None),
            )
            .group_by(HedgeOrderLinkage.order_id)
            .all()
        )
        return {str(r.order_id): quantize_mt(r.linked_qty) for r in rows}

    @staticmethod
    def reconcile_from_orders(
        session: Session,
    ) -> tuple[ReconciliationRun, dict]:
        """Scan all active Orders and create / update Exposures.

        Computes open_tons = order.quantity_mt - linked hedge quantity.
        Persists a ``ReconciliationRun`` row at the start (anchor for the
        signed audit event emitted by the route) and updates it with the
        run summary on success. Returns ``(run, summary)``.

        On failure the surrounding ``unit_of_work`` rolls the run row back
        together with any partial Exposure mutations — no orphan anchor.
        """
        run = ReconciliationRun(status=ReconciliationRunStatus.running)
        session.add(run)
        # ``flush`` so ``run.id`` is generated and visible to the caller
        # (the route uses it as the audit ``entity_id`` anchor).
        session.flush()
        session.refresh(run)

        created = 0
        updated = 0

        linked_map = ExposureEngineService._get_linked_qty_map(session)
        # §3.7: only live (not soft-deleted) orders feed new/updated Exposure
        # rows. Pre-existing rows whose source order has since been
        # soft-deleted are retired by the §3.8 sweep below.
        orders = session.query(Order).filter(Order.deleted_at.is_(None)).all()

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
            commodity = canonical_commodity(order.commodity) or order.commodity

            # Compute hedge-adjusted open tons
            hedged_qty = quantize_mt(linked_map.get(str(order.id), Decimal("0")))
            order_qty = quantize_mt(order.quantity_mt)

            # ── Constitution §2.6 hard-fail (J-A1-OPUS-01) ────────────────
            # Previously this branch silently clamped a negative residual via
            # ``max(order_qty - hedged_qty, 0)`` and mapped it to
            # ``fully_hedged``, hiding the over-allocation. Per §2.6 an
            # over-allocated exposure is a hard-fail: raise explicitly and
            # leave no Exposure row behind (route-level rollback handles it
            # because the service flush is part of the unit_of_work).
            if hedged_qty > order_qty:
                raise ExposureOverAllocationError(
                    order_id=order.id,
                    linked_qty=hedged_qty,
                    order_qty=order_qty,
                )

            open_qty = quantize_mt(order_qty - hedged_qty)

            # Determine status based on hedging
            if hedged_qty <= Decimal("0"):
                exp_status = ExposureStatus.open
            elif open_qty <= Decimal("0"):
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
                if quantize_mt(existing.original_tons) != order_qty:
                    existing.original_tons = order_qty
                    changed = True
                if quantize_mt(existing.open_tons) != open_qty:
                    existing.open_tons = open_qty
                    changed = True
                if existing.status != exp_status:
                    existing.status = exp_status
                    changed = True
                if existing.commodity != commodity:
                    existing.commodity = commodity
                    changed = True
                if changed:
                    updated += 1
            else:
                exposure = Exposure(
                    commodity=commodity,
                    direction=direction,
                    source_type=source_type,
                    source_id=order.id,
                    original_tons=order_qty,
                    open_tons=open_qty,
                    price_per_ton=order.avg_entry_price,
                    status=exp_status,
                )
                session.add(exposure)
                created += 1

        # §3.8 Retirement sweep (Option A — soft-delete symmetric to upstream).
        # Pre-existing Exposure rows whose source Order has since been
        # soft-deleted are retired here so compute_net_exposure (and any other
        # consumer that filters Exposure.is_deleted) stops counting them. All
        # consumers in this module already filter Exposure.is_deleted == False,
        # so retirement takes effect without further consumer changes.
        # Reversibility: when Order.deleted_at is later cleared, the next
        # reconcile creates a fresh Exposure row (the existing-row lookup
        # above filters is_deleted == False, so the retired row is left as
        # audit history — not un-retired).
        retired = 0
        tasks_cancelled = 0
        stale_exposures = (
            session.query(Exposure)
            .join(Order, Order.id == Exposure.source_id)
            .filter(
                Exposure.source_type.in_(
                    [
                        ExposureSourceType.sales_order,
                        ExposureSourceType.purchase_order,
                    ]
                ),
                Exposure.is_deleted.is_(False),
                Order.deleted_at.isnot(None),
            )
            .all()
        )
        for exposure in stale_exposures:
            exposure.is_deleted = True
            exposure.deleted_at = func.now()
            retired += 1

            # Codex P2: a retired Exposure must not leave behind an
            # executable HedgeTask. cancel_stale_tasks only catches
            # fully_hedged / cancelled exposures, and list_pending_tasks
            # filters solely on HedgeTask.status — without this sweep,
            # /exposures/tasks would keep returning a recommendation for
            # an exposure whose source order has been deleted.
            pending_tasks = (
                session.query(HedgeTask)
                .filter(
                    HedgeTask.exposure_id == exposure.id,
                    HedgeTask.status == HedgeTaskStatus.pending,
                )
                .all()
            )
            for task in pending_tasks:
                task.status = HedgeTaskStatus.cancelled
                tasks_cancelled += 1

        session.flush()

        summary = {
            "created": created,
            "updated": updated,
            "retired": retired,
            "tasks_cancelled": tasks_cancelled,
            "message": "Reconciliation completed",
        }
        run.status = ReconciliationRunStatus.succeeded
        run.completed_at = now_utc()
        run.rows_created = created
        run.rows_updated = updated
        run.summary = summary
        session.flush()
        session.refresh(run)
        return run, summary

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
            q = q.filter(Exposure.commodity.in_(commodity_aliases(commodity)))

        q = q.group_by(Exposure.commodity, Exposure.direction)
        rows = q.all()

        # Aggregate commercial data by commodity (normalised to uppercase)
        agg: dict[str, dict] = {}
        for row in rows:
            c = canonical_commodity(row.commodity) if row.commodity else row.commodity
            if c not in agg:
                agg[c] = {
                    "commodity": c,
                    "long_tons": Decimal("0.000"),
                    "short_tons": Decimal("0.000"),
                    "net_tons": Decimal("0.000"),
                    "long_original": Decimal("0.000"),
                    "short_original": Decimal("0.000"),
                    "long_hedged": Decimal("0.000"),
                    "short_hedged": Decimal("0.000"),
                }
            open_val = quantize_mt(row.total_open)
            original_val = quantize_mt(row.total_original)
            hedged_val = quantize_mt(original_val - open_val)
            if row.direction == ExposureDirection.long:
                agg[c]["long_original"] += original_val
                agg[c]["long_hedged"] += hedged_val
            else:
                agg[c]["short_original"] += original_val
                agg[c]["short_hedged"] += hedged_val

        # ── 2. Global hedge contracts — residual-subtraction aggregation ──
        # §3.10: replace whole-contract NOT IN exclusion with per-contract
        # residual subtraction so partly-linked hedges contribute their
        # unlinked portion (e.g. a 100 MT hedge with a 40 MT live linkage
        # contributes 60 MT, not 0). Mirrors compute_global_snapshot's
        # per-contract residual formula (§3.5) for cross-endpoint parity.
        # Inner subquery filters Order.deleted_at IS NULL: linkages from
        # soft-deleted orders do NOT reduce the hedge's residual, so a live
        # hedge linked only to dead orders reappears with full residual
        # (matching §3.5 / §6.3.5 / §6.3.7).
        live_linked_qty_per_contract = (
            session.query(
                HedgeOrderLinkage.contract_id.label("contract_id"),
                func.coalesce(
                    func.sum(HedgeOrderLinkage.quantity_mt), 0.0
                ).label("linked_qty"),
            )
            .join(Order, Order.id == HedgeOrderLinkage.order_id)
            .filter(Order.deleted_at.is_(None))
            .group_by(HedgeOrderLinkage.contract_id)
            .subquery()
        )

        residual_contract_qty = HedgeContract.quantity_mt - func.coalesce(
            live_linked_qty_per_contract.c.linked_qty, 0.0
        )

        gq = (
            session.query(
                HedgeContract.commodity,
                HedgeContract.classification,
                func.coalesce(func.sum(residual_contract_qty), 0).label("total_qty"),
            )
            .outerjoin(
                live_linked_qty_per_contract,
                HedgeContract.id == live_linked_qty_per_contract.c.contract_id,
            )
            .filter(
                HedgeContract.deleted_at.is_(None),
                HedgeContract.status.in_(
                    [HedgeContractStatus.active, HedgeContractStatus.partially_settled]
                ),
            )
        )
        if commodity:
            gq = gq.filter(HedgeContract.commodity.in_(commodity_aliases(commodity)))
        gq = gq.group_by(HedgeContract.commodity, HedgeContract.classification)
        global_rows = gq.all()

        for grow in global_rows:
            # §3.10 zero-residual skip (Python-side per dispatch decision).
            # When all of a commodity's live hedges are fully linked to live
            # orders, SUM(residual) is 0 but GROUP BY still emits a row.
            # Without this guard, agg.setdefault would inflate the response
            # shape with a zero-valued commodity entry that should NOT exist
            # (per §4 / §10 invariant — "no exposure" → no row, not a zero
            # row).
            if quantize_mt(grow.total_qty) == Decimal("0"):
                continue
            c = (
                canonical_commodity(grow.commodity)
                if grow.commodity
                else grow.commodity
            )
            if c not in agg:
                agg[c] = {
                    "commodity": c,
                    "long_tons": Decimal("0.000"),
                    "short_tons": Decimal("0.000"),
                    "net_tons": Decimal("0.000"),
                    "long_original": Decimal("0.000"),
                    "short_original": Decimal("0.000"),
                    "long_hedged": Decimal("0.000"),
                    "short_hedged": Decimal("0.000"),
                }
            qty = quantize_mt(grow.total_qty)
            if grow.classification == HedgeClassification.long:
                agg[c]["long_tons"] += qty
            else:
                agg[c]["short_tons"] += qty

        # ── 3. Net position (positive = Vendido/Short) ──
        for v in agg.values():
            so_open = v["short_original"] - v["short_hedged"]
            po_open = v["long_original"] - v["long_hedged"]
            v["net_tons"] = quantize_mt(
                (so_open - po_open) + v["short_tons"] - v["long_tons"]
            )

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

        # Codex P2 belt-and-suspenders: exclude tasks whose parent Exposure
        # has been retired (§3.8). The retirement sweep cancels these
        # tasks proactively, but a join+filter on Exposure.is_deleted
        # closes the read path even if a task slips through (e.g., a
        # task created mid-reconcile, or external mutation paths).
        q = (
            session.query(HedgeTask)
            .join(Exposure, HedgeTask.exposure_id == Exposure.id)
            .filter(
                HedgeTask.status == HedgeTaskStatus.pending,
                Exposure.is_deleted.is_(False),
            )
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
        # Codex P2: reject execution if the parent Exposure has been
        # retired (§3.8). Belt-and-suspenders alongside the retirement
        # sweep's task cancellation and list_pending_tasks's filter —
        # ensures an executable recommendation cannot escape the
        # is_deleted predicate even via a stale URL.
        exposure = (
            session.query(Exposure).filter(Exposure.id == task.exposure_id).first()
        )
        if exposure is not None and exposure.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task's exposure has been retired (source order deleted)",
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
            q = q.filter(Exposure.commodity.in_(commodity_aliases(commodity)))
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
