"""Finance Pipeline daily orchestrator service."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.contracts import HedgeContract, HedgeContractStatus
from app.models.counterparty import Counterparty, KycStatus
from app.models.exposure import Exposure, ExposureStatus
from app.models.finance_pipeline import (
    PIPELINE_STEPS,
    FinancePipelineRiskFlag,
    FinancePipelineRun,
    FinancePipelineStep,
    PipelineRiskFlagSeverity,
    PipelineRiskFlagType,
    PipelineRunStatus,
    PipelineStepStatus,
    PipelineTriggerSource,
)
from app.models.market_data import CashSettlementPrice
from app.models.workflow_approval import ApprovalStatus, WorkflowApprovalRequest
from app.services.audit_trail_service import AuditTrailService
from app.services.lme_calendar import lme_calendar
from app.services.mtm_contract_service import PriceProvenanceMissing
from app.services.price_lookup_service import (
    PriceReferenceUnprovable,
    get_cash_settlement_price_d1_with_provenance,
    resolve_symbol,
)


class HolidaySkipSignal(Exception):  # noqa: N818
    """Raised when the requested run date is not an LME business day."""


class RunAlreadyInProgressSignal(Exception):  # noqa: N818
    """Raised when a fresh same-day running row already owns the pipeline lock."""


class FinancePipelineService:
    """Runs the daily finance pipeline: 6 sequential, idempotent steps."""

    @staticmethod
    def run_daily_pipeline(
        db: Session,
        run_date: date,
        *,
        commit: bool = True,
        trigger_source: PipelineTriggerSource | str = PipelineTriggerSource.manual,
        actor: str = "system",
    ) -> FinancePipelineRun:
        """Execute or resume the daily finance pipeline for ``run_date``."""
        if isinstance(trigger_source, str):
            trigger_source = PipelineTriggerSource(trigger_source)

        if not lme_calendar().is_business_day(run_date):
            raise HolidaySkipSignal(f"run_date {run_date.isoformat()} is not an LME trading day")

        inputs_hash = FinancePipelineRun.compute_hash(run_date)
        existing = (
            db.query(FinancePipelineRun).filter(FinancePipelineRun.run_date == run_date).first()
        )

        if existing is not None:
            if existing.status == PipelineRunStatus.completed:
                return existing
            if FinancePipelineService._is_fresh_running_lock(existing):
                raise RunAlreadyInProgressSignal(
                    f"finance pipeline run already in progress for {run_date.isoformat()}"
                )
            run = existing
            previous_status = run.status.value
            run.status = PipelineRunStatus.running
            run.error_message = None
            FinancePipelineService._emit_audit_event(
                db,
                run=run,
                event_type="finance_pipeline_run_started",
                entity_type="finance_pipeline_run",
                entity_id=run.id,
                trigger_source=trigger_source,
                actor=actor,
                previous_status=previous_status,
            )
        else:
            run = FinancePipelineRun(
                run_date=run_date,
                status=PipelineRunStatus.running,
                inputs_hash=inputs_hash,
                triggered_by=trigger_source,
            )
            db.add(run)
            db.flush()
            FinancePipelineService._emit_audit_event(
                db,
                run=run,
                event_type="finance_pipeline_run_started",
                entity_type="finance_pipeline_run",
                entity_id=run.id,
                trigger_source=trigger_source,
                actor=actor,
                previous_status=None,
            )

            for idx, step_name in enumerate(PIPELINE_STEPS, start=1):
                db.add(
                    FinancePipelineStep(
                        run_id=run.id,
                        step_number=idx,
                        step_name=step_name,
                    )
                )
            db.flush()

        failed = False
        for step in sorted(run.steps, key=lambda s: s.step_number):
            if step.status == PipelineStepStatus.completed:
                continue

            previous_status = step.status.value
            step.status = PipelineStepStatus.running
            step.started_at = datetime.now(UTC)
            db.flush()
            FinancePipelineService._emit_audit_event(
                db,
                run=run,
                event_type="finance_pipeline_step_started",
                entity_type="finance_pipeline_step",
                entity_id=step.id,
                trigger_source=trigger_source,
                actor=actor,
                step=step,
                previous_status=previous_status,
            )

            try:
                records = FinancePipelineService._execute_step(db, step.step_name, run_date, run)
                previous_status = step.status.value
                step.status = PipelineStepStatus.completed
                step.records_processed = records
                step.finished_at = datetime.now(UTC)
                run.steps_completed = sum(
                    1 for s in run.steps if s.status == PipelineStepStatus.completed
                )
                db.flush()
                FinancePipelineService._emit_audit_event(
                    db,
                    run=run,
                    event_type="finance_pipeline_step_completed",
                    entity_type="finance_pipeline_step",
                    entity_id=step.id,
                    trigger_source=trigger_source,
                    actor=actor,
                    step=step,
                    previous_status=previous_status,
                    records_processed=records,
                    flags_count=records if step.step_name == "risk_flags" else None,
                )
            except Exception as exc:
                previous_status = step.status.value
                step.status = PipelineStepStatus.failed
                step.error_message = str(exc)[:500]
                step.finished_at = datetime.now(UTC)
                run.status = PipelineRunStatus.partial
                run.error_message = f"Step {step.step_name} failed: {str(exc)[:200]}"
                failed = True
                db.flush()
                FinancePipelineService._emit_audit_event(
                    db,
                    run=run,
                    event_type="finance_pipeline_step_failed",
                    entity_type="finance_pipeline_step",
                    entity_id=step.id,
                    trigger_source=trigger_source,
                    actor=actor,
                    step=step,
                    previous_status=previous_status,
                    error_message=str(exc)[:500],
                )
                FinancePipelineService._emit_audit_event(
                    db,
                    run=run,
                    event_type="finance_pipeline_run_failed_partial",
                    entity_type="finance_pipeline_run",
                    entity_id=run.id,
                    trigger_source=trigger_source,
                    actor=actor,
                    previous_status=PipelineRunStatus.running.value,
                    error_message=run.error_message,
                )
                break

        if not failed:
            previous_status = run.status.value
            run.status = PipelineRunStatus.completed
            run.finished_at = datetime.now(UTC)
            run.steps_completed = len(PIPELINE_STEPS)
            db.flush()
            FinancePipelineService._emit_audit_event(
                db,
                run=run,
                event_type="finance_pipeline_run_completed",
                entity_type="finance_pipeline_run",
                entity_id=run.id,
                trigger_source=trigger_source,
                actor=actor,
                previous_status=previous_status,
            )

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
    def get_run(db: Session, run_id: uuid.UUID) -> FinancePipelineRun | None:
        return db.get(FinancePipelineRun, run_id)

    @staticmethod
    def _is_fresh_running_lock(run: FinancePipelineRun) -> bool:
        if run.status != PipelineRunStatus.running:
            return False
        timeout_seconds = int(os.getenv("FINANCE_PIPELINE_LOCK_TIMEOUT_SECONDS", "1800"))
        created_at = run.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - created_at < timedelta(seconds=timeout_seconds)

    @staticmethod
    def _execute_step(db: Session, step_name: str, run_date: date, run: FinancePipelineRun) -> int:
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
    def _step_market_snapshot(db: Session, run_date: date, run: FinancePipelineRun) -> int:
        return (
            db.query(CashSettlementPrice)
            .filter(CashSettlementPrice.settlement_date <= run_date)
            .count()
        )

    @staticmethod
    def _step_mtm_computation(db: Session, run_date: date, run: FinancePipelineRun) -> int:
        from app.services.mtm_contract_service import compute_mtm_for_contract

        contracts = FinancePipelineService._active_contracts(db)
        processed = 0
        for contract in contracts:
            try:
                compute_mtm_for_contract(db, contract.id, run_date)
                processed += 1
            except PriceProvenanceMissing as exc:
                FinancePipelineService._emit_risk_flag(
                    db,
                    run_id=run.id,
                    flag_type=PipelineRiskFlagType.missing_mtm_price,
                    severity=PipelineRiskFlagSeverity.warning,
                    subject_entity_type="hedge_contract",
                    subject_entity_id=contract.id,
                    payload={"reason": str(exc.detail)[:500]},
                )
        return processed

    @staticmethod
    def _step_pl_snapshot(db: Session, run_date: date, run: FinancePipelineRun) -> int:
        from app.services.pl_snapshot_service import create_pl_snapshot

        contracts = FinancePipelineService._active_contracts(db)
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
            except PriceProvenanceMissing as exc:
                FinancePipelineService._emit_risk_flag(
                    db,
                    run_id=run.id,
                    flag_type=PipelineRiskFlagType.missing_mtm_price,
                    severity=PipelineRiskFlagSeverity.warning,
                    subject_entity_type="hedge_contract",
                    subject_entity_id=contract.id,
                    payload={"reason": str(exc.detail)[:500]},
                )
        return processed

    @staticmethod
    def _step_cashflow_baseline(db: Session, run_date: date, run: FinancePipelineRun) -> int:
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
        except PriceProvenanceMissing:
            return 0

    @staticmethod
    def _step_risk_flags(db: Session, run_date: date, run: FinancePipelineRun) -> int:
        flags_written = 0
        for contract, reason in FinancePipelineService._query_missing_mtm_prices(db, run_date):
            if FinancePipelineService._emit_risk_flag(
                db,
                run_id=run.id,
                flag_type=PipelineRiskFlagType.missing_mtm_price,
                severity=PipelineRiskFlagSeverity.warning,
                subject_entity_type="hedge_contract",
                subject_entity_id=contract.id,
                payload={"reason": reason[:500]},
            ):
                flags_written += 1

        for exposure in FinancePipelineService._query_unhedged_exposures_over_guardrail(db):
            if FinancePipelineService._emit_risk_flag(
                db,
                run_id=run.id,
                flag_type=PipelineRiskFlagType.unhedged_exposure_over_guardrail,
                severity=PipelineRiskFlagSeverity.warning,
                subject_entity_type="exposure",
                subject_entity_id=exposure.id,
                payload={
                    "commodity": exposure.commodity,
                    "open_tons": str(exposure.open_tons),
                    "guardrail_tonnes": os.getenv(
                        "FINANCE_PIPELINE_UNHEDGED_GUARDRAIL_TONNES", "0"
                    ),
                },
            ):
                flags_written += 1

        for counterparty in FinancePipelineService._query_kyc_regressions_with_active_deals(db):
            if FinancePipelineService._emit_risk_flag(
                db,
                run_id=run.id,
                flag_type=PipelineRiskFlagType.kyc_regression_with_active_deals,
                severity=PipelineRiskFlagSeverity.critical,
                subject_entity_type="counterparty",
                subject_entity_id=counterparty.id,
                payload={"kyc_status": counterparty.kyc_status.value},
            ):
                flags_written += 1

        for approval in FinancePipelineService._query_pending_workflow_approvals_past_expiry(db):
            if FinancePipelineService._emit_risk_flag(
                db,
                run_id=run.id,
                flag_type=PipelineRiskFlagType.workflow_approval_pending_past_expiry,
                severity=PipelineRiskFlagSeverity.warning,
                subject_entity_type="workflow_approval_request",
                subject_entity_id=approval.id,
                payload={
                    "mutation_type": approval.mutation_type.value,
                    "expires_at": approval.expires_at.isoformat(),
                },
            ):
                flags_written += 1

        return flags_written

    @staticmethod
    def _step_summary(db: Session, run_date: date, run: FinancePipelineRun) -> int:
        return sum(
            s.records_processed for s in run.steps if s.status == PipelineStepStatus.completed
        )

    @staticmethod
    def _active_contracts(db: Session) -> list[HedgeContract]:
        return (
            db.query(HedgeContract)
            .filter(
                HedgeContract.status == HedgeContractStatus.active,
                HedgeContract.deleted_at.is_(None),
            )
            .order_by(HedgeContract.created_at.asc(), HedgeContract.id.asc())
            .all()
        )

    @staticmethod
    def _query_missing_mtm_prices(db: Session, run_date: date) -> list[tuple[HedgeContract, str]]:
        missing: list[tuple[HedgeContract, str]] = []
        for contract in FinancePipelineService._active_contracts(db):
            try:
                symbol = resolve_symbol(contract.commodity)
                get_cash_settlement_price_d1_with_provenance(db, symbol=symbol, as_of_date=run_date)
            except PriceReferenceUnprovable as exc:
                missing.append((contract, str(exc)))
        return missing

    @staticmethod
    def _query_unhedged_exposures_over_guardrail(db: Session) -> list[Exposure]:
        guardrail = Decimal(os.getenv("FINANCE_PIPELINE_UNHEDGED_GUARDRAIL_TONNES", "0"))
        if guardrail <= 0:
            return []
        return (
            db.query(Exposure)
            .filter(
                Exposure.is_deleted.is_(False),
                Exposure.status != ExposureStatus.fully_hedged,
                Exposure.open_tons > guardrail,
            )
            .order_by(Exposure.created_at.asc(), Exposure.id.asc())
            .all()
        )

    @staticmethod
    def _query_kyc_regressions_with_active_deals(db: Session) -> list[Counterparty]:
        active_counterparty_ids = {
            uuid.UUID(contract.counterparty_id)
            for contract in FinancePipelineService._active_contracts(db)
            if contract.counterparty_id
            and FinancePipelineService._is_uuid(contract.counterparty_id)
        }
        if not active_counterparty_ids:
            return []
        return (
            db.query(Counterparty)
            .filter(
                Counterparty.id.in_(active_counterparty_ids),
                Counterparty.kyc_status != KycStatus.approved,
                Counterparty.is_deleted.is_(False),
            )
            .order_by(Counterparty.created_at.asc(), Counterparty.id.asc())
            .all()
        )

    @staticmethod
    def _query_pending_workflow_approvals_past_expiry(
        db: Session,
    ) -> list[WorkflowApprovalRequest]:
        return (
            db.query(WorkflowApprovalRequest)
            .filter(
                WorkflowApprovalRequest.status == ApprovalStatus.pending,
                WorkflowApprovalRequest.expires_at < datetime.now(UTC),
            )
            .order_by(
                WorkflowApprovalRequest.expires_at.asc(),
                WorkflowApprovalRequest.id.asc(),
            )
            .all()
        )

    @staticmethod
    def _emit_risk_flag(
        db: Session,
        *,
        run_id: uuid.UUID,
        flag_type: PipelineRiskFlagType,
        severity: PipelineRiskFlagSeverity,
        subject_entity_type: str,
        subject_entity_id: uuid.UUID | None,
        payload: dict,
    ) -> bool:
        existing = (
            db.query(FinancePipelineRiskFlag)
            .filter(
                FinancePipelineRiskFlag.run_id == run_id,
                FinancePipelineRiskFlag.flag_type == flag_type,
                FinancePipelineRiskFlag.subject_entity_id == subject_entity_id,
            )
            .first()
        )
        if existing is not None:
            return False
        db.add(
            FinancePipelineRiskFlag(
                run_id=run_id,
                flag_type=flag_type,
                severity=severity,
                subject_entity_type=subject_entity_type,
                subject_entity_id=subject_entity_id,
                payload=payload,
            )
        )
        db.flush()
        return True

    @staticmethod
    def _emit_audit_event(
        db: Session,
        *,
        run: FinancePipelineRun,
        event_type: str,
        entity_type: str,
        entity_id: uuid.UUID,
        trigger_source: PipelineTriggerSource,
        actor: str,
        step: FinancePipelineStep | None = None,
        previous_status: str | None = None,
        records_processed: int | None = None,
        error_message: str | None = None,
        flags_count: int | None = None,
    ) -> AuditEvent:
        metadata = {
            "run_id": str(run.id),
            "run_date": run.run_date.isoformat(),
            "inputs_hash": run.inputs_hash,
            "actor": actor,
            "trigger_source": trigger_source.value,
            "step_name": step.step_name if step else None,
            "step_number": step.step_number if step else None,
            "records_processed": records_processed,
            "error_message": error_message,
            "previous_status": previous_status,
            "flags_count": flags_count,
        }
        return AuditTrailService.record_worker_event(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor=actor,
            source="finance_pipeline_service",
            metadata=metadata,
        )

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            uuid.UUID(value)
        except ValueError:
            return False
        return True
