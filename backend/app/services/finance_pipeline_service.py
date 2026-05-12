"""Finance Pipeline — daily orchestrator service."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.contracts import HedgeContract, HedgeContractStatus
from app.models.finance_pipeline import (
    FinancePipelineRun,
    FinancePipelineStep,
    PIPELINE_STEPS,
    PipelineRunStatus,
    PipelineStepStatus,
)
from app.models.market_data import CashSettlementPrice


class FinancePipelineService:
    """Runs the daily finance pipeline — 6 sequential steps, idempotent & resumable."""

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @staticmethod
    def run_daily_pipeline(
        db: Session, run_date: date, *, commit: bool = True
    ) -> FinancePipelineRun:
        """Execute (or resume) the daily finance pipeline for *run_date*.

        Idempotent: if a run already exists for the same date and is
        completed, returns it immediately.  If it is partial/failed, the
        pipeline resumes from the first non-completed step.
        """
        inputs_hash = FinancePipelineRun.compute_hash(run_date)

        existing = (
            db.query(FinancePipelineRun)
            .filter(FinancePipelineRun.inputs_hash == inputs_hash)
            .first()
        )

        if existing is not None:
            if existing.status == PipelineRunStatus.completed:
                return existing
            # Resume — reuse the existing run
            run = existing
            run.status = PipelineRunStatus.running
            run.error_message = None
        else:
            run = FinancePipelineRun(
                run_date=run_date,
                status=PipelineRunStatus.running,
                inputs_hash=inputs_hash,
            )
            db.add(run)
            db.flush()  # assign id

            # Create step rows
            for idx, step_name in enumerate(PIPELINE_STEPS, start=1):
                step = FinancePipelineStep(
                    run_id=run.id,
                    step_number=idx,
                    step_name=step_name,
                )
                db.add(step)
            db.flush()

        # Execute steps sequentially
        failed = False
        for step in sorted(run.steps, key=lambda s: s.step_number):
            if step.status == PipelineStepStatus.completed:
                continue  # skip already-done steps (resume)

            step.status = PipelineStepStatus.running
            step.started_at = datetime.now(timezone.utc)
            db.flush()

            try:
                records = FinancePipelineService._execute_step(
                    db, step.step_name, run_date, run
                )
                step.status = PipelineStepStatus.completed
                step.records_processed = records
                step.finished_at = datetime.now(timezone.utc)
                run.steps_completed = sum(
                    1 for s in run.steps if s.status == PipelineStepStatus.completed
                )
                db.flush()
            except Exception as exc:  # noqa: BLE001
                step.status = PipelineStepStatus.failed
                step.error_message = str(exc)[:500]
                step.finished_at = datetime.now(timezone.utc)
                run.status = PipelineRunStatus.partial
                run.error_message = f"Step {step.step_name} failed: {str(exc)[:200]}"
                failed = True
                db.flush()
                break  # stop on first failure

        if not failed:
            run.status = PipelineRunStatus.completed
            run.finished_at = datetime.now(timezone.utc)
            run.steps_completed = len(PIPELINE_STEPS)

        db.flush()
        if commit:
            db.commit()
            db.refresh(run)
        return run

    @staticmethod
    def list_runs(db: Session, limit: int = 50) -> list[FinancePipelineRun]:
        return (
            db.query(FinancePipelineRun)
            .order_by(FinancePipelineRun.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_run(db: Session, run_id: uuid.UUID) -> Optional[FinancePipelineRun]:
        return db.get(FinancePipelineRun, run_id)

    # ------------------------------------------------------------------
    # step implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _execute_step(
        db: Session, step_name: str, run_date: date, run: FinancePipelineRun
    ) -> int:
        """Dispatch to the appropriate step handler. Returns records_processed."""
        handler = {
            "market_snapshot": FinancePipelineService._step_market_snapshot,
            "mtm_computation": FinancePipelineService._step_mtm_computation,
            "pl_snapshot": FinancePipelineService._step_pl_snapshot,
            "cashflow_baseline": FinancePipelineService._step_cashflow_baseline,
            "risk_flags": FinancePipelineService._step_risk_flags,
            "summary": FinancePipelineService._step_summary,
        }.get(step_name)
        if handler is None:
            raise ValueError(f"Unknown step: {step_name}")
        return handler(db, run_date, run)

    @staticmethod
    def _step_market_snapshot(
        db: Session, run_date: date, run: FinancePipelineRun
    ) -> int:
        """Count latest market prices available up to run_date."""
        count = (
            db.query(CashSettlementPrice)
            .filter(CashSettlementPrice.settlement_date <= run_date)
            .count()
        )
        return count

    @staticmethod
    def _step_mtm_computation(
        db: Session, run_date: date, run: FinancePipelineRun
    ) -> int:
        """Compute MTM for all active hedge contracts."""
        from app.services.mtm_contract_service import compute_mtm_for_contract

        contracts = (
            db.query(HedgeContract)
            .filter(HedgeContract.status == HedgeContractStatus.active)
            .all()
        )
        processed = 0
        for contract in contracts:
            try:
                compute_mtm_for_contract(db, contract.id, run_date)
                processed += 1
            except Exception:  # noqa: BLE001
                pass  # skip contracts that can't be MTM'd (missing prices, etc.)
        return processed

    @staticmethod
    def _step_pl_snapshot(db: Session, run_date: date, run: FinancePipelineRun) -> int:
        """Create P&L snapshots for all active contracts."""
        from app.services.pl_snapshot_service import create_pl_snapshot

        contracts = (
            db.query(HedgeContract)
            .filter(HedgeContract.status == HedgeContractStatus.active)
            .all()
        )
        processed = 0
        for contract in contracts:
            try:
                create_pl_snapshot(
                    db,
                    entity_type="hedge_contract",
                    entity_id=contract.id,
                    period_start=run_date,
                    period_end=run_date,
                    commit=False,
                )
                processed += 1
            except Exception:  # noqa: BLE001
                pass
        return processed

    @staticmethod
    def _step_cashflow_baseline(
        db: Session, run_date: date, run: FinancePipelineRun
    ) -> int:
        """Create cashflow baseline snapshot."""
        from app.services.cashflow_baseline_service import (
            create_cashflow_baseline_snapshot,
        )

        try:
            create_cashflow_baseline_snapshot(
                db,
                as_of_date=run_date,
                correlation_id=str(run.id),
                commit=False,
            )
            return 1
        except Exception:  # noqa: BLE001
            return 0

    @staticmethod
    def _step_risk_flags(db: Session, run_date: date, run: FinancePipelineRun) -> int:
        """Stub — risk flags identification (to be implemented)."""
        # Future: check for missing prices, unhedged exposures, etc.
        return 0

    @staticmethod
    def _step_summary(db: Session, run_date: date, run: FinancePipelineRun) -> int:
        """Summary step — aggregates records processed across steps."""
        total = sum(
            s.records_processed
            for s in run.steps
            if s.status == PipelineStepStatus.completed
        )
        return total
