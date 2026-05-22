from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.counterparty import Counterparty, CounterpartyType, KycStatus
from app.models.exposure import Exposure, ExposureDirection, ExposureSourceType
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
from app.models.workflow_approval import (
    ApprovalStatus,
    MutationType,
    ThresholdDimension,
    WorkflowApprovalRequest,
)
from app.services.finance_pipeline_service import (
    FinancePipelineService,
    HolidaySkipSignal,
    RunAlreadyInProgressSignal,
)


def _active_contract_without_price(session) -> HedgeContract:
    contract = HedgeContract(
        commodity="ALUMINUM",
        quantity_mt=Decimal("5.000"),
        fixed_leg_side=HedgeLegSide.buy,
        variable_leg_side=HedgeLegSide.sell,
        classification=HedgeClassification.long,
        fixed_price_value=Decimal("2400.000000"),
        fixed_price_unit="USD/MT",
        float_pricing_convention="avg",
        status=HedgeContractStatus.active,
    )
    session.add(contract)
    session.commit()
    session.refresh(contract)
    return contract


def _active_contract_for_counterparty(session, counterparty_id: str) -> HedgeContract:
    contract = _active_contract_without_price(session)
    contract.counterparty_id = counterparty_id
    session.commit()
    session.refresh(contract)
    return contract


def test_pipeline_steps_is_tuple() -> None:
    assert isinstance(PIPELINE_STEPS, tuple)


def test_holiday_skip_creates_no_run_or_audit_event(session) -> None:
    with pytest.raises(HolidaySkipSignal):
        FinancePipelineService.run_daily_pipeline(
            session,
            date(2026, 5, 23),  # Saturday
            trigger_source=PipelineTriggerSource.scheduler,
            actor="service:cashflow_pipeline",
        )

    assert session.query(AuditEvent).count() == 0


def test_scheduled_run_sets_triggered_by_and_lifecycle_audit(session) -> None:
    run = FinancePipelineService.run_daily_pipeline(
        session,
        date(2026, 5, 22),
        trigger_source=PipelineTriggerSource.scheduler,
        actor="service:cashflow_pipeline",
    )

    session.refresh(run)
    assert run.triggered_by == PipelineTriggerSource.scheduler
    assert run.risk_flags_count == 0

    events = session.query(AuditEvent).order_by(AuditEvent.timestamp_utc).all()
    event_types = [event.event_type for event in events]
    assert event_types.count("finance_pipeline_run_started") == 1
    assert event_types.count("finance_pipeline_run_completed") == 1
    assert event_types.count("finance_pipeline_step_started") == 6
    assert event_types.count("finance_pipeline_step_completed") == 6

    for event in events:
        metadata = event.payload["metadata"]
        assert metadata["run_id"] == str(run.id)
        assert metadata["run_date"] == "2026-05-22"
        assert metadata["inputs_hash"] == run.inputs_hash
        assert metadata["actor"] == "service:cashflow_pipeline"
        assert metadata["trigger_source"] == "scheduler"


def test_manual_run_sets_triggered_by_manual_in_db(session) -> None:
    run = FinancePipelineService.run_daily_pipeline(
        session,
        date(2026, 5, 22),
        trigger_source=PipelineTriggerSource.manual,
        actor="human-risk-manager",
    )

    session.refresh(run)
    assert run.triggered_by == PipelineTriggerSource.manual


def test_running_lock_raises_signal(session) -> None:
    run = FinancePipelineRun(
        run_date=date(2026, 5, 22),
        status=PipelineRunStatus.running,
        inputs_hash=FinancePipelineRun.compute_hash(date(2026, 5, 22)),
    )
    session.add(run)
    session.commit()

    with pytest.raises(RunAlreadyInProgressSignal):
        FinancePipelineService.run_daily_pipeline(session, date(2026, 5, 22))


def test_running_lock_uses_last_started_at_not_original_created_at(monkeypatch) -> None:
    now = datetime.now(UTC)
    run = FinancePipelineRun(
        run_date=date(2026, 5, 22),
        status=PipelineRunStatus.running,
        inputs_hash=FinancePipelineRun.compute_hash(date(2026, 5, 22)),
        created_at=now - timedelta(hours=1),
        started_at=now,
    )
    monkeypatch.setenv("FINANCE_PIPELINE_LOCK_TIMEOUT_SECONDS", "1800")

    assert FinancePipelineService._is_fresh_running_lock(run) is True


def test_resume_refreshes_run_started_at_for_lock_window(session) -> None:
    old_started_at = datetime(2026, 5, 21, 10, 0, tzinfo=UTC)
    run = FinancePipelineRun(
        run_date=date(2026, 5, 22),
        status=PipelineRunStatus.partial,
        inputs_hash=FinancePipelineRun.compute_hash(date(2026, 5, 22)),
        started_at=old_started_at,
        created_at=old_started_at,
    )
    session.add(run)
    session.flush()
    for idx, step_name in enumerate(PIPELINE_STEPS, start=1):
        session.add(
            FinancePipelineStep(
                run_id=run.id,
                step_number=idx,
                step_name=step_name,
                status=PipelineStepStatus.completed
                if step_name == "market_snapshot"
                else PipelineStepStatus.pending,
            )
        )
    session.commit()

    resumed = FinancePipelineService.run_daily_pipeline(session, date(2026, 5, 22))

    assert resumed.id == run.id
    resumed_started_at = resumed.started_at
    if resumed_started_at.tzinfo is None:
        resumed_started_at = resumed_started_at.replace(tzinfo=UTC)
    assert resumed_started_at > old_started_at


def test_resume_clears_stale_step_error_message(client) -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            FinancePipelineService,
            "_step_mtm_computation",
            staticmethod(lambda db, run_date, run: (_ for _ in ()).throw(RuntimeError("down"))),
        )
        first = client.post("/finance/pipeline/run", json={"run_date": "2026-05-22"})
    run_id = first.json()["id"]

    second = client.post("/finance/pipeline/run", json={"run_date": "2026-05-22"})
    detail = client.get(f"/finance/pipeline/runs/{run_id}")

    assert second.json()["status"] == "completed"
    mtm_step = next(
        step for step in detail.json()["steps"] if step["step_name"] == "mtm_computation"
    )
    assert mtm_step["error_message"] is None


def test_insert_race_on_unique_run_date_raises_lock_signal(session, monkeypatch) -> None:
    original_flush = session.flush

    def flush_with_duplicate_run_date(*args, **kwargs):
        if any(isinstance(obj, FinancePipelineRun) for obj in session.new):
            raise IntegrityError(
                "INSERT INTO finance_pipeline_runs",
                {},
                Exception("duplicate key value violates unique constraint"),
            )
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(session, "flush", flush_with_duplicate_run_date)

    with pytest.raises(RunAlreadyInProgressSignal):
        FinancePipelineService.run_daily_pipeline(session, date(2026, 5, 22))


def test_completed_same_date_returns_existing_run_without_new_audit(session) -> None:
    first = FinancePipelineService.run_daily_pipeline(session, date(2026, 5, 22))
    event_count = session.query(AuditEvent).count()

    second = FinancePipelineService.run_daily_pipeline(session, date(2026, 5, 22))

    assert second.id == first.id
    assert session.query(AuditEvent).count() == event_count


def test_missing_mtm_price_is_flagged_once_across_steps(session) -> None:
    contract = _active_contract_without_price(session)

    run = FinancePipelineService.run_daily_pipeline(
        session,
        date(2026, 2, 2),
        trigger_source=PipelineTriggerSource.manual,
        actor="risk-manager-1",
    )

    flags = session.query(FinancePipelineRiskFlag).all()
    assert len(flags) == 1
    assert flags[0].run_id == run.id
    assert flags[0].flag_type == PipelineRiskFlagType.missing_mtm_price
    assert flags[0].severity == PipelineRiskFlagSeverity.warning
    assert flags[0].subject_entity_type == "hedge_contract"
    assert flags[0].subject_entity_id == contract.id

    risk_step_event = (
        session.query(AuditEvent)
        .filter(AuditEvent.event_type == "finance_pipeline_step_completed")
        .filter(AuditEvent.payload["metadata"]["step_name"].as_string() == "risk_flags")
        .one()
    )
    assert risk_step_event.payload["metadata"]["flags_count"] == 0


def test_risk_flags_step_detects_four_bound_flag_types(session, monkeypatch) -> None:
    counterparty = Counterparty(
        type=CounterpartyType.broker,
        name="Expired KYC Broker",
        country="BRA",
        kyc_status=KycStatus.expired,
    )
    session.add(counterparty)
    session.commit()
    contract = _active_contract_for_counterparty(session, str(counterparty.id))
    exposure = Exposure(
        commodity="ALUMINUM",
        direction=ExposureDirection.long,
        source_type=ExposureSourceType.sales_order,
        source_id=contract.id,
        original_tons=Decimal("100.000"),
        open_tons=Decimal("100.000"),
        price_per_ton=Decimal("2400.000000"),
        status="open",
    )
    approval = WorkflowApprovalRequest(
        mutation_type=MutationType.deal_create,
        status=ApprovalStatus.pending,
        requested_by="requester",
        threshold_at_request=Decimal("1.000000"),
        threshold_config_value=Decimal("1.000000"),
        threshold_dimension=ThresholdDimension.notional_usd,
        mutation_payload_canonical="{}",
        mutation_payload_hash="0" * 64,
        correlation_id=contract.id,
        expires_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.add_all([exposure, approval])
    session.commit()
    monkeypatch.setenv("FINANCE_PIPELINE_UNHEDGED_GUARDRAIL_TONNES", "50")

    run = FinancePipelineService.run_daily_pipeline(
        session,
        date(2026, 2, 2),
        trigger_source=PipelineTriggerSource.scheduler,
        actor="service:cashflow_pipeline",
    )

    flag_types = {
        flag.flag_type for flag in session.query(FinancePipelineRiskFlag).filter_by(run_id=run.id)
    }
    assert {
        PipelineRiskFlagType.missing_mtm_price,
        PipelineRiskFlagType.unhedged_exposure_over_guardrail,
        PipelineRiskFlagType.kyc_regression_with_active_deals,
        PipelineRiskFlagType.workflow_approval_pending_past_expiry,
    }.issubset(flag_types)


def test_risk_flags_step_zero_flags_is_valid(session) -> None:
    run = FinancePipelineService.run_daily_pipeline(session, date(2026, 5, 22))

    assert run.status.value == "completed"
    assert run.risk_flags_count == 0


def test_pending_workflow_query_ignores_future_expiry(session) -> None:
    approval = WorkflowApprovalRequest(
        mutation_type=MutationType.deal_create,
        status=ApprovalStatus.pending,
        requested_by="requester",
        threshold_at_request=Decimal("1.000000"),
        threshold_config_value=Decimal("1.000000"),
        threshold_dimension=ThresholdDimension.notional_usd,
        mutation_payload_canonical="{}",
        mutation_payload_hash="0" * 64,
        correlation_id=uuid.uuid4(),
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
    )
    session.add(approval)
    session.commit()

    run = FinancePipelineService.run_daily_pipeline(session, date(2026, 5, 22))

    assert {
        flag.flag_type for flag in session.query(FinancePipelineRiskFlag).filter_by(run_id=run.id)
    } == set()


def test_emit_risk_flag_is_idempotent(session) -> None:
    run = FinancePipelineService.run_daily_pipeline(session, date(2026, 5, 22))

    first = FinancePipelineService._emit_risk_flag(
        session,
        run_id=run.id,
        flag_type=PipelineRiskFlagType.workflow_approval_pending_past_expiry,
        severity=PipelineRiskFlagSeverity.warning,
        subject_entity_type="workflow_approval_request",
        subject_entity_id=run.id,
        payload={"reason": "first"},
    )
    second = FinancePipelineService._emit_risk_flag(
        session,
        run_id=run.id,
        flag_type=PipelineRiskFlagType.workflow_approval_pending_past_expiry,
        severity=PipelineRiskFlagSeverity.warning,
        subject_entity_type="workflow_approval_request",
        subject_entity_id=run.id,
        payload={"reason": "second"},
    )

    assert first is True
    assert second is False


def test_route_response_surfaces_triggered_by_and_risk_flags_count(client) -> None:
    response = client.post("/finance/pipeline/run", json={"run_date": "2026-05-22"})

    assert response.status_code == 201
    body = response.json()
    assert body["triggered_by"] == "manual"
    assert body["risk_flags_count"] == 0


def test_list_runs_eager_loads_risk_flags_count(session) -> None:
    for run_date in (date(2026, 5, 20), date(2026, 5, 21), date(2026, 5, 22)):
        FinancePipelineService.run_daily_pipeline(session, run_date)

    select_count = 0

    def count_selects(conn, cursor, statement, parameters, context, executemany):
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    sqlalchemy_event.listen(engine, "before_cursor_execute", count_selects)
    try:
        with SessionLocal() as fresh:
            runs = FinancePipelineService.list_runs(fresh)
            counts = [run.risk_flags_count for run in runs]
    finally:
        sqlalchemy_event.remove(engine, "before_cursor_execute", count_selects)

    assert len(runs) == 3
    assert counts == [0, 0, 0]
    assert select_count <= 2


def test_detail_response_includes_risk_flags(client, session) -> None:
    _active_contract_without_price(session)

    response = client.post("/finance/pipeline/run", json={"run_date": "2026-02-02"})
    assert response.status_code == 201
    detail = client.get(f"/finance/pipeline/runs/{response.json()['id']}")

    assert detail.status_code == 200
    assert detail.json()["risk_flags_count"] == 1
    assert detail.json()["risk_flags"][0]["flag_type"] == "missing_mtm_price"


def test_unique_constraint_blocks_duplicate_flag_emission(session) -> None:
    run = FinancePipelineService.run_daily_pipeline(session, date(2026, 5, 22))
    subject_id = run.id
    first = FinancePipelineRiskFlag(
        run_id=run.id,
        flag_type=PipelineRiskFlagType.workflow_approval_pending_past_expiry,
        severity=PipelineRiskFlagSeverity.warning,
        subject_entity_type="workflow_approval_request",
        subject_entity_id=subject_id,
        payload={"reason": "first"},
    )
    second = FinancePipelineRiskFlag(
        run_id=run.id,
        flag_type=PipelineRiskFlagType.workflow_approval_pending_past_expiry,
        severity=PipelineRiskFlagSeverity.warning,
        subject_entity_type="workflow_approval_request",
        subject_entity_id=subject_id,
        payload={"reason": "second"},
    )
    session.add(first)
    session.commit()
    session.add(second)
    with pytest.raises(IntegrityError):
        session.commit()


def test_unique_constraint_blocks_duplicate_run_level_flag_with_null_subject(session) -> None:
    run = FinancePipelineService.run_daily_pipeline(session, date(2026, 5, 22))
    first = FinancePipelineRiskFlag(
        run_id=run.id,
        flag_type=PipelineRiskFlagType.workflow_approval_pending_past_expiry,
        severity=PipelineRiskFlagSeverity.warning,
        subject_entity_type="finance_pipeline_run",
        subject_entity_id=None,
        payload={"reason": "first"},
    )
    second = FinancePipelineRiskFlag(
        run_id=run.id,
        flag_type=PipelineRiskFlagType.workflow_approval_pending_past_expiry,
        severity=PipelineRiskFlagSeverity.warning,
        subject_entity_type="finance_pipeline_run",
        subject_entity_id=None,
        payload={"reason": "second"},
    )
    session.add(first)
    session.commit()
    session.add(second)
    with pytest.raises(IntegrityError):
        session.commit()


def test_scheduled_task_defaults_run_date_from_utc(monkeypatch) -> None:
    from app.tasks import finance_pipeline_task

    captured = {}

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 1, 2, 0, 15, tzinfo=tz)

    def fake_run_daily_pipeline(session, run_date, **kwargs):
        captured["run_date"] = run_date
        return SimpleNamespace(
            id=uuid.uuid4(),
            status=SimpleNamespace(value="completed"),
        )

    monkeypatch.setattr(finance_pipeline_task, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        finance_pipeline_task.FinancePipelineService,
        "run_daily_pipeline",
        staticmethod(fake_run_daily_pipeline),
    )

    finance_pipeline_task.run_finance_pipeline_daily()

    assert captured["run_date"] == date(2030, 1, 2)


def test_reconstruct_past_run_from_four_tables_alone(session) -> None:
    run = FinancePipelineService.run_daily_pipeline(session, date(2026, 5, 22))
    run_id = run.id

    with SessionLocal() as fresh:
        reconstructed_run = fresh.get(type(run), run_id)
        reconstructed_steps = list(reconstructed_run.steps)
        reconstructed_flags = (
            fresh.query(FinancePipelineRiskFlag)
            .filter(FinancePipelineRiskFlag.run_id == run_id)
            .all()
        )
        reconstructed_events = (
            fresh.query(AuditEvent)
            .filter(AuditEvent.payload["metadata"]["run_id"].as_string() == str(run_id))
            .all()
        )

    assert reconstructed_run.status.value == "completed"
    assert [step.status.value for step in reconstructed_steps] == ["completed"] * 6
    assert reconstructed_flags == []
    assert len(reconstructed_events) == 14
