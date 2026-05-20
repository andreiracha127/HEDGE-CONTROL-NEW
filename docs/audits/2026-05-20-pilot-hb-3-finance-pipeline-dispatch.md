# PR-HB-3-1 — Finance Pipeline Daily Hardening Dispatch

Cycle: Pilot Hard Blockers (conditional-go brief — PR #89)
Wave: PR-HB-3-1
Constitutional anchor: `docs/governance.md` — "Finance Pipeline daily reconstructability (binding, Pilot Hard Blocker 3)" subsection (HB-3 amendment, sibling artifact to this dispatch in the same PR per relaxed-protocol decision 2026-05-20).
Pilot brief reference: `docs/2026-05-tech-lead-executive-analysis.md` §HB-3 (lines 77–93).
Findings closed by this wave: HB-3 (the third of the four Pilot Hard Blockers gating the June 2026 aluminium pilot go-decision).
Status: DRAFT

---

## §1 Scope

This PR delivers the Finance Pipeline daily-hardening implementation contracted by the HB-3 constitutional amendment in `docs/governance.md`. Concretely, the executor must:

1. Wire the existing `FinancePipelineService.run_daily_pipeline` orchestrator (`backend/app/services/finance_pipeline_service.py:29`) onto the Railway `scheduler` service via a new task module `backend/app/tasks/finance_pipeline_task.py` plus an `add_job(...)` registration in `backend/app/tasks/scheduler.py` (which currently has zero `finance_pipeline` references — confirmed gap).
2. Add a holiday-skip guard at the entry of `run_daily_pipeline` using `app.services.lme_calendar.Calendar.is_business_day` (`backend/app/services/lme_calendar.py:69`) — non-trading days produce neither a row nor an audit event.
3. Convert the `PIPELINE_STEPS` enumeration at `backend/app/models/finance_pipeline.py:41-48` from `list` to `tuple` to bind constitutional immutability.
4. Replace the four silent-exception sites in the step bodies (`_step_mtm_computation` lines 174–179, `_step_pl_snapshot` lines 193–205, `_step_cashflow_baseline` lines 217–226) and the production stub (`_step_risk_flags` lines 228–232) with explicit per-record risk-flag emission + the four detection routines binding `risk_flags` step content.
5. Add the per-day UNIQUE invariant on `finance_pipeline_runs.run_date` and the new `triggered_by` enum column via a new alembic revision continuing from HB-2's head (revision `046` per HB-2 amendment — actual chain anchor verified via `alembic heads` at the start of the executor session).
6. Introduce the `finance_pipeline_risk_flags` table (4 `flag_type` values × 3 `severity` values, JSONB payload with `with_variant` SQLite fallback per the Cluster 4 pattern).
7. Emit the six HMAC-signed lifecycle audit events (`finance_pipeline_run_started` / `_completed` / `_failed_partial` + `finance_pipeline_step_started` / `_completed` / `_failed`) via `AuditTrailService.record_worker_event(...)` (`backend/app/services/audit_trail_service.py:122`) for scheduler-triggered runs and via the existing route-layer `audit_event` dependency for manual runs — `trigger_source` field on the payload disambiguates the two provenance modes.
8. Bind scheduled invocations to the existing `service:cashflow_pipeline` service identity (no new identity introduced — AUTHORIZATION MATRIX line 250 already covers "cashflow_ledger + finance_pipeline writes").
9. Add the reconstruction acceptance test materializing a past run's state from the four tables (`finance_pipeline_runs` + `finance_pipeline_steps` + `finance_pipeline_risk_flags` + `audit_events`) with no other inputs.
10. Expand `docs/runbook-railway.md` with the HB-3 operational section (scheduled cadence, failure-recovery procedure, observable absence-of-completion signal per pilot brief §5 stop-condition).

The PR closes HB-3 of the four-Hard-Blocker pilot go-condition. After merge, three of the four HBs are in `landed` state (HB-1 ✅ via PR #95; HB-2 implementation ⏳ via PR-HB-2-1; HB-3 ✅ via this PR); HB-4 (Audit Daily Report) remains.

## §2 Boundary

This PR DOES NOT touch:

- **Service identity surface** — no new institutional or service identity. Scheduled runs use the existing `service:cashflow_pipeline` per AUTHORIZATION MATRIX line 250. No edits to the matrix appendix.
- **Frontend institutional surfaces** beyond the minimum-viable schema regen + `triggered_by` / `risk_flags_count` field surfacing on any existing pipeline detail page (per §6 below). The auditor's daily report (which will consume HB-3's `finance_pipeline_run_completed` audit event) is the HB-4 deliverable, not HB-3.
- **Snapshot service contracts** for MTM (`mtm_contract_service.compute_mtm_for_contract`), P&L (`pl_snapshot_service.create_pl_snapshot`), or cashflow baseline (`cashflow_baseline_service.create_cashflow_baseline_snapshot`). HB-3 only removes the silent-`except` wrapping AROUND these calls inside the pipeline service; it does not modify the snapshot services themselves. Snapshot-service invariants (append-only, idempotent on primary-key conflict) are pre-existing and remain in scope of their own modules.
- **Advanced `risk_flags` taxonomy** beyond the four `flag_type` enum members bound by the HB-3 amendment (`missing_mtm_price`, `unhedged_exposure_over_guardrail`, `kyc_regression_with_active_deals`, `workflow_approval_pending_past_expiry`). Adding a fifth flag is a future-amendment work item per the amendment's Phase 2 deferral.
- **Backfill of pre-merge business days** into the `finance_pipeline_runs` table. The data migration sets `triggered_by = 'manual'` only on rows that already exist; it does not retroactively materialize runs for prior business days that had no `FinancePipelineRun` row. Pre-merge reconstruction continues to rely on the existing per-entity audit trails (MTM/PL/cashflow_baseline snapshots).
- **Cross-day rollup reporting**. The daily ledger emitted by HB-3 is sufficient for reconstructability; weekly/monthly aggregates are a downstream reporting concern outside HB-3 scope per the amendment.
- **The existing route-layer `manual_run_triggered` audit event** at `backend/app/api/routes/finance_pipeline.py:31-36`. This event captures the human-intent record (an actor crossed the route with intent to trigger) and is distinct from the six lifecycle events HB-3 introduces, which capture pipeline-state transitions. Both event surfaces persist after HB-3.
- **The MARKET-DATA GOVERNANCE appendix and the HB-1 KYC amendment text**. HB-3's `risk_flags` step CONSUMES the invariants defined there (price provenance, KYC status) but does not modify those bindings.
- **The HB-2 Workflow Approval gate amendment text**. HB-3's `risk_flags` step likewise CONSUMES the HB-2 lifecycle (querying for `pending` or `approved` approvals past `expires_at`) but does not modify the HB-2 bindings.

§1 deliverables and §2 boundaries are pairwise disjoint by design — verify before review.

## §3 Pre-step

Before any code change, the executor MUST:

1. **Confirm HB-3 amendment present at HEAD of working branch.** Run:

   ```sh
   grep -n "Finance Pipeline daily reconstructability (binding, Pilot Hard Blocker 3)" docs/governance.md
   ```

   Must return exactly one match (the binding subsection header). If zero matches, the amendment did not land — STOP and surface to the orchestrator before proceeding.

2. **Capture current alembic head.** Run:

   ```sh
   cd backend && alembic heads
   ```

   Expected single head depending on HB-2 implementation status:
   - If HB-2 implementation has merged: head is `046_workflow_approvals` (or whatever revision name HB-2 implementation PR shipped — read the revision file under `backend/alembic/versions/` to confirm).
   - If HB-2 implementation has NOT yet merged: head is `045_market_data_governance_columns`. In this case, HB-3 implementation MUST hold until HB-2 implementation lands — the alembic chain cannot be authored without knowing HB-2's revision number, and merging HB-3's revision before HB-2's would create a fork that violates `backend/tests/test_alembic_chain.py`. The executor surfaces this dependency to the orchestrator.

3. **Confirm `service:cashflow_pipeline` is listed in AUTHORIZATION MATRIX.** Run:

   ```sh
   grep -n "service:cashflow_pipeline" docs/governance.md
   ```

   Must return ≥ 2 matches including `docs/governance.md:250` ("cashflow_ledger + finance_pipeline writes"). This anchors the service-identity binding for §4.12.

4. **No SQL pre-step.** All schema changes ship in the §5 alembic revision; no out-of-band SQL is required.

## §4 Backend changes

Per-file directives. Each subsection cites the current HEAD line range that changes; line numbers are pinned to the state observed at dispatch authoring time and may drift by ±2 in the executor session — the executor follows the SYMBOL, not the line, when this happens.

### §4.1 `backend/app/models/finance_pipeline.py` — immutable PIPELINE_STEPS + new model

Change at lines 41–48 (the `PIPELINE_STEPS` constant):

```python
# BEFORE (current HEAD)
PIPELINE_STEPS = [
    "market_snapshot",
    "mtm_computation",
    "pl_snapshot",
    "cashflow_baseline",
    "risk_flags",
    "summary",
]

# AFTER
PIPELINE_STEPS: tuple[str, ...] = (
    "market_snapshot",
    "mtm_computation",
    "pl_snapshot",
    "cashflow_baseline",
    "risk_flags",
    "summary",
)
```

Add new enums + ORM model at end of file (after `FinancePipelineStep` ends at line 114):

```python
class PipelineTriggerSource(enum.Enum):
    scheduler = "scheduler"
    manual = "manual"


class PipelineRiskFlagType(enum.Enum):
    missing_mtm_price = "missing_mtm_price"
    unhedged_exposure_over_guardrail = "unhedged_exposure_over_guardrail"
    kyc_regression_with_active_deals = "kyc_regression_with_active_deals"
    workflow_approval_pending_past_expiry = "workflow_approval_pending_past_expiry"


class PipelineRiskFlagSeverity(enum.Enum):
    informational = "informational"
    warning = "warning"
    critical = "critical"


class FinancePipelineRiskFlag(Base):
    __tablename__ = "finance_pipeline_risk_flags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("finance_pipeline_runs.id"),
        nullable=False,
        index=True,
    )
    flag_type: Mapped[PipelineRiskFlagType] = mapped_column(
        Enum(PipelineRiskFlagType, name="pipeline_risk_flag_type"),
        nullable=False,
    )
    severity: Mapped[PipelineRiskFlagSeverity] = mapped_column(
        Enum(PipelineRiskFlagSeverity, name="pipeline_risk_flag_severity"),
        nullable=False,
    )
    subject_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    payload: Mapped[dict] = mapped_column(
        JSONB().with_variant(Text(), "sqlite"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # DB-level dedup defense matching §5.3 alembic. Mirrors the constraint
        # declared in the migration so ORM-level integrity errors fire too.
        UniqueConstraint(
            "run_id",
            "subject_entity_id",
            "flag_type",
            name="uq_finance_pipeline_risk_flags_run_subject_type",
        ),
    )
```

Add `UniqueConstraint` to the existing `from sqlalchemy import …` import block at the top of the file.

Modify `FinancePipelineRun` to add the `triggered_by` column (insert after existing `inputs_hash` declaration at line 72):

```python
triggered_by: Mapped[PipelineTriggerSource] = mapped_column(
    Enum(PipelineTriggerSource, name="pipeline_trigger_source"),
    nullable=False,
    default=PipelineTriggerSource.manual,
)
```

Imports to add at top of file:

```python
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
```

(`UUID`, `Date`, `DateTime`, `Enum`, `ForeignKey`, `Integer`, `String`, `Text` — `Text` is the new addition; the rest are already imported per current HEAD lines 10–18.)

### §4.2 `backend/app/schemas/finance_pipeline.py` — surface new fields

Extend `PipelineRunRead` and `PipelineRunDetailRead` (current shapes are response models per `backend/app/api/routes/finance_pipeline.py:25,59`) to include:

- `triggered_by: PipelineTriggerSource` — read-back of the new column
- `risk_flags_count: int` — computed property: count of `FinancePipelineRiskFlag` rows attached to the run (read via `len(run.risk_flags)` after the relationship is added in §4.1 above)

Add the relationship on `FinancePipelineRun` (§4.1 model addendum):

```python
risk_flags: Mapped[list["FinancePipelineRiskFlag"]] = relationship(
    cascade="all, delete-orphan",
    order_by="FinancePipelineRiskFlag.created_at",
)
```

Add new schema `PipelineRiskFlagRead` (Pydantic v2) mirroring the model columns for downstream consumers (HB-4 auditor report will consume this; HB-3 only ships the schema definition).

### §4.3 `backend/app/services/finance_pipeline_service.py` — holiday guard + audit emission + idempotency tightening

**Domain signals (NOT HTTP exceptions).** Per the canonical task pattern in `backend/app/tasks/westmetall_task.py` (which catches domain classes `WestmetallLayoutError` / `CircuitOpenError`, never HTTP framework types), the service layer MUST NOT raise `fastapi.HTTPException`. Two HB-3 domain exceptions are defined at module top of `finance_pipeline_service.py`, above the `FinancePipelineService` class:

```python
class HolidaySkipSignal(Exception):
    """Raised by FinancePipelineService.run_daily_pipeline when run_date is
    not an LME trading day. The route layer translates this to HTTP 409; the
    scheduler task catches the class directly and logs as a skipped run.
    No row, no event, no run — per HB-3 holiday-exempt invariant.
    """


class RunAlreadyInProgressSignal(Exception):
    """Raised by FinancePipelineService.run_daily_pipeline when a row with
    status='running' already exists for the same run_date AND was created
    within the FINANCE_PIPELINE_LOCK_TIMEOUT_SECONDS window. The route layer
    translates this to HTTP 409; the scheduler task catches the class
    directly and logs at INFO level (NOT a failure — overlapping firings are
    a normal operational case, not a stop-condition signal). Distinct class
    from HolidaySkipSignal so the task can disambiguate skip-reasons in
    structured logs.
    """
```

Insert at the top of `run_daily_pipeline` (before line 39's `inputs_hash` computation):

```python
from app.services.lme_calendar import Calendar  # at module top

# inside run_daily_pipeline, after the run_date arg validation:
cal = Calendar()
if not cal.is_business_day(run_date):
    # Holiday-skip: constitutional invariant — no row, no event, no run.
    raise HolidaySkipSignal(
        f"run_date {run_date.isoformat()} is not an LME trading day"
    )
```

(Imports: add `from app.services.lme_calendar import Calendar` at module top. The service module MUST NOT `import fastapi` — the HTTP boundary is the route layer's responsibility per §4.11. `HolidaySkipSignal` is defined in this same module per the block above; no additional import directive is needed inside the service.)

After the existing existing-row check at lines 41–53, tighten the idempotency anchor against the new UNIQUE constraint (§5.2):

- If a row exists with `status = completed`: return as today (line 49 unchanged).
- If a row exists with `status = running` and was created within the last `FINANCE_PIPELINE_LOCK_TIMEOUT_SECONDS` (new env var; default 1800 = 30 min): `raise RunAlreadyInProgressSignal(f"finance pipeline run already in progress for {run_date.isoformat()}")` — the route layer translates this to HTTP 409 (§4.11), the task layer catches it and logs at INFO without rolling back the scheduler (§4.9). This prevents two concurrent scheduler firings from overlapping execution against the new UNIQUE constraint (which would otherwise produce an `IntegrityError` mid-execution). The service layer MUST NOT `import fastapi`.
- Otherwise (existing `running` row past the lock timeout, OR `partial`/`failed`): resume as today (lines 50–53 unchanged).

### §4.4 Silent-exception removal: `_step_mtm_computation` (lines 161–180)

Replace the body at lines 173–180 (the `for contract in contracts: try ... except Exception: pass` block):

```python
processed = 0
for contract in contracts:
    try:
        compute_mtm_for_contract(db, contract.id, run_date)
        processed += 1
    except PriceProvenanceMissing as exc:
        # Per-contract recoverable failure → surface as risk_flag, continue.
        _emit_risk_flag(
            db,
            run_id=run.id,
            flag_type=PipelineRiskFlagType.missing_mtm_price,
            severity=PipelineRiskFlagSeverity.warning,
            subject_entity_type="hedge_contract",
            subject_entity_id=contract.id,
            payload={"reason": str(exc)[:500]},
        )
        # Do NOT increment processed — this contract did not get an MTM.
return processed
```

Where:
- `PriceProvenanceMissing` is the existing exception raised by the canonical-price provenance check (per the MARKET-DATA GOVERNANCE appendix). If the snapshot service raises a different exception class for this failure mode, the executor catches that concrete class — NOT a bare `Exception`. The principle: catch only what the contract documents as recoverable; let structural failures (DB errors, configuration missing) propagate so the step halts.
- `_emit_risk_flag` is a private helper inside `FinancePipelineService` (defined in §4.6) that constructs and flushes a `FinancePipelineRiskFlag` row without committing.

If `compute_mtm_for_contract` does not currently expose a distinct exception class for the missing-price case, the executor adds one in `app/services/mtm_contract_service.py` (out-of-scope additive change — annotate it in the PR description) and references it here. Catching `Exception` and re-raising on a sentinel-string match is FORBIDDEN.

### §4.5 Silent-exception removal: `_step_pl_snapshot` (lines 183–206)

Replace the `try ... except Exception: pass` at lines 193–205. The semantics differ from §4.4 — `SnapshotPrerequisiteMissing` here is NOT semantically `missing_mtm_price` (a P&L prerequisite gap is a distinct failure mode from a missing price quote), and §4.6 already rejects the parallel pattern for cashflow_baseline with the same rationale. Beyond the semantic mismatch, the typical cause of `SnapshotPrerequisiteMissing` is the absence of the upstream MTM snapshot — which means §4.4 has ALREADY emitted a `missing_mtm_price` flag for the same contract earlier in this run. Emitting another flag here would corrupt the `(run_id, subject_entity_id, flag_type)` audit count for the run.

The dispatch resolves this by (a) pre-querying the set of contracts §4.4 already flagged with `missing_mtm_price` for `run.id`, (b) explicitly skipping those contracts (the skip is auditable via the pre-existing flag row — NOT a silent fallback), and (c) letting `SnapshotPrerequisiteMissing` raised for any contract NOT in that set propagate as a structural step failure (matches the §4.6 cashflow pattern: "structural failures propagate to whole-step `failed`").

```python
from sqlalchemy import select, and_

# Pre-query contracts already flagged by §4.4 in this run.
flagged_contract_ids: set[uuid.UUID] = {
    row[0]
    for row in db.execute(
        select(FinancePipelineRiskFlag.subject_entity_id).where(
            and_(
                FinancePipelineRiskFlag.run_id == run.id,
                FinancePipelineRiskFlag.flag_type
                    == PipelineRiskFlagType.missing_mtm_price,
                FinancePipelineRiskFlag.subject_entity_type == "hedge_contract",
                FinancePipelineRiskFlag.subject_entity_id.is_not(None),
            )
        )
    )
}

processed = 0
skipped_due_to_upstream_flag = 0
for contract in contracts:
    if contract.id in flagged_contract_ids:
        # Upstream §4.4 already wrote a missing_mtm_price flag for this
        # contract — P&L snapshot cannot proceed without an MTM and
        # double-flagging would corrupt the audit count. Skip is correlated
        # to the existing flag row (auditable, NOT a silent fallback).
        skipped_due_to_upstream_flag += 1
        continue
    create_pl_snapshot(
        db,
        entity_type="hedge_contract",
        entity_id=contract.id,
        period_start=run_date,
        period_end=run_date,
        commit=False,
    )
    processed += 1
# SnapshotPrerequisiteMissing raised for a contract NOT pre-flagged by
# §4.4 indicates a structural prerequisite gap not caught upstream —
# propagates to the service-level handler at lines 94–101, which marks
# the step `failed` and halts the run. The dispatch deliberately does NOT
# emit a `missing_mtm_price` flag here (semantic mismatch — see §4.6 for
# the parallel rationale) and does NOT add a new enum value (Phase 2 per
# the amendment's deferral list).
return processed
```

The concrete-exception discipline of §4.4 still applies: `except Exception` is FORBIDDEN. The only `SnapshotPrerequisiteMissing` paths through this step body are (a) silently filtered out via the upstream-flag pre-check (auditable), or (b) propagated as a step failure. The `skipped_due_to_upstream_flag` counter is for the step's audit metadata (the `records_processed` field carries `processed`; the `audit_metadata` payload extension carries `skipped_due_to_upstream_flag` so the audit row reconstructs the per-contract decision tree).

If the existing P&L service exposes a different concrete-exception name for the prerequisite-missing failure mode, the executor uses that name and annotates it in the PR description — `SnapshotPrerequisiteMissing` is the binding contract name for this dispatch.

### §4.6 Silent-exception removal: `_step_cashflow_baseline` (lines 208–226)

The cashflow_baseline step is single-op (one snapshot for the whole day, not per-contract). Its failure semantics differ structurally from §4.4 / §4.5 — there is no per-record dimension to surface as a recoverable flag. Per the HB-3 amendment's failure-semantics binding ("structural failures propagate to whole-step `failed` status"), a `CashflowBaselinePrerequisiteMissing` raise here MUST propagate to whole-step `failed` and halt the run. **The dispatch deliberately does NOT emit a `FinancePipelineRiskFlag` from this step**: the binding `flag_type` enum (§4.1) has no value that semantically corresponds to a cashflow-baseline prerequisite failure, and reusing `missing_mtm_price` would corrupt the audit trail (an auditor querying `flag_type='missing_mtm_price'` must see only MTM-related rows). Adding a fifth `flag_type` enum member is explicit Phase 2 deferral per §2 and the amendment's deferral list.

Replace lines 216–226 (no `try:` wrapper — the step body deliberately catches nothing, so every raise propagates to the service-level handler at lines 94–101 which marks the step `failed` and halts the run):

```python
# Single-op step body — no try: wrapper. CashflowBaselinePrerequisiteMissing
# and any other raise propagate to the service-level handler at lines
# 94–101, which marks the step `failed` and halts the run. The run-level
# audit event `finance_pipeline_run_failed_partial` (§4.8) and the
# step-level `finance_pipeline_step_failed` event together carry the
# full failure record; no risk_flag row is written because the binding
# `flag_type` enum (§4.1) does not define a value for this failure mode
# and the dispatch refuses to reuse `missing_mtm_price` (which would
# semantically corrupt the audit trail). Bare `except Exception` is
# FORBIDDEN here — adding any `try/except` to this step body would
# re-introduce silent fallback.
create_cashflow_baseline_snapshot(
    db,
    as_of_date=run_date,
    correlation_id=str(run.id),
    commit=False,
)
return 1
```

The concrete-exception discipline of §4.4 / §4.5 (catch the documented domain class only) still applies: catching `Exception` and falling back is prohibited. The difference is that for cashflow_baseline, NO recoverable class is caught at the step body — every raise propagates and halts the step.

### §4.7 `_emit_risk_flag` helper + implement `_step_risk_flags` body (lines 228–232)

Private helper inside `FinancePipelineService` (place near the bottom of the class, before `_step_risk_flags`):

```python
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
) -> FinancePipelineRiskFlag:
    flag = FinancePipelineRiskFlag(
        run_id=run_id,
        flag_type=flag_type,
        severity=severity,
        subject_entity_type=subject_entity_type,
        subject_entity_id=subject_entity_id,
        payload=payload,
    )
    db.add(flag)
    db.flush()
    return flag
```

Replace the stub `_step_risk_flags` body at lines 228–232 with the four detection routines:

```python
@staticmethod
def _step_risk_flags(db: Session, run_date: date, run: FinancePipelineRun) -> int:
    """HB-3 risk_flags step — 4 detection routines per HB-3 amendment binding."""
    flag_count = 0

    # 1. missing_mtm_price gap-scan — DEDUPLICATED against per-contract flags
    #    already written by §4.4 (`_step_mtm_computation`) earlier in this run.
    #    The MTM step emits `missing_mtm_price` per-contract when
    #    `compute_mtm_for_contract` raises `PriceProvenanceMissing`. This routine
    #    ADDITIONALLY scans for active contracts that have no `PriceQuote` row
    #    for `run_date` at all (a structural-gap class), but EXCLUDES any
    #    `contract_id` that already has a `missing_mtm_price` flag row for
    #    `run_id == run.id`. The exclusion is enforced inside the SQL of
    #    `_query_active_contracts_without_price_for` (anti-join against
    #    `finance_pipeline_risk_flags` — see §4.7-helpers below). This keeps the
    #    `(run_id, subject_entity_id, flag_type)` triple unique within a run
    #    and keeps the `flags_count` field of the `finance_pipeline_step_completed`
    #    audit event consistent with the row count in `finance_pipeline_risk_flags`
    #    (acceptance criterion §10.27 reconstructability invariant).
    contracts_without_price = _query_active_contracts_without_price_for(
        db, run_date, run.id
    )
    for contract in contracts_without_price:
        FinancePipelineService._emit_risk_flag(
            db, run_id=run.id,
            flag_type=PipelineRiskFlagType.missing_mtm_price,
            severity=PipelineRiskFlagSeverity.critical,
            subject_entity_type="hedge_contract",
            subject_entity_id=contract.id,
            payload={"reason": "no PriceQuote row for run_date"},
        )
        flag_count += 1

    # 2. unhedged_exposure_over_guardrail — sum unhedged exposure per counterparty,
    #    flag any that crosses the operational guardrail
    #    (configured via FINANCE_PIPELINE_UNHEDGED_GUARDRAIL_TONNES env, default 1000).
    unhedged = _query_unhedged_exposure_over_guardrail(db, run_date)
    for entry in unhedged:
        FinancePipelineService._emit_risk_flag(
            db, run_id=run.id,
            flag_type=PipelineRiskFlagType.unhedged_exposure_over_guardrail,
            severity=PipelineRiskFlagSeverity.warning,
            subject_entity_type="counterparty",
            subject_entity_id=entry.counterparty_id,
            payload={
                "unhedged_tonnes": str(entry.tonnes),
                "guardrail_tonnes": str(entry.guardrail),
            },
        )
        flag_count += 1

    # 3. kyc_regression_with_active_deals — counterparties whose kyc_status is
    #    not 'approved' but who have at least one active Deal. Per HB-1 amendment,
    #    this is operationally important because the HB-1 KYC gate prevents NEW
    #    RFQs but does not retroactively close existing positions.
    regressions = _query_kyc_regressions_with_active_deals(db)
    for entry in regressions:
        FinancePipelineService._emit_risk_flag(
            db, run_id=run.id,
            flag_type=PipelineRiskFlagType.kyc_regression_with_active_deals,
            severity=PipelineRiskFlagSeverity.critical,
            subject_entity_type="counterparty",
            subject_entity_id=entry.counterparty_id,
            payload={
                "kyc_status": entry.kyc_status,
                "active_deal_count": entry.active_deal_count,
            },
        )
        flag_count += 1

    # 4. workflow_approval_pending_past_expiry — per HB-2 amendment. The HB-2
    #    background sweeper transitions pending/approved past expires_at to
    #    expired, but if the sweeper has not yet fired (or has fallen behind),
    #    HB-3 surfaces the staleness here as a risk_flag.
    stale_approvals = _query_workflow_approvals_pending_past_expiry(db)
    for approval in stale_approvals:
        FinancePipelineService._emit_risk_flag(
            db, run_id=run.id,
            flag_type=PipelineRiskFlagType.workflow_approval_pending_past_expiry,
            severity=PipelineRiskFlagSeverity.warning,
            subject_entity_type="workflow_approval_request",
            subject_entity_id=approval.id,
            payload={
                "current_status": approval.status,
                "expires_at": approval.expires_at.isoformat(),
            },
        )
        flag_count += 1

    return flag_count
```

The four `_query_*` helpers are module-level functions (NOT class methods) in `finance_pipeline_service.py`, defined below the `FinancePipelineService` class. Names + signatures are binding (used in tests below). Bodies are specified inline so the executor has a binding spec to write and test against (acceptance criterion §10.14 requires the `_step_risk_flags` body to be non-trivial; that binding extends transitively to these helpers):

```python
from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent  # pre-existing model
from app.models.counterparty import Counterparty  # pre-existing model
from app.models.deal import Deal  # pre-existing model
from app.models.finance_pipeline import (
    FinancePipelineRiskFlag,
    PipelineRiskFlagType,
)
from app.models.hedge_contract import HedgeContract  # pre-existing model
from app.models.price_quote import PriceQuote  # pre-existing model
from app.models.workflow_approval import (  # pre-existing model (HB-2)
    WorkflowApprovalRequest,
    WorkflowApprovalStatus,
)


def _query_active_contracts_without_price_for(
    db: Session,
    run_date: date,
    run_id: uuid.UUID,
) -> list[HedgeContract]:
    """Active hedge contracts that have NO PriceQuote row for run_date AND
    do NOT yet have a missing_mtm_price flag for this run (P1 #3 dedup —
    routine 1 of `_step_risk_flags` MUST NOT double-flag contracts the MTM
    step already flagged per-record).
    """
    has_price = select(PriceQuote.id).where(
        and_(
            PriceQuote.contract_id == HedgeContract.id,
            PriceQuote.quote_date == run_date,
        )
    ).exists()
    already_flagged = select(FinancePipelineRiskFlag.id).where(
        and_(
            FinancePipelineRiskFlag.run_id == run_id,
            FinancePipelineRiskFlag.flag_type
                == PipelineRiskFlagType.missing_mtm_price,
            FinancePipelineRiskFlag.subject_entity_type == "hedge_contract",
            FinancePipelineRiskFlag.subject_entity_id == HedgeContract.id,
        )
    ).exists()
    stmt = (
        select(HedgeContract)
        .where(HedgeContract.status == "active")  # match existing enum literal
        .where(~has_price)
        .where(~already_flagged)
        .order_by(HedgeContract.id)
    )
    return list(db.execute(stmt).scalars())


# Lightweight row shapes returned by the next three helpers. The executor MAY
# replace these with `typing.NamedTuple` or dataclasses depending on local
# style; the field names below are binding (consumed in §4.7 payload dicts).
@dataclass(frozen=True)
class _UnhedgedRow:
    counterparty_id: uuid.UUID
    tonnes: Decimal
    guardrail: Decimal


@dataclass(frozen=True)
class _KycRegressionRow:
    counterparty_id: uuid.UUID
    kyc_status: str
    active_deal_count: int


def _query_unhedged_exposure_over_guardrail(
    db: Session,
    run_date: date,
) -> list[_UnhedgedRow]:
    """Counterparties whose net unhedged exposure (in tonnes) for run_date
    exceeds the operational guardrail. Guardrail is the env var
    FINANCE_PIPELINE_UNHEDGED_GUARDRAIL_TONNES (default 1000).

    Net unhedged exposure per counterparty := sum(open commercial order tonnes)
    minus sum(active hedge contract tonnes) for the same metal class. The
    aggregation follows the existing `exposure_engine.compute_global_exposure`
    primitive — the helper SHOULD delegate to that primitive to avoid
    duplicating the exposure math, then filter the result by guardrail.
    """
    from app.services.exposure_engine import compute_global_exposure
    guardrail = Decimal(
        os.getenv("FINANCE_PIPELINE_UNHEDGED_GUARDRAIL_TONNES", "1000")
    )
    rows: list[_UnhedgedRow] = []
    for entry in compute_global_exposure(db, as_of_date=run_date):
        if entry.unhedged_tonnes > guardrail:
            rows.append(
                _UnhedgedRow(
                    counterparty_id=entry.counterparty_id,
                    tonnes=entry.unhedged_tonnes,
                    guardrail=guardrail,
                )
            )
    return rows


def _query_kyc_regressions_with_active_deals(
    db: Session,
) -> list[_KycRegressionRow]:
    """Counterparties whose kyc_status is anything OTHER than 'approved' but
    who have at least one active Deal. Per HB-1 amendment, the KYC gate
    prevents NEW RFQs but does not retroactively close existing positions;
    HB-3 surfaces this lag as a `kyc_regression_with_active_deals` flag.
    """
    active_deal_count = (
        select(func.count(Deal.id))
        .where(
            and_(
                Deal.counterparty_id == Counterparty.id,
                Deal.status == "active",  # match existing enum literal
            )
        )
        .scalar_subquery()
    )
    stmt = (
        select(
            Counterparty.id.label("counterparty_id"),
            Counterparty.kyc_status.label("kyc_status"),
            active_deal_count.label("active_deal_count"),
        )
        .where(Counterparty.kyc_status != "approved")
        .where(active_deal_count > 0)
        .order_by(Counterparty.id)
    )
    return [
        _KycRegressionRow(
            counterparty_id=row.counterparty_id,
            kyc_status=row.kyc_status,
            active_deal_count=row.active_deal_count,
        )
        for row in db.execute(stmt)
    ]


def _query_workflow_approvals_pending_past_expiry(
    db: Session,
) -> list[WorkflowApprovalRequest]:
    """WorkflowApprovalRequest rows whose status is `pending` or `approved`
    AND `expires_at < now()`. The HB-2 background sweeper SHOULD transition
    these to `expired`, but if it has not yet fired (or has fallen behind),
    HB-3 surfaces the staleness as a `workflow_approval_pending_past_expiry`
    flag. Both `pending` and `approved` are in scope because either status
    crossing `expires_at` represents an operational gap the auditor needs
    to see.
    """
    stmt = (
        select(WorkflowApprovalRequest)
        .where(
            WorkflowApprovalRequest.status.in_(
                (
                    WorkflowApprovalStatus.pending,
                    WorkflowApprovalStatus.approved,
                )
            )
        )
        .where(WorkflowApprovalRequest.expires_at < func.now())
        .order_by(WorkflowApprovalRequest.id)
    )
    return list(db.execute(stmt).scalars())
```

Imports to add at top of `finance_pipeline_service.py`:

```python
import os
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
```

(Most are already imported per current HEAD — confirm and only add the missing ones. `dataclass`, `Decimal`, and `os` are the most likely additions.)

**Symbol-not-line discipline:** if the column or enum names cited above (e.g. `HedgeContract.status == "active"`, `Counterparty.kyc_status`, `WorkflowApprovalStatus.pending`) drift from the names actually present at the executor's HEAD, the executor follows the SYMBOL (resolves to the current name) — NOT the literal string above. The query semantics (anti-join on already-flagged, sum-of-tonnes vs guardrail, kyc != approved AND active_deal_count > 0, status in {pending, approved} AND expires_at < now) are the binding contract.

### §4.8 Service-layer audit-event emission (six lifecycle events)

The current service emits ZERO audit events (a constitutional violation per HB-3 amendment). Add HMAC-signed emission at every state transition. The pattern uses `AuditTrailService.record_worker_event(...)` (`audit_trail_service.py:122`) so scheduler-triggered runs attribute to the `service:cashflow_pipeline` identity; manual runs continue to also emit through the route-layer `audit_event` dependency (`finance_pipeline.py:31-36`) which captures the human actor — both surfaces persist per §2.

Add a private helper:

```python
@staticmethod
def _emit_audit_event(
    db: Session,
    *,
    entity_type: str,         # "finance_pipeline_run" | "finance_pipeline_step"
    entity_id: uuid.UUID,
    event_type: str,          # one of the six lifecycle event_type strings
    run: FinancePipelineRun,
    step: FinancePipelineStep | None = None,
    actor: str,               # "service:cashflow_pipeline" | "<human actor_sub>"
    trigger_source: PipelineTriggerSource,
    previous_status: str | None = None,
    records_processed: int | None = None,
    error_message: str | None = None,
    flags_count: int | None = None,
) -> None:
    metadata = {
        "run_id": str(run.id),
        "run_date": run.run_date.isoformat(),
        "inputs_hash": run.inputs_hash,
        "trigger_source": trigger_source.value,
        "step_name": step.step_name if step else None,
        "step_number": step.step_number if step else None,
        "records_processed": records_processed,
        "error_message": error_message,
        "previous_status": previous_status,
        "flags_count": flags_count,
    }
    AuditTrailService.record_worker_event(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor=actor,
        source="finance_pipeline_task" if trigger_source == PipelineTriggerSource.scheduler else "finance_pipeline_route",
        metadata=metadata,
    )
```

Emission sites in `run_daily_pipeline`:

| Site | Event |
|---|---|
| After `db.add(run); db.flush()` on fresh-creation path (line 61) | `finance_pipeline_run_started`, `previous_status=None` |
| After the resume-path `run.status = PipelineRunStatus.running` (line 52) | `finance_pipeline_run_started`, `previous_status="partial"` |
| Inside the per-step loop, right after `step.status = PipelineStepStatus.running; db.flush()` (line 79–81) | `finance_pipeline_step_started`, `previous_status="pending"` |
| Inside the per-step loop, right after `step.status = PipelineStepStatus.completed; ...; db.flush()` (line 87–93) | `finance_pipeline_step_completed`, `previous_status="running"`, `records_processed=records`, `flags_count=<count if step_name=='risk_flags' else None>` |
| Inside the per-step loop, right after `step.status = PipelineStepStatus.failed; ...; db.flush()` (line 95–101) | `finance_pipeline_step_failed`, `previous_status="running"`, `error_message=str(exc)[:500]` |
| After the `if not failed:` block sets `run.status = PipelineRunStatus.completed` (line 105) | `finance_pipeline_run_completed`, `previous_status="running"`, `records_processed=<sum across steps>` |
| Inside the failed-path early-break, after setting `run.status = PipelineRunStatus.partial` (line 98–99) | `finance_pipeline_run_failed_partial`, `previous_status="running"`, `error_message=run.error_message` |

The `actor` and `trigger_source` values are passed into `run_daily_pipeline` as new REQUIRED keyword-only parameters — there is no default for `actor`, and the call site MUST supply a non-empty string. This enforces the binding "`actor` is always populated in the audit payload" invariant at the type-system layer (no silent `null` actor possible):

```python
@staticmethod
def run_daily_pipeline(
    db: Session,
    run_date: date,
    *,
    commit: bool = True,
    trigger_source: PipelineTriggerSource = PipelineTriggerSource.manual,
    actor: str,  # REQUIRED — see actor-validation guard below
) -> FinancePipelineRun:
    if not actor:
        raise ValueError(
            "run_daily_pipeline requires a non-empty actor (service identity "
            "or human actor_sub). Audit-payload integrity invariant per HB-3."
        )
```

The route layer (§4.11) sets `actor` from `Depends(get_current_actor_sub)` (already non-empty by JWT-validator invariant); the scheduler task (§4.9) sets `actor="service:cashflow_pipeline"` and `trigger_source=PipelineTriggerSource.scheduler`. The `trigger_source` default is `PipelineTriggerSource.manual` so the existing in-tree call sites that already pass through the manual route remain source-compatible when this dispatch is implemented (the route call site updates `trigger_source` explicitly in §4.11). The `actor` parameter has NO default — every caller, including future test fixtures, must pass it explicitly. Tests that call `run_daily_pipeline` directly use a sentinel like `actor="test:fixture"`.

Audit-query path note: with `record_worker_event` semantics (§4.8 above), the binding payload fields live at `payload.metadata.<field>` at runtime, while `payload.actor` and `payload.source` are top-level meta fields produced by the helper. Auditor JSONB queries against the constitutional schema must therefore use `payload -> 'metadata' ->> 'trigger_source'` and `payload -> 'metadata' ->> 'run_id'` (NOT `payload ->> 'trigger_source'`). Acceptance criterion §10.24 implicitly carries this through (the grep over emission sites confirms the helper is the right one; the runtime shape follows from the helper choice).

### §4.9 New task module: `backend/app/tasks/finance_pipeline_task.py`

Mirror the existing `westmetall_task.py` pattern (lines 1–80 of that file are the reference shape — own DB session, log start/success/failure, never crash the scheduler):

```python
"""Scheduled background task for the daily Finance Pipeline run.

Runs every business day at 19:00 UTC (after Westmetall 18:00 UTC ingest)
under the standalone Railway scheduler service. Holiday-skip is enforced
inside FinancePipelineService.run_daily_pipeline via lme_calendar.

Per HB-3 amendment: scheduler-triggered runs attribute to the existing
service:cashflow_pipeline identity (AUTHORIZATION MATRIX line 250 already
covers 'cashflow_ledger + finance_pipeline writes').
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.finance_pipeline import PipelineTriggerSource
from app.services.finance_pipeline_service import (
    FinancePipelineService,
    HolidaySkipSignal,
    RunAlreadyInProgressSignal,
)

logger = get_logger()

FINANCE_PIPELINE_SERVICE_ACTOR = "service:cashflow_pipeline"


def run_finance_pipeline_daily() -> None:
    """Execute one daily Finance Pipeline cycle.

    Holiday-skips raise the `HolidaySkipSignal` domain exception inside the
    service; this task catches that class DIRECTLY and logs without alerting
    (matches the `WestmetallLayoutError` / `CircuitOpenError` precedent in
    `westmetall_task.py` — no HTTP framework types crossing layer boundaries,
    no fragile string match on `exc.detail`). Other exceptions are logged
    as failures and surface via the audit-event absence-of-completion signal.
    """
    today = datetime.now(timezone.utc).date()
    logger.info("finance_pipeline_task_start", run_date=str(today))
    session = SessionLocal()
    try:
        run = FinancePipelineService.run_daily_pipeline(
            session,
            today,
            commit=False,
            trigger_source=PipelineTriggerSource.scheduler,
            actor=FINANCE_PIPELINE_SERVICE_ACTOR,
        )
        session.commit()
        logger.info(
            "finance_pipeline_task_success",
            run_id=str(run.id),
            run_date=str(today),
            status=run.status.value,
            steps_completed=run.steps_completed,
        )
    except HolidaySkipSignal:
        logger.info("finance_pipeline_task_skipped_holiday", run_date=str(today))
    except RunAlreadyInProgressSignal as exc:
        # Overlapping firings are a normal operational case (e.g. APScheduler
        # misfire grace + manual run racing) — INFO log, NOT a failure, so
        # the absence-of-completion stop-condition signal isn't false-tripped.
        logger.info(
            "finance_pipeline_task_skipped_already_running",
            run_date=str(today),
            detail=str(exc)[:200],
        )
    except Exception as exc:  # noqa: BLE001 — task boundary, NEVER crash the scheduler
        logger.exception(
            "finance_pipeline_task_failure",
            run_date=str(today),
            error=str(exc)[:500],
        )
        session.rollback()
    finally:
        session.close()
```

Note: the bare `except Exception` AT THE TASK BOUNDARY is permitted (matches the existing `westmetall_task.py` pattern at lines 92–97); the constitutional "no silent fallback" applies INSIDE step bodies, where errors must surface as audit events / risk flags / step-level failure. The task boundary's role is to keep the scheduler process alive across one bad day; the run-level audit event for the failure already fired inside the service layer (per §4.8), so the audit trail is not silent. **`fastapi` is NOT imported in this module** — domain class `HolidaySkipSignal` is the holiday-skip control signal per §4.3.

### §4.10 Scheduler registration in `backend/app/tasks/scheduler.py`

Mirror the existing pattern at lines 39–63 (three `add_job` calls). Insert a fourth `add_job` between the Westmetall job and the RFQ-timeout job:

```python
# At top of file:
from app.tasks.finance_pipeline_task import run_finance_pipeline_daily

# Inside start_scheduler(), after the existing _scheduler.add_job for run_westmetall_ingestion:
_scheduler.add_job(
    run_finance_pipeline_daily,
    trigger="cron",
    hour=int(os.getenv("FINANCE_PIPELINE_CRON_HOUR", "19")),
    minute=int(os.getenv("FINANCE_PIPELINE_CRON_MINUTE", "0")),
    id="finance_pipeline_daily",
    replace_existing=True,
    misfire_grace_time=3600,  # allow up to 1h late execution
)
```

Default 19:00 UTC is intentional — 1h after Westmetall's 18:00 UTC ingest so the canonical day's prices are persisted before MTM computation reads them. Override via `FINANCE_PIPELINE_CRON_HOUR` / `FINANCE_PIPELINE_CRON_MINUTE` env vars (Railway dashboard ownership per `docs/runbook-railway.md`).

The existing `logger.info("scheduler_started", jobs=[j.id for j in _scheduler.get_jobs()])` at lines 65–68 surfaces the new job id in the startup log without further changes.

### §4.11 Route layer: `backend/app/api/routes/finance_pipeline.py` — set `triggered_by="manual"` + translate `HolidaySkipSignal` → HTTP 409

Pass `trigger_source=PipelineTriggerSource.manual` and `actor=actor_sub` into the service call at line 42–43, AND wrap the service call so the new domain exception is translated to HTTP 409 at the route boundary (the only layer permitted to emit HTTP framework types):

```python
# BEFORE
run = FinancePipelineService.run_daily_pipeline(
    db, body.run_date, commit=False
)

# AFTER
try:
    run = FinancePipelineService.run_daily_pipeline(
        db,
        body.run_date,
        commit=False,
        trigger_source=PipelineTriggerSource.manual,
        actor=actor_sub,
    )
except HolidaySkipSignal as exc:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"{exc}; pipeline skipped per HB-3 holiday-exempt invariant.",
    ) from exc
except RunAlreadyInProgressSignal as exc:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(exc),
    ) from exc
```

The existing `Depends(audit_event(...))` at lines 31–36 (the `manual_run_triggered` route-level event) is preserved unchanged — this dispatch does NOT remove the route-layer audit event. The HB-3 holiday-skip translation is the only behavioral change at this route; the existing 200/200-with-resumed-run response shape is untouched on business days.

Verify imports at top of the route module — the new import directives are:

- `from app.models.finance_pipeline import PipelineTriggerSource`
- `from app.services.finance_pipeline_service import HolidaySkipSignal, RunAlreadyInProgressSignal`
- `from fastapi import HTTPException, status` (already imported per current HEAD; confirm — if absent, add)

### §4.12 Service-identity binding documentation (NO matrix edit)

Confirm via grep that the AUTHORIZATION MATRIX line 250 of `docs/governance.md` still reads "cashflow_ledger + finance_pipeline writes". This dispatch does NOT modify the matrix. If a future audit pass identifies that the matrix scope description needs explicit "scheduled" vs "manual" disambiguation, that is a follow-on amendment, not HB-3 scope.

## §5 Database / Alembic changes

### §5.1 New revision

Run `alembic revision -m "hb_3_finance_pipeline_hardening"` after capturing the current head per §3. The new revision filename follows the existing numeric chain pattern. `down_revision` is set to the head captured in §3.

### §5.2 UNIQUE on `finance_pipeline_runs.run_date`

In `upgrade()`:

```python
op.create_unique_constraint(
    "uq_finance_pipeline_runs_run_date",
    "finance_pipeline_runs",
    ["run_date"],
)
```

In `downgrade()`:

```python
op.drop_constraint(
    "uq_finance_pipeline_runs_run_date",
    "finance_pipeline_runs",
    type_="unique",
)
```

Both Postgres and SQLite support UNIQUE constraints natively — no `with_variant` fallback required. (SQLite's `CREATE TABLE` would need `batch_alter_table` for the ALTER TABLE ADD CONSTRAINT path; the executor uses `with op.batch_alter_table('finance_pipeline_runs'):` wrapper if running against SQLite locally, per the existing migration patterns under `backend/alembic/versions/`.)

### §5.3 New `finance_pipeline_risk_flags` table + enums

In `upgrade()`:

```python
flag_type_enum = sa.Enum(
    "missing_mtm_price",
    "unhedged_exposure_over_guardrail",
    "kyc_regression_with_active_deals",
    "workflow_approval_pending_past_expiry",
    name="pipeline_risk_flag_type",
)
severity_enum = sa.Enum(
    "informational",
    "warning",
    "critical",
    name="pipeline_risk_flag_severity",
)
flag_type_enum.create(op.get_bind(), checkfirst=True)
severity_enum.create(op.get_bind(), checkfirst=True)

op.create_table(
    "finance_pipeline_risk_flags",
    sa.Column("id", postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
              primary_key=True),
    sa.Column("run_id", postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
              sa.ForeignKey("finance_pipeline_runs.id"), nullable=False),
    sa.Column("flag_type", flag_type_enum, nullable=False),
    sa.Column("severity", severity_enum, nullable=False),
    sa.Column("subject_entity_type", sa.String(64), nullable=False),
    sa.Column("subject_entity_id", postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
              nullable=True),
    sa.Column("payload", postgresql.JSONB().with_variant(sa.Text(), "sqlite"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True),
              server_default=sa.func.now(), nullable=False),
)
op.create_index(
    "ix_finance_pipeline_risk_flags_run_id",
    "finance_pipeline_risk_flags",
    ["run_id"],
)
op.create_index(
    "ix_finance_pipeline_risk_flags_run_id_severity",
    "finance_pipeline_risk_flags",
    ["run_id", "severity"],
)
# DB-level dedup defense for the (run_id, subject_entity_id, flag_type)
# triple. §4.7 routine 1 + §4.5 cross-step skip provide application-level
# anti-join, but the UNIQUE constraint below is the authoritative defense
# against any future second-emission code path silently inserting a
# duplicate row. Matches the run_date idempotency pattern in §5.2.
#
# Note on nullable subject_entity_id: both Postgres and SQLite treat NULL
# as DISTINCT in UNIQUE constraints by default. This permits multiple
# run-scoped flags (where subject_entity_id is NULL) of the same type
# within a run — which is intentional (e.g. a missed-prior-day flag with
# subject_entity_id=NULL could occur once per detection pass without
# blocking the constraint). For NON-NULL subject_entity_id, the constraint
# is fully effective.
op.create_unique_constraint(
    "uq_finance_pipeline_risk_flags_run_subject_type",
    "finance_pipeline_risk_flags",
    ["run_id", "subject_entity_id", "flag_type"],
)
```

In `downgrade()`:

```python
op.drop_constraint(
    "uq_finance_pipeline_risk_flags_run_subject_type",
    "finance_pipeline_risk_flags",
    type_="unique",
)
op.drop_index("ix_finance_pipeline_risk_flags_run_id_severity", table_name="finance_pipeline_risk_flags")
op.drop_index("ix_finance_pipeline_risk_flags_run_id", table_name="finance_pipeline_risk_flags")
op.drop_table("finance_pipeline_risk_flags")
sa.Enum(name="pipeline_risk_flag_severity").drop(op.get_bind(), checkfirst=True)
sa.Enum(name="pipeline_risk_flag_type").drop(op.get_bind(), checkfirst=True)
```

### §5.4 `triggered_by` column on `finance_pipeline_runs`

In `upgrade()`:

```python
trigger_source_enum = sa.Enum("scheduler", "manual", name="pipeline_trigger_source")
trigger_source_enum.create(op.get_bind(), checkfirst=True)

op.add_column(
    "finance_pipeline_runs",
    sa.Column(
        "triggered_by",
        trigger_source_enum,
        nullable=False,
        server_default="manual",
    ),
)
# Backfill existing rows are already 'manual' via server_default; data migration
# preserves provenance — every existing row was produced by the manual route.
```

In `downgrade()`:

```python
op.drop_column("finance_pipeline_runs", "triggered_by")
sa.Enum(name="pipeline_trigger_source").drop(op.get_bind(), checkfirst=True)
```

### §5.5 Chain hygiene

- Single-head invariant verified post-revision via `cd backend && alembic heads` (must report one head).
- `backend/tests/test_alembic_chain.py` must continue to pass — no ancestry rewrites.

## §6 Frontend changes

Minimum-viable per the transport-partner clause (per `feedback_dispatch_transport_partner_clause` — when §4 ships a new backend response shape, §6 must pre-authorize the client patch needed to consume it):

1. **Regenerate `frontend-svelte/src/lib/api/schema.d.ts`** from the running backend's `/openapi.json` via `npm run api:types` (per `CLAUDE.md` frontend section). The two new schema fields (`PipelineRunRead.triggered_by`, `PipelineRunRead.risk_flags_count`) appear in the regenerated file.
2. **Surface the new fields on existing pipeline detail pages.** If a route under `frontend-svelte/src/routes/(protected)/finance/pipeline/**/*` consumes `PipelineRunRead`, render the two new fields. If no such page currently exists, no UI change is required — schema.d.ts regen alone closes the transport-partner clause.
3. **CI drift guard:** `npm run api:types:check` must pass in CI (per the existing CI workflow `.github/workflows/ci.yml`). The executor runs this locally before the final push.
4. **No new frontend route, no new component, no ECharts changes.** The auditor's daily report frontend lives under HB-4 scope.

## §7 Tests

All backend tests run via `python -m pytest -x -q` (SQLite in-memory per `backend/tests/conftest.py`). Coverage target ≥ 85% on `finance_pipeline_service.py` and `finance_pipeline_task.py`.

### §7.1 Service-layer tests — new file `backend/tests/test_finance_pipeline_hb3.py`

Required cases (at least one test function per bullet):

- `test_holiday_skip_service_raises_signal` — pass a Saturday `run_date` directly to `FinancePipelineService.run_daily_pipeline`; assert `HolidaySkipSignal` raised; assert NO row inserted into `finance_pipeline_runs`; assert NO audit event emitted (query `AuditEvent` by `entity_type IN ("finance_pipeline_run", "finance_pipeline_step")` → zero rows). Confirms the service layer raises a DOMAIN exception, NOT `fastapi.HTTPException`.
- `test_holiday_skip_route_returns_409` — POST `/finance/pipeline/run` with `risk_manager` JWT and a Saturday `run_date` body; assert HTTP 409 response with `detail` containing `"not an LME trading day"`. Confirms the route layer translates the domain signal correctly; the assertion lives in `backend/tests/test_finance_pipeline_routes.py` if the project's route-test convention puts it there — otherwise inline in the same HB-3 test file.
- `test_holiday_skip_task_logs_skipped_no_exception` — see §7.3 (`test_task_holiday_logs_skipped_no_exception`). The task catches `HolidaySkipSignal` directly (no `HTTPException` / no string match).
- `test_business_day_completes_all_six_steps` — happy path; assert `run.status == completed`, `run.steps_completed == 6`, six `finance_pipeline_step_completed` audit events + one `finance_pipeline_run_started` + one `finance_pipeline_run_completed`.
- `test_unique_run_date_constraint` — two concurrent `SessionLocal()` instances both call `run_daily_pipeline` for the same `run_date`; assert the second raises `RunAlreadyInProgressSignal` (lock-timeout branch in §4.3) OR `IntegrityError` (race past the lock check), NEVER `fastapi.HTTPException`; assert only ONE row in `finance_pipeline_runs` post-test.
- `test_concurrent_run_lock_route_returns_409` — POST `/finance/pipeline/run` twice for the same `run_date` against a fixture that holds the first run open in `running` status; assert second POST returns HTTP 409. Confirms route layer translates the `RunAlreadyInProgressSignal` domain exception.
- `test_concurrent_run_lock_task_logs_info_not_failure` — patch the service to raise `RunAlreadyInProgressSignal`; call `run_finance_pipeline_daily()`; assert log line `"finance_pipeline_task_skipped_already_running"` recorded at INFO level and `"finance_pipeline_task_failure"` is NOT recorded. Confirms the operational distinction between skip and failure (no false stop-condition signal).
- `test_idempotency_completed_run_returns_existing` — call `run_daily_pipeline` twice for the same `run_date` sequentially; assert second call returns the same `run.id` as the first; assert ONE row in `finance_pipeline_runs`; assert exactly 6 step rows; assert no duplicate audit events.
- `test_resume_from_partial` — simulate a `partial` run (set status manually + one step to `failed`); call `run_daily_pipeline` again; assert the failed step retried, run transitions to `completed`; assert `finance_pipeline_run_started` event with `previous_status="partial"` emitted.
- `test_mtm_step_recoverable_emits_risk_flag` — patch `compute_mtm_for_contract` to raise the recoverable exception class for one contract out of three; assert two contracts processed, one `FinancePipelineRiskFlag` row with `flag_type=missing_mtm_price` + `subject_entity_id=<the failed contract>`; assert step status `completed`, not `failed`.
- `test_cashflow_baseline_prerequisite_failure_halts_step` — patch `create_cashflow_baseline_snapshot` to raise `CashflowBaselinePrerequisiteMissing`; assert the `cashflow_baseline` step transitions to `failed`; assert the run transitions to `partial`; assert `finance_pipeline_step_failed` + `finance_pipeline_run_failed_partial` audit events emitted; assert NO `FinancePipelineRiskFlag` row written for this run (the prerequisite failure does NOT surface as a flag — see §4.6 rationale: the binding `flag_type` enum has no semantically correct member for this failure mode, and reusing `missing_mtm_price` would corrupt the audit trail). Subsequent steps (`risk_flags`, `summary`) MUST NOT execute.
- `test_pl_step_skips_contracts_flagged_by_mtm_step_without_double_flagging` — fixture seeds three active contracts: one with no `PriceQuote` (so §4.4 emits one `missing_mtm_price` flag), two with prices. Run the pipeline. Assert §4.5 reads exactly ONE row in `finance_pipeline_risk_flags` for the contract (NOT two), and that `_step_pl_snapshot.processed == 2`. The skipped contract has NO additional flag row written; the existing §4.4 flag is the canonical record.
- `test_pl_step_propagates_unexplained_prerequisite_missing_to_step_failed` — fixture seeds an active contract that has a `PriceQuote` but for which `create_pl_snapshot` is patched to raise `SnapshotPrerequisiteMissing` (simulating a prerequisite gap that §4.4 did NOT catch — i.e. NOT pre-flagged). Assert the `pl_snapshot` step transitions to `failed`; assert the run transitions to `partial`; assert `finance_pipeline_step_failed` + `finance_pipeline_run_failed_partial` audit events emitted; assert NO `FinancePipelineRiskFlag` row is written for this run (the structural failure surfaces only through step status + audit events, NOT through a misattributed flag).
- `test_mtm_step_structural_failure_halts_run` — patch `compute_mtm_for_contract` to raise a non-recoverable exception (e.g. `sqlalchemy.exc.DatabaseError`); assert run transitions to `partial`, the failed step has status `failed`, `finance_pipeline_step_failed` audit event emitted, subsequent steps NOT executed.
- `test_risk_flags_step_emits_all_four_flag_types` — fixture seeds (a) a contract without a PriceQuote for run_date → `missing_mtm_price`, (b) a counterparty with unhedged tonnes above guardrail → `unhedged_exposure_over_guardrail`, (c) a counterparty with `kyc_status != approved` + an active Deal → `kyc_regression_with_active_deals`, (d) a `pending` workflow_approval past `expires_at` → `workflow_approval_pending_past_expiry`. Assert four `FinancePipelineRiskFlag` rows with matching `flag_type` enum values.
- `test_risk_flags_step_zero_flags_is_valid` — fixture seeds a clean state; assert step completes, returns 0, step status `completed`.
- `test_unique_constraint_blocks_duplicate_flag_emission` — directly insert two `FinancePipelineRiskFlag` rows with the same `(run_id, subject_entity_id, flag_type)` triple (non-null subject_entity_id); assert the second insert raises `IntegrityError`. Confirms the DB-level defense from §5.3 is shipped, not just declared. The application-level anti-join in §4.7 is a fast-path; the constraint is the authoritative invariant.
- `test_no_double_flagging_of_missing_mtm_price_per_contract` — fixture seeds an active contract with no `PriceQuote` row for `run_date` (so both §4.4 per-contract handler AND §4.7 routine 1 would otherwise emit). Run the full pipeline. Assert EXACTLY ONE `FinancePipelineRiskFlag` row exists with `(run_id=run.id, flag_type=missing_mtm_price, subject_entity_id=contract.id)` — NOT two. The dedup invariant is on the triple itself. Separately, assert the `flags_count` field of the `finance_pipeline_step_completed` event for the `risk_flags` step equals `0` (the return value of `_step_risk_flags`, which anti-joined the only candidate out per §4.7 routine 1) — `flags_count` is bound to "flags written BY this step" per §4.8, NOT to the total run row count.
- `test_pipeline_steps_is_tuple` — `assert isinstance(PIPELINE_STEPS, tuple)`; static check that mutability was removed.
- `test_six_audit_events_emitted_per_full_run` — assert exactly 1×`run_started` + 6×`step_started` + 6×`step_completed` + 1×`run_completed` events emitted; check the common payload fields (`run_id`, `run_date`, `inputs_hash`, `trigger_source`, `step_name`/`step_number` for step events) are populated correctly.
- `test_scheduled_run_attributes_to_service_cashflow_pipeline` — call `run_daily_pipeline` with `trigger_source=scheduler` and `actor="service:cashflow_pipeline"`; assert the emitted audit-event payload has `"actor": "service:cashflow_pipeline"` and `"trigger_source": "scheduler"`.
- `test_manual_run_attributes_to_human_actor` — call via the route layer with a `risk_manager` JWT fixture; assert audit event payload has `"actor": "<actor_sub>"` and `"trigger_source": "manual"` (plus the existing route-level `manual_run_triggered` event is also present, distinguishable by `event_type`).

### §7.2 Reconstruction test — same file

- `test_reconstruct_past_run_from_four_tables_alone` — execute a full pipeline run, capture `run.id`, then close the session and open a new SessionLocal. Reconstruct the run's complete state (run + steps + risk_flags + audit_events) by querying ONLY those four tables. Assert reconstructed state matches captured state in: status, all six step statuses, records_processed per step, all risk_flag rows, all audit event payloads. NO other data source (logs, operational state, env vars) is consulted by the reconstruction. This binds the HB-3 amendment's reconstructability invariant.

### §7.3 Task-boundary tests — new file `backend/tests/test_finance_pipeline_task.py`

- `test_task_holiday_logs_skipped_no_exception` — set `today` to a Saturday via patch; call `run_finance_pipeline_daily()`; assert no exception escaped, log line `"finance_pipeline_task_skipped_holiday"` recorded.
- `test_task_business_day_logs_success` — happy path; assert log line `"finance_pipeline_task_success"` with `status="completed"`.
- `test_task_internal_failure_logs_exception_no_crash` — patch `run_daily_pipeline` to raise `RuntimeError("simulated DB outage")`; assert task returns without raising; assert log line `"finance_pipeline_task_failure"` recorded.

### §7.4 Scheduler-registration test — new file `backend/tests/test_finance_pipeline_scheduler.py`

- `test_scheduler_registers_finance_pipeline_daily_job` — with `SCHEDULER_DISABLED=false` patched, call `start_scheduler()`; assert the running scheduler has a job with id `"finance_pipeline_daily"`; tear down via `stop_scheduler()`.
- `test_scheduler_skips_when_disabled` — with `SCHEDULER_DISABLED=true`, call `start_scheduler()`; assert no scheduler instance created, log line `"scheduler_disabled"` recorded.

### §7.5 RBAC matrix tests — extension of existing `backend/tests/test_rbac_matrix_enforcement.py`

- `test_trader_cannot_trigger_finance_pipeline_manual` — POST `/finance/pipeline/run` with a `trader`-only JWT; assert 403.
- `test_auditor_can_read_pipeline_runs` — GET `/finance/pipeline/runs` with `auditor` JWT; assert 200.
- `test_auditor_cannot_trigger_pipeline_manual` — POST `/finance/pipeline/run` with `auditor`-only JWT; assert 403 (no write scope per AUTHORIZATION MATRIX).

### §7.6 Frontend tests

- If `frontend-svelte/src/routes/(protected)/finance/pipeline/**/*` exists and renders pipeline runs, add a Vitest unit test asserting `triggered_by` and `risk_flags_count` are surfaced (string match on rendered output).
- If no such route exists, no frontend test is added; only the schema.d.ts drift guard via `npm run api:types:check` runs in CI.

### §7.7 Full-suite regression

Before push, the executor runs `python -m pytest -x -q` from `backend/` and `npm run check && npm run test` from `frontend-svelte/`. All must pass — no `--no-verify` bypass of failing tests.

## §8 Audit-trail emission

Every mutation in this PR's scope emits an HMAC-signed audit row via `AuditTrailService.record_worker_event(...)` (for scheduled runs) or via the route-layer `audit_event` Depends + the service-layer `_emit_audit_event` helper (for manual runs). Six lifecycle event types per HB-3 amendment binding:

| event_type | entity_type | Emission site (file:approx-line) | trigger_source |
|---|---|---|---|
| `finance_pipeline_run_started` | `finance_pipeline_run` | `finance_pipeline_service.py` — after `db.add(run); db.flush()` (~line 62) AND after resume's `run.status = running` (~line 53) | scheduler \| manual |
| `finance_pipeline_run_completed` | `finance_pipeline_run` | `finance_pipeline_service.py` — after `if not failed: run.status = completed` (~line 105) | scheduler \| manual |
| `finance_pipeline_run_failed_partial` | `finance_pipeline_run` | `finance_pipeline_service.py` — inside the `except` branch after `run.status = partial` (~line 99) | scheduler \| manual |
| `finance_pipeline_step_started` | `finance_pipeline_step` | `finance_pipeline_service.py` — after `step.status = running; db.flush()` (~line 81) | scheduler \| manual |
| `finance_pipeline_step_completed` | `finance_pipeline_step` | `finance_pipeline_service.py` — after `step.status = completed; ...; db.flush()` (~line 93) | scheduler \| manual |
| `finance_pipeline_step_failed` | `finance_pipeline_step` | `finance_pipeline_service.py` — after `step.status = failed; ...; db.flush()` (~line 101) | scheduler \| manual |

Per HB-3 amendment "Common payload fields (binding)" subsection, ALL six events carry the binding payload schema: `run_id`, `run_date`, `inputs_hash`, `actor`, `trigger_source`, `step_name`/`step_number` (nullable on run-level events), `records_processed` (nullable), `error_message` (nullable), `previous_status` (nullable on creation), `flags_count` (populated on `step_completed` only for `step_name == "risk_flags"`).

The existing route-layer `manual_run_triggered` event at `app/api/routes/finance_pipeline.py:31-36` is PRESERVED — it captures human-intent (route-layer record) and is distinct from the six lifecycle events (state-machine record). Both surfaces persist.

WORM sink invariant per HB-3 amendment: no new admin route mutates `AuditEvent` rows. The implementation MUST NOT introduce any such route.

## §9 Docs

### §9.1 Runbook expansion: `docs/runbook-railway.md`

Add a new "Finance Pipeline (HB-3)" section after the existing scheduler section. Required content:

- Service responsible: Railway `scheduler` service (the standalone process running `python -m app.scheduler_main`).
- Schedule: daily 19:00 UTC by default; override via `FINANCE_PIPELINE_CRON_HOUR` / `FINANCE_PIPELINE_CRON_MINUTE`.
- Env vars owned by Railway dashboard (not `railway.json`): `FINANCE_PIPELINE_CRON_HOUR`, `FINANCE_PIPELINE_CRON_MINUTE`, `FINANCE_PIPELINE_LOCK_TIMEOUT_SECONDS`, `FINANCE_PIPELINE_UNHEDGED_GUARDRAIL_TONNES`.
- Observable absence-of-completion signal: query `AuditEvent` for `entity_type='finance_pipeline_run'` + `event_type='finance_pipeline_run_completed'` + the day's range on `timestamp_utc`. Zero rows = the day did not close. Operational query example included.
- Failure-recovery procedure: `partial` run resumed by re-firing the task (either by waiting for the next 19:00 UTC tick + holiday-skip carryover, OR by manual `POST /finance/pipeline/run` from a `risk_manager` JWT for the affected `run_date`).
- Sign-off line: security/platform owner signature required per pilot brief §HB-3 "Closure evidence required" before HB-3 closes.

### §9.2 No CLAUDE.md update

CLAUDE.md already mentions `cashflow_pipeline` service identity (per the project memory; the scheduler section also already covers `SCHEDULER_DISABLED` discipline). No further edits required.

### §9.3 No frontend docs update

Per §6, the frontend change is schema regen + minimum surface; no new frontend doc page.

## §10 Acceptance criteria

Each criterion is a verifiable command against the merged HEAD. The PR is acceptable when ALL items pass.

1. `grep -n "Finance Pipeline daily reconstructability (binding, Pilot Hard Blocker 3)" docs/governance.md` returns exactly one match. (Amendment present.)
2. `grep -n "isinstance(PIPELINE_STEPS, tuple)" backend/tests/test_finance_pipeline_hb3.py` returns ≥ 1 match AND the test passes — `PIPELINE_STEPS` immutability binding test exists and passes.
3. `python -c "from app.models.finance_pipeline import PIPELINE_STEPS; assert isinstance(PIPELINE_STEPS, tuple); print('OK')"` prints `OK`. (Type binding.)
4. `python -m pytest backend/tests/test_finance_pipeline_hb3.py -v` reports ≥ 15 tests, all passing.
5. `python -m pytest backend/tests/test_finance_pipeline_task.py -v` reports ≥ 3 tests, all passing.
6. `python -m pytest backend/tests/test_finance_pipeline_scheduler.py -v` reports ≥ 2 tests, all passing.
7. `python -m pytest backend/tests/test_rbac_matrix_enforcement.py -v -k "finance_pipeline"` reports ≥ 3 tests, all passing.
8. `python -m pytest backend/tests/ -x -q` — full backend suite passes.
9. `cd backend && alembic heads` reports a single head whose revision identifier corresponds to the HB-3 hardening revision (and `down_revision` is the HB-2 head captured in §3).
10. `cd backend && alembic upgrade head && alembic downgrade -1 && alembic upgrade head` — forward/reverse roundtrip succeeds without error against a fresh SQLite DB.
11. `python -m pytest backend/tests/test_alembic_chain.py -v` — single-head invariant test passes.
12. `grep -rn "except Exception: pass" backend/app/services/finance_pipeline_service.py | wc -l` returns `0` (no silent exception swallowing inside step bodies).
13. `grep -rn "return 0" backend/app/services/finance_pipeline_service.py | grep -v "_step_risk_flags" | wc -l` returns `0` OR every remaining occurrence is an INTENDED zero-records return (e.g. `cashflow_baseline` recoverable path returning 0), NEVER a stub. The executor confirms each remaining `return 0` is intentional in the PR description.
14. `grep -n "_step_risk_flags" backend/app/services/finance_pipeline_service.py` — the function body is non-trivial (>10 lines including the four detection routines); a stub of fewer than 5 effective lines fails this criterion.
15. `grep -n "finance_pipeline_daily" backend/app/tasks/scheduler.py` returns ≥ 1 match (scheduler registration present).
16. `grep -n "run_finance_pipeline_daily" backend/app/tasks/finance_pipeline_task.py` returns ≥ 1 match (task module present).
17. `grep -n "service:cashflow_pipeline" backend/app/tasks/finance_pipeline_task.py` returns ≥ 1 match (service identity binding present).
18. `grep -rn "PipelineTriggerSource\|PipelineRiskFlagType\|PipelineRiskFlagSeverity" backend/app/models/finance_pipeline.py | wc -l` returns ≥ 3 (three new enums declared).
19. `grep -n "FinancePipelineRiskFlag" backend/app/models/finance_pipeline.py` — model class present.
20. `cd frontend-svelte && npm run api:types:check` — schema.d.ts drift guard passes.
21. `grep -n "triggered_by" frontend-svelte/src/lib/api/schema.d.ts` returns ≥ 1 match (schema regen captured the new field).
22. `grep -n "risk_flags_count" frontend-svelte/src/lib/api/schema.d.ts` returns ≥ 1 match.
23. `cd frontend-svelte && npm run check && npm run test` passes.
24. `grep -nE "finance_pipeline_(run|step)_(started|completed|failed|failed_partial)" backend/app/services/finance_pipeline_service.py | wc -l` returns ≥ 6 (six lifecycle event_type emissions).
25. `grep -n "Finance Pipeline (HB-3)" docs/runbook-railway.md` returns ≥ 1 match (runbook section authored).
26. End-to-end manual test: with `SCHEDULER_DISABLED=false` against a local stack, the scheduler fires `finance_pipeline_daily` at the next 19:00 UTC tick (or accelerate via `FINANCE_PIPELINE_CRON_HOUR` / `FINANCE_PIPELINE_CRON_MINUTE` for the smoke test); confirm a `finance_pipeline_run_completed` row appears in the `audit_events` table for the business day. Captured in the PR description as a smoke-test transcript.
27. Reconstruction test (`test_reconstruct_past_run_from_four_tables_alone`) explicitly asserts that ONLY the four tables (`finance_pipeline_runs`, `finance_pipeline_steps`, `finance_pipeline_risk_flags`, `audit_events`) are queried during reconstruction. The test fails if any other table is touched.
28. `ruff check backend/` and `ruff format --check backend/` both pass.
29. `grep -n "uq_finance_pipeline_risk_flags_run_subject_type" backend/alembic/versions/*.py` returns ≥ 1 match (the dedup UNIQUE constraint on `(run_id, subject_entity_id, flag_type)` is present in the §5.3 alembic block). The DB-level defense against duplicate-flag emission is shipped, not just the application-level anti-join in §4.7.

## §11 Workflow

1. **Prerequisite confirmation.** The executor verifies HB-2 implementation has landed (or chooses to wait per §3 step 2). If HB-2 has not landed, the executor surfaces the dependency to the orchestrator and stops.

2. **Branch creation.** From current main: `git switch -c feat/hb-3-finance-pipeline-hardening`.

3. **Implementation order.** §3 (pre-step verification) → §5 (alembic revision, then `alembic upgrade head` against local SQLite) → §4.1 (models + enums) → §4.2 (schemas) → §4.3 (holiday guard + idempotency) → §4.4/4.5/4.6 (silent-exception removal) → §4.7 (helpers + risk_flags step body) → §4.8 (audit-event emission) → §4.9 (task module) → §4.10 (scheduler registration) → §4.11 (route update) → §6 (schema.d.ts regen + minimum surface) → §7 (tests) → §9 (runbook).

4. **Local validation.** Before push: `python -m pytest -x -q` from `backend/`, `npm run check && npm run test` from `frontend-svelte/`, `ruff check . && ruff format --check .` from `backend/`.

5. **Push.** The pre-push dispatch-review hook (`.githooks/pre-push`) runs against any `docs/**/*-dispatch.md` files in the push range. A code-only push (no edits to this dispatch file) skips the hook in ~100 ms. The hook MUST NOT be bypassed via `--no-verify` unless the orchestrator explicitly authorizes it.

6. **PR opening.** Title: `feat(finance-pipeline): HB-3 daily-run hardening + risk_flags step + scheduler integration`. Body links back to:
   - This dispatch file (`docs/audits/2026-05-20-pilot-hb-3-finance-pipeline-dispatch.md`)
   - The HB-3 amendment subsection (`docs/governance.md` lines ~1130 onwards)
   - The pilot brief HB-3 spec (`docs/2026-05-tech-lead-executive-analysis.md:77-93`)
   - HB-1 implementation precedent (PR #95) and HB-2 implementation precedent (PR-HB-2-1 number once known)

7. **Review.** AugmentCode + Greptile review. Greptile `+1` reaction (queried via `gh api repos/<owner>/<repo>/issues/<N>/reactions`) is the silent-acceptance signal per `feedback_greptile_silent_re_review`. Absorption iters follow the standard pattern — each iter pushes additional commits to the same branch; no force-push on merged commits.

8. **Merge.** When Andrei provides plain-text merge authorization AND CI is green AND Greptile +1 is recorded, merge via the standard squash workflow.

9. **Post-merge smoke test.** Within 24 hours, the executor (or orchestrator) verifies one production scheduler firing emitted a `finance_pipeline_run_completed` audit event for that day; captures the verification in the PR's post-merge comment.

10. **HB-3 closure marker.** After the smoke test passes, the orchestrator updates the auto-memory with `project_hb_3_implementation_landed.md` and closes the HB-3 line in the pilot brief §7 sign-off table.

---

**End of dispatch.** Three of the four pilot Hard Blockers will be landed after this PR merges; HB-4 (Audit Daily Report) remains.
