# HB-2 — Workflow Approval Gate Implementation Dispatch

Cycle: Pilot Hard Blockers (June 2026 launch)
Wave: HB-2
Constitutional anchor: `docs/governance.md` "Workflow Approval gate (binding, Pilot Hard Blocker 2)" subsection inside AUTHORIZATION MATRIX (landed via PR #96, merge commit `7c0588a8d`, amendment lines 554-1128)
Pilot brief anchor: `docs/2026-05-tech-lead-executive-analysis.md` §2 HB-2 (landed via PR #89, scope-bound via PR #92)
Prior precedent: HB-1 implementation dispatch (`docs/audits/2026-05-18-pilot-hb-1-kyc-gate-dispatch.md`, PR #94 → executor PR #95)
Findings closed by this wave: HB-2 (sole)
Status: READY

---

## §1 Scope

This dispatch prescribes the implementation contract for the follow-on executor PR that will close Pilot Hard Blocker 2 (Workflow Approval gate, constitutionally bound via PR #96 merge commit `7c0588a8d`). The executor PR will land: one new alembic revision `046` creating `workflow_approval_requests` + `approval_policy` tables with all binding columns/indexes/constraints per the amendment Schema clause (§5); one new service module `backend/app/services/workflow_approval_service.py` holding the lifecycle primitives (`evaluate_and_maybe_create`, `grant_request`, `reject_request`, `supersede_request`, `consume_request`, `sweep_expired`) plus the `mutation_payload_hash` invariant enforcement via `normalize_payload_raw`; gate insertions at the THREE gated route handlers (`POST /deals` in `backend/app/api/routes/deals.py:94`, `POST /rfqs/{rfq_id}/actions/award` in `backend/app/api/routes/rfqs.py:474`, `POST /cashflow/contracts/{contract_id}/settle` in `backend/app/api/routes/cashflow_ledger.py:28`) that route threshold-crossing requests through the approval cycle and return HTTP 202 + `WorkflowApprovalRequest` per the Pending-mutation behavior clause; one new approval router under `/workflow-approvals` exposing the grant/reject/supersede/consume/polling endpoints with `require_role` decorators per the approval_policy seed; SIX HMAC-signed audit event types emitted across three layers (event 1 `workflow_approval_requested` from the service module inside the gated route's `unit_of_work`; events 2/3/5/6 from the approval-router route-level `audit_event` Depends; event 4 `workflow_approval_expired` from the sweeper task — see §8 for the binding emission-source-by-event table); one expiry sweeper background task registered on the existing Railway scheduler service per the amendment's Phase 2 deferral clause (sweeper IS required for HB-2 closure); SSE broadcast wiring on each state transition; the defense-in-depth "lacks risk_manager" HTTP 403 assertion at the gate; THREE new Settings fields (`WORKFLOW_APPROVAL_DEAL_THRESHOLD_USD`, `WORKFLOW_APPROVAL_SETTLE_THRESHOLD_USD`, `WORKFLOW_APPROVAL_SWEEPER_INTERVAL_MINUTES`) with binding pilot defaults; and a minimum-viable frontend consumer (typed-client regeneration + risk_manager/auditor pending-approval panel) per `feedback_dispatch_transport_partner_clause` to keep the contract end-to-end testable in the same PR.

This dispatch itself is documentation-only — no code change lands via the PR shipping this file. The executor PR is the next task in the orchestrator's HB-2 sequence and starts after this dispatch PR merges.

## §2 Boundary

This PR does NOT:

- Introduce any new institutional role. The amendment's Role additions clause is binding: "None. The HB-2 Workflow Approval gate introduces no new institutional roles" (`docs/governance.md` lines 672-684, post-Option-B refactor). `compliance_officer` is a retired draft concept; the executor MUST NOT add it back. The auditor-as-settle-requester edge case is unreachable by construction per the AUTHORIZATION MATRIX (auditor has no write scope).
- Implement the daily cumulative per-counterparty exposure gate. The amendment's Phase 2 deferral clause registers this as a future-amendment item; the operational compensating control during pilot is risk_manager's daily review per brief §5 stop-conditions. This dispatch is fail-closed on aggregate-volume gating within HB-2 scope.
- Implement a runtime mutation route for `approval_policy`. The amendment binds: "There is NO admin route to mutate `approval_policy` at runtime — this is intentional." Policy changes require a new alembic data migration + governance amendment, both out of HB-2 scope. The executor MUST NOT ship a PATCH/PUT route for `approval_policy`.
- Modify the existing RBAC matrix for any role. HB-2 binds approval-gate routes on top of the existing matrix; it does NOT carve trader exceptions, expand auditor write scope, or alter `{trader, risk_manager}` combinability. The defense-in-depth "lacks risk_manager" assertion at the approval gate (§4.7) is REDUNDANT with the RBAC layer, not a replacement.
- Introduce a new canonicalization helper. The amendment's `mutation_payload_hash` invariant binds: "Canonicalization MUST reuse the existing canonical-form helper that drives audit-trail signing (`normalize_payload_raw` per `audit_trail_service`) — no new canonicalization is introduced by this amendment." The executor MUST call `normalize_payload_raw` (at `backend/app/services/audit_trail_service.py:216`) and SHA-256-hash its first-return-value string. Do NOT invent `json.dumps(..., sort_keys=True)`, `dumps_canonical`, or any other helper.
- Modify or replace the existing audit-trail emission pattern. All six event types route through `AuditTrailService.record(...)` at `backend/app/services/audit_trail_service.py:76-119`. The HMAC signing path is unchanged; this PR adds new event-type constants but does NOT extend the recorder.
- Persist a `compliance_officer` member in any role enum, JWT claim handler, or seed. The post-Option-B refactor removed every reference to that role from `docs/governance.md` (verified by `grep -i compliance_officer docs/governance.md` returning only the historical "None" rationale line); the executor's PR MUST contain ZERO new `compliance_officer` references.
- Backfill `notional_usd` onto the `deals` table. Per the amendment, notional_usd is COMPUTED at gate-evaluation time from persisted-entity primitives — for deal_create from the HedgeContract rows referenced by `body.links` (server-side, see §4.3.1); for deal_award from the awarded `(quote, quantity_mt)` pairs (server-side, see §4.3.2) — and persisted onto the `WorkflowApprovalRequest` row as `threshold_at_request` (Decimal). The `deals` table schema is UNCHANGED by HB-2 (alembic 044 already dropped the lifecycle fields per PR #78 / Cluster 1; that closure persists through this amendment).
- Allow synchronous gated mutations to proceed when above threshold. The amendment is explicit: above-threshold mutations return HTTP 202 + `WorkflowApprovalRequest` (NOT 200/201 + mutation result). The route MUST NOT both create the mutation AND return 202; the mutation is deferred until the consume path fires. The executor's PR MUST verify by integration test that the three gated mutations do NOT commit any side effects (no `Deal` row, no `HedgeContractSettlement` row) on the 202 path.
- Extend the gate to OTHER write surfaces. The amendment binds exactly three gated mutations (deal_create, deal_award, hedge_contract_settle). RFQ create/refresh/award (below threshold), Order CRUD, Counterparty CRUD, Linkage CRUD, MTM/P&L writes, Scenario writes, audit-log routes — none of these are in HB-2 scope. The executor MUST NOT add an approval gate to any route not in the binding three.

## §3 Pre-step (manual)

Empty for the code PR itself. The executor's branch opens against current main HEAD (`7c0588a8d` post-amendment-merge) and runs without infrastructure changes.

Two operational pre-conditions exist BUT they belong to pilot launch operations, NOT to the executor PR:

1. **Threshold ratification (pre-pilot, NOT in PR scope)**: the amendment binds the defaults (USD 500,000 deal, USD 250,000 settle) as pilot placeholders pending risk_committee ratification. The risk_committee sign-off captures the actual production values into the brief §7 sign-off record; if production values differ from the defaults, the `WORKFLOW_APPROVAL_DEAL_THRESHOLD_USD` / `WORKFLOW_APPROVAL_SETTLE_THRESHOLD_USD` env vars are set on the Railway `backend` service AFTER this PR merges and BEFORE pilot day 1. The PR ships the defaults; the operational override is a Railway dashboard action, not a code change.

2. **Second-auditor provisioning (pre-pilot, NOT in PR scope)**: the amendment's approval_policy seed binds `hedge_contract_settle → required_approver_roles=["auditor"]` with the global `requested_by != approved_by` DB constraint. For threshold-crossing settles to complete, the system must have at least one `auditor` Clerk identity that is distinct from the `risk_manager` actor submitting the settle request (per RBAC, requester is always `risk_manager` here; the constraint is trivially satisfied across roles since requester and approver have different role definitions, but the Clerk tenant still needs at least one `auditor` identity provisioned to consume the approval). The amendment's post-Option-B refactor notes this as "a known pre-condition shared with any other auditor-signed institutional action, not an HB-2 design defect." Confirm with Andrei pre-pilot that the production Clerk tenant has ≥ 1 `auditor` identity; the executor PR does NOT gate on this.

3. **Two-risk-manager provisioning (pre-pilot, NOT in PR scope) — Greptile iter 5 P1 catch**: the approval_policy seed binds `deal_create → required_approver_roles=["risk_manager"]` and `deal_award → required_approver_roles=["risk_manager"]`. The requester for both is also `risk_manager` (per RBAC, no other role has deal-write or RFQ-award scope). The global `requested_by != approved_by` DB constraint therefore requires TWO distinct `risk_manager` Clerk identities for any threshold-crossing deal_create or deal_award to complete the approval cycle. With only one `risk_manager` provisioned, every above-threshold deal mutation would land in `pending` and stay there until either (a) the expiry sweeper transitions it to `expired` or (b) the requester supersedes it — never reaching `approved`. Confirm with Andrei pre-pilot that the production Clerk tenant has ≥ 2 `risk_manager` identities; the executor PR does NOT gate on this. This pre-condition is structural to the approval-policy seed: a future amendment could weaken `requested_by != approved_by` for deal mutations (e.g. by introducing a separate "deal_approver" role that risk_managers also carry) — but that change is out of HB-2 scope and would itself be a constitutional amendment, not a pilot-config tweak.

## §4 Backend changes

### §4.1 New module: `backend/app/services/workflow_approval_service.py`

Create a new service module centralizing the workflow-approval lifecycle. Every gate site (§4.3) calls a single `evaluate_and_maybe_create` entry; every approval-router endpoint (§4.4) calls one of `grant_request`, `reject_request`, `supersede_request`, `consume_request`; the sweeper task (§4.5) calls `sweep_expired`. Centralizing the helpers means every state transition emits a uniform audit shape and applies the `mutation_payload_hash` invariant identically — no per-site drift.

**Module structure (binding):**

```python
# backend/app/services/workflow_approval_service.py
"""WorkflowApprovalRequest lifecycle service.

Constitutional anchor: docs/governance.md "Workflow Approval gate
(binding, Pilot Hard Blocker 2)" subsection of AUTHORIZATION MATRIX.

Every state transition emits an HMAC-signed audit event via
AuditTrailService.record(...). The mutation_payload_hash invariant
reuses normalize_payload_raw from audit_trail_service — no new
canonicalization is introduced.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.workflow_approval import (
    ApprovalPolicy,
    ApprovalStatus,
    MutationType,
    RejectionReasonCode,
    ThresholdDimension,
    WorkflowApprovalRequest,
)
from app.services.audit_trail_service import AuditTrailService, normalize_payload_raw

MutationTypeLiteral = Literal["deal_create", "deal_award", "hedge_contract_settle"]

_EXPIRY_BY_MUTATION_TYPE = {
    MutationType.deal_create: timedelta(hours=48),
    MutationType.deal_award: timedelta(hours=24),
    MutationType.hedge_contract_settle: timedelta(hours=2),
}

_THRESHOLD_BY_MUTATION_TYPE = {
    MutationType.deal_create: lambda: settings.workflow_approval_deal_threshold_usd,
    MutationType.deal_award: lambda: settings.workflow_approval_deal_threshold_usd,
    MutationType.hedge_contract_settle: lambda: settings.workflow_approval_settle_threshold_usd,
}

_THRESHOLD_DIMENSION_BY_MUTATION_TYPE = {
    MutationType.deal_create: ThresholdDimension.notional_usd,
    MutationType.deal_award: ThresholdDimension.notional_usd,
    MutationType.hedge_contract_settle: ThresholdDimension.settlement_amount_usd,
}
```

**Lifecycle entry points (binding):** the service exposes EXACTLY these public functions; no others. The route handlers (§4.3 + §4.4) MUST consume only this public surface. Internal helpers (e.g. `_emit_audit_event`, `_compute_payload_hash`) may be added but MUST be prefixed with `_` and never called from outside the module.

| Function | Caller | Responsibility |
|---|---|---|
| `evaluate_and_maybe_create(session, mutation_type, payload_obj, threshold_value, requesting_actor_sub, requesting_actor_ip, requesting_actor_session_id, correlation_id, idempotency_key, request_role_set)` | §4.3.1 / §4.3.2 / §4.3.3 gate sites | Compares `threshold_value` to the configured threshold. If below threshold returns `None` (caller proceeds with synchronous mutation). If above threshold: enforces the defense-in-depth `lacks_risk_manager` assertion (§4.7) raising 403 if violated; resolves the `approval_policy` seed for the mutation_type; checks for an existing row matching the `idempotency_key` (if non-null) and returns it if found; otherwise creates a new `WorkflowApprovalRequest` row in `pending` state with `mutation_payload_hash`, `threshold_at_request`, `threshold_config_value`, `expires_at` populated per the amendment Pending-mutation behavior clause; emits `workflow_approval_requested` audit event; broadcasts SSE; returns the row. The gate site converts the returned row into the HTTP 202 + body shape. |
| `grant_request(session, approval_id, approver_actor_sub, approver_role_set, approver_ip, approver_session_id)` | §4.4.2 POST /workflow-approvals/{id}/grant | Loads the row WITH `SELECT FOR UPDATE` (same concurrency guard as `consume_request` below — two parallel grants on the same row would otherwise both pass the status check and produce mismatched `approved_by` attribution + duplicate `workflow_approval_granted` audit events on a compliance-bound trail); asserts current status is `pending`; asserts `approver_actor_sub != requested_by` (DB constraint also enforces; this is the application-layer pre-check for a 422 with a useful detail); asserts the approver's role intersects `approval_policy.required_approver_roles`; transitions to `approved`, populates `approved_by`, `approver_ip`, `approver_session_id`; emits `workflow_approval_granted`; broadcasts SSE; returns the row. |
| `reject_request(session, approval_id, approver_actor_sub, approver_role_set, approver_ip, approver_session_id, reason_code, reason_text)` | §4.4.3 POST /workflow-approvals/{id}/reject | Same shape as grant including `SELECT FOR UPDATE` on the row load (same concurrency rationale: two parallel rejects on the same row would otherwise both pass the status check, with the second overwriting the first's `rejection_reason_*` columns); transitions to `rejected`, persists `rejection_reason_code` + `rejection_reason_text` (CHECK constraint enforces both NULL or both set with text length ≥ 8); emits `workflow_approval_rejected`. |
| `supersede_request(session, approval_id, requesting_actor_sub)` | §4.4.4 POST /workflow-approvals/{id}/supersede | Loads the row WITH `SELECT FOR UPDATE` (same concurrency guard); asserts current status is `pending` OR `approved`; asserts `requesting_actor_sub == row.requested_by` (the amendment binds actor-level scope at lines 742-750: "Only the original requester ... can mark `superseded`"); transitions to `superseded` with `previous_status` captured for the audit event; emits `workflow_approval_superseded`; broadcasts SSE. Returns the row. Reissue is a SEPARATE call (the caller submits the original mutation again, which goes through `evaluate_and_maybe_create` and creates a new row). |
| `consume_request(session, approval_id, requesting_actor_sub, consume_payload_obj, executor)` | §4.4.5 POST /workflow-approvals/{id}/consume | Loads the row WITH `SELECT FOR UPDATE` (postgres) / equivalent row-locking semantics (sqlite tests rely on the transaction-level lock; postgres production relies on the explicit `with_for_update()` per the concurrency guard below); asserts `requesting_actor_sub == row.requested_by` (actor-level authorization; raises HTTPException(403) "consume restricted to the original requester" on mismatch — same actor-level scope as `supersede_request` per amendment lines 742-750, which the §4.4 #6 endpoint table extends to consume); asserts current status is `approved`; recomputes `_compute_payload_hash(consume_payload_obj)` and compares against `row.mutation_payload_hash` — if mismatch, raises HTTP 422 with `detail={"code": "payload_drift_detected", ...}` and the row stays `approved` (per amendment lines 794-807); on match, calls `executor(consume_payload_obj)` which is a callable provided by the consume route that wires through to the HEAD-verified write paths — `DealEngineService.create_deal(session, data)` for deal_create, `RFQService.award(session, rfq_id, actor_sub)` for deal_award, `ingest_hedge_contract_settlement(session, contract_id, payload, commit=False)` (module-level function in `app.services.cashflow_ledger_service`) for hedge_contract_settle; on executor success, transitions the row to `consumed` (the row was loaded `FOR UPDATE` so this atomic transition is guarded against concurrent double-consume — a second consume attempt sees the row already in `consumed` and 409s), populates `consumed_at`, emits `workflow_approval_consumed`; broadcasts SSE; returns `(row, executor_result)`. On executor failure (uncaught exception during the wrapped mutation), the outer `unit_of_work` rolls back; the row stays `approved` and the failure is surfaced to the caller. |
| `sweep_expired(session)` | §4.5 scheduler task | Selects rows where `status IN (pending, approved) AND expires_at < now()` using the composite index `(status, expires_at)`; for each, captures `previous_status` and transitions to `expired`; emits one `workflow_approval_expired` audit event per row; broadcasts SSE for each. Returns the count. Pure background job — no HTTPException, just structured logging on errors per the existing `app/tasks/` patterns. |

**Concurrency guard on all transitioning lifecycle helpers (binding):** every row load inside `grant_request`, `reject_request`, `supersede_request`, AND `consume_request` MUST use `session.execute(select(WorkflowApprovalRequest).where(WorkflowApprovalRequest.id == approval_id).with_for_update())` on postgres. Under SQLAlchemy 2.x, `with_for_update()` emits `SELECT ... FOR UPDATE` on postgres, locking the row for the duration of the transaction; concurrent transition attempts on the same row will block on the lock and, when they acquire it, will observe the post-first-commit status and either proceed (if still in a valid source state) or 409 (if a peer already transitioned it). On SQLite (test env), `with_for_update()` is a no-op — but the SQLite test driver serializes write transactions globally, so the same double-transition race is structurally impossible in tests. The §7.2 tests `test_consume_concurrent_double_consume`, `test_grant_concurrent_double_grant`, and `test_reject_concurrent_double_reject` verify the postgres lock behavior by spawning two threads against a shared connection pool. The guard makes each lifecycle transition atomic with respect to the status check, closing the entire double-transition window the application-layer check alone would leave open.

**`mutation_payload_hash` computation (binding):** the helper MUST use `normalize_payload_raw` per the amendment's binding clause at lines 808-811:

```python
def _compute_payload_hash(payload_obj: dict | list) -> str:
    """Canonicalize via normalize_payload_raw and SHA-256-hash the canonical form.

    This MUST reuse normalize_payload_raw — the amendment lines 808-811
    bind this helper as the sole canonicalization path; no new
    canonicalization is introduced by HB-2.
    """
    canonical, _ = normalize_payload_raw(payload_obj)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

**`expires_at` computation (binding):** `created_at + _EXPIRY_BY_MUTATION_TYPE[mutation_type]`. The amendment binds the per-type defaults at lines 770-775; the executor MAY make these env-var-configurable (e.g. `WORKFLOW_APPROVAL_DEAL_CREATE_EXPIRY_HOURS`) as an additional Settings field, but the BINDING defaults must remain 48h / 24h / 2h.

**`SessionLocal()` dual-session pattern for audit emission (binding — calibrated against HB-1's `feedback_dispatch_executor_session_pattern`):** the `workflow_approval_requested` audit event MUST be emitted on the SAME session as the row creation (route's request session), inside the route's `unit_of_work` — because the row IS the mutation here; if the route handler raises after the gate fires, both the row and the audit event should roll back atomically. Same applies to grant/reject/supersede/consume — these are state mutations on the row itself, not gates rejecting an outer mutation. ONLY the `sweep_expired` background task is exempt because it has no enclosing request `unit_of_work`; the sweeper opens its own `SessionLocal()` and commits the row + audit atomically per iteration.

This is the structural inverse of HB-1's gate pattern (where the gate REJECTED an outer mutation and used dual-session to survive the outer rollback). HB-2's approval-row CREATION is the desired outcome of the gate firing, so no dual-session escape is needed; the failure mode in HB-2 is "the outer mutation didn't fire and we returned 202 instead", which is the success path of the gate.

**`require_role` / `require_any_role` import directive (binding for `backend/app/services/workflow_approval_service.py`):** the service module itself imports zero FastAPI role helpers (role checks live in the route layer). The `lacks_risk_manager` defense-in-depth assertion (§4.7) raises `HTTPException(status.HTTP_403_FORBIDDEN, ...)`. The imports at the top of the file MUST include `from fastapi import HTTPException, status`. Without this, the module fails at load time with `NameError`.

### §4.2 New module: `backend/app/models/workflow_approval.py`

Create the SQLAlchemy ORM models for the two new tables. The schema mirrors the amendment's Schema clause at lines 1026-1097 exactly; any deviation is a P1 Tipo II self-defeat.

```python
# backend/app/models/workflow_approval.py
"""WorkflowApprovalRequest + ApprovalPolicy ORM models.

Constitutional anchor: docs/governance.md "Workflow Approval gate
(binding, Pilot Hard Blocker 2)" — Schema clause at lines 1026-1097.
"""
from __future__ import annotations

import enum
import uuid as _uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MutationType(enum.Enum):
    deal_create = "deal_create"
    deal_award = "deal_award"
    hedge_contract_settle = "hedge_contract_settle"


class ApprovalStatus(enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    consumed = "consumed"
    superseded = "superseded"


class ThresholdDimension(enum.Enum):
    notional_usd = "notional_usd"
    settlement_amount_usd = "settlement_amount_usd"


class RejectionReasonCode(enum.Enum):
    """EXHAUSTIVE enum per amendment lines 951-958 + 1060-1067.

    payload_drift_detected is intentionally NOT a member — it is an
    HTTP 422 detail string on the consume endpoint, not a rejection
    transition (the approval stays `approved` on payload drift; the
    caller may resubmit, supersede, or wait for the sweeper).
    """
    policy_violation = "policy_violation"
    counterparty_risk = "counterparty_risk"
    payload_concern = "payload_concern"
    threshold_inappropriate = "threshold_inappropriate"
    other = "other"


class WorkflowApprovalRequest(Base):
    __tablename__ = "workflow_approval_requests"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True).with_variant(String(length=36), "sqlite"),
        primary_key=True,
        default=_uuid.uuid4,
    )
    mutation_type: Mapped[MutationType] = mapped_column(
        Enum(MutationType, name="workflow_approval_mutation_type"),
        nullable=False,
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="workflow_approval_status"),
        nullable=False,
        default=ApprovalStatus.pending,
    )
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    threshold_at_request: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False
    )
    threshold_config_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False
    )
    threshold_dimension: Mapped[ThresholdDimension] = mapped_column(
        Enum(ThresholdDimension, name="workflow_approval_threshold_dimension"),
        nullable=False,
    )
    mutation_payload_canonical: Mapped[dict | list] = mapped_column(
        JSONB().with_variant(String, "sqlite"),  # TEXT on sqlite; JSONB on postgres
        nullable=False,
    )
    mutation_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True).with_variant(String(length=36), "sqlite"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approver_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approver_session_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    rejection_reason_code: Mapped[RejectionReasonCode | None] = mapped_column(
        Enum(RejectionReasonCode, name="workflow_approval_rejection_reason_code"),
        nullable=True,
    )
    rejection_reason_text: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )

    __table_args__ = (
        # Composite index for the expiry sweeper — covers both
        # status IN (pending, approved) AND expires_at < now() lookups.
        Index(
            "ix_workflow_approval_requests_status_expires_at",
            "status",
            "expires_at",
        ),
        # Partial UNIQUE on idempotency_key (postgres + sqlite 3.8+).
        # See alembic migration §5 for the variant-aware index DDL —
        # SQLAlchemy `unique=True` on the column would emit a full
        # unique constraint that does not match the partial-index
        # binding; the partial form lives in the migration file.
        # `requested_by != approved_by` CHECK lives in the migration
        # for the same reason (variant constraint).
        # CHECK constraint on rejection fields (both NULL or both NOT
        # NULL with rejection_reason_text length >= 8) — also in the
        # migration as a variant CHECK / sqlite trigger.
    )


class ApprovalPolicy(Base):
    __tablename__ = "approval_policy"

    mutation_type: Mapped[MutationType] = mapped_column(
        Enum(MutationType, name="workflow_approval_mutation_type"),
        primary_key=True,
    )
    required_approver_roles: Mapped[list[str]] = mapped_column(
        JSONB().with_variant(String, "sqlite"),
        nullable=False,
    )
    fallback_when_requester_is: Mapped[dict[str, str]] = mapped_column(
        JSONB().with_variant(String, "sqlite"),
        nullable=False,
        default=dict,
    )
    threshold_dimension: Mapped[ThresholdDimension] = mapped_column(
        Enum(ThresholdDimension, name="workflow_approval_threshold_dimension"),
        nullable=False,
    )
```

**Enum reuse contract (binding):** the four enums (`MutationType`, `ApprovalStatus`, `ThresholdDimension`, `RejectionReasonCode`) are defined ONLY in this module. The schemas (§4.4 Pydantic models) import them from here; the alembic migration (§5) registers the corresponding postgres ENUM types with the same names; the workflow_approval_service (§4.1) imports the enums for type annotations. There MUST be exactly one source of truth per enum.

### §4.3 Gate integration sites

#### §4.3.1 `POST /deals` (`backend/app/api/routes/deals.py:94`)

Current handler at HEAD `7c0588a8d` (verified by dispatch author): `create_deal(body: DealCreate, request: Request, ...)` at lines 94-117. The handler currently calls `DealEngineService.create_deal(session, data)` synchronously (verified at `backend/app/api/routes/deals.py:115`; the service name is `DealEngineService`, NOT `DealEngine`).

**Notional computation contract (binding — server-side, security-critical):** the amendment binds `notional_usd` as the threshold dimension for deal_create, computed at gate-evaluation time from `fixed_price_value * quantity_t` (Decimal precision). The current `DealCreate` schema (`backend/app/schemas/deal.py:38-42`) carries ONLY `name`, `commodity`, and `links` — no direct `notional_usd`, `fixed_price_value`, or `quantity_t` field. The dispatch binds the following resolution: **the gate computes `notional_usd` server-side from the `HedgeContract` rows referenced by `body.links` — NEVER from a client-supplied field**. `DealCreate` is NOT extended with a `notional_usd` field; trusting a frontend-supplied threshold value would create a constitutional bypass (any actor with deal-create scope could submit `notional_usd=0` with real HedgeContract links to evade the $500k gate; Greptile iter 3 P1 security catch).

**Server-side computation (binding):**

1. Iterate `body.links` filtering for entries where `linked_type == DealLinkedType.contract`.
2. For each filtered link, load the `HedgeContract` row from the DB by `linked_id`.
3. Compute `notional_usd = sum(contract.fixed_price_value * contract.quantity_t for each contract)` — Decimal × Decimal, summed in Decimal precision.
4. Pass the resulting `Decimal` as `threshold_value` to `evaluate_and_maybe_create`.

**Edge cases (binding):**

- **No HedgeContract links** (e.g. deal with only Order or RFQ links): `notional_usd = 0` (sum of empty iterable). Below threshold by construction → synchronous path proceeds. This is institutionally correct: a Deal without HedgeContract links has no committed market exposure to gate against; the gate exists to ratify the HedgeContract-bearing portion of the Deal's notional.
- **Missing HedgeContract row** (link references a non-existent or soft-deleted contract): the existing link validator at the Deal create path already rejects this case before the gate fires (executor verifies by inspecting `DealEngine.create_deal` link resolution; if the validator doesn't reject missing/deleted contracts, the executor MUST add that check in this PR to close the gate-evasion vector).
- **Negative or zero contract values**: `HedgeContract` columns are constitutionally non-negative (per the Phase A1 precision contract). The sum is non-negative by construction.

**Schema (binding):** `backend/app/schemas/deal.py` `DealCreate` is UNCHANGED — keeps the original 3 fields (`name`, `commodity`, `links`). The frontend (§6) computes notional from user-selected HedgeContracts using existing read endpoints for informational display (so the user knows whether their submission will trigger the approval gate) BUT the displayed value is not authoritative — only the server-side computation gates the mutation.

**Why server-compute over client-supplied (binding rationale):** the threshold gate is a security boundary; trusting client input on a security boundary violates the institutional principle "the backend is authoritative for economics" (per CLAUDE.md). The earlier Path B (client-supplied `notional_usd` field) was rejected after Greptile iter 3 surfaced the bypass: an authenticated risk_manager with intent to evade two-signatory approval could submit `notional_usd=0` with $1M of HedgeContract links and the gate would not fire. Server-side computation closes this vector unconditionally — the gate evaluates against actual persisted entity state, not against client-asserted scalars.

**Backend gate consumes the server-computed value** — see the §4.3.1 handler shape below.

**Gate insertion (binding shape):**

```python
from fastapi.responses import JSONResponse

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"model": DealRead},
        202: {"model": ApprovalPendingResponseBody},
    },
)
def create_deal(
    body: DealCreate,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    actor_roles: set[str] = Depends(get_current_actor_roles),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _: None = Depends(audit_event(entity_type="deal", event_type="created")),
    __: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    with unit_of_work(session, request=request):
        notional_usd = _compute_deal_notional_from_links(session, body.links)
        approval = workflow_approval_service.evaluate_and_maybe_create(
            session,
            mutation_type=MutationType.deal_create,
            payload_obj=body.model_dump(mode="json"),
            threshold_value=notional_usd,
            requesting_actor_sub=actor_sub,
            requesting_actor_ip=request.client.host if request.client else None,
            requesting_actor_session_id=request.headers.get("X-Session-ID"),
            correlation_id=_uuid.uuid4(),
            idempotency_key=idempotency_key,
            request_role_set=actor_roles,
        )
        if approval is not None:
            mark_audit_success(request, approval.id, metadata={
                "actor_sub": actor_sub,
                "approval_path": "pending",
            })
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=approval_response_body(session, approval),  # §4.4.7 helper
            )
        # Below threshold — synchronous path. The current HEAD handler
        # at backend/app/api/routes/deals.py:108-117 normalises link enum
        # values BEFORE calling DealEngineService.create_deal. The gate's
        # synchronous path MUST preserve that normalization (binding):
        data = body.model_dump()
        if data.get("links"):
            for link in data["links"]:
                if hasattr(link.get("linked_type"), "value"):
                    link["linked_type"] = link["linked_type"].value
        deal = DealEngineService.create_deal(session, data)
        mark_audit_success(request, deal.id, metadata={"actor_sub": actor_sub})
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=DealRead.model_validate(deal).model_dump(mode="json"),
    )
```

The `_compute_deal_notional_from_links` helper lives in `backend/app/api/routes/deals.py` as a module-level function (or in a small `backend/app/services/deal_notional.py` module — executor's choice; importing convenience matters more than placement):

```python
def _compute_deal_notional_from_links(
    session: Session, links: list[DealLinkCreate]
) -> Decimal:
    """Sum HedgeContract notionals across the deal's contract links.

    Returns Decimal(0) if no HedgeContract links exist. Skips links of
    other types (Order, RFQ); those entities are below-threshold
    components of the deal that roll up through HedgeContracts.
    """
    contract_ids = [
        link.linked_id for link in links
        if link.linked_type == DealLinkedType.contract
    ]
    if not contract_ids:
        return Decimal(0)
    contracts = session.execute(
        select(HedgeContract).where(HedgeContract.id.in_(contract_ids))
    ).scalars().all()
    return sum(
        (c.fixed_price_value * c.quantity_t for c in contracts),
        start=Decimal(0),
    )
```

The handler's response model annotation widens to `DealRead | dict` to accommodate the 202 body. The OpenAPI schema regen (§6.1) MUST surface this dual return shape — `frontend-svelte/src/lib/api/schema.d.ts` will type the endpoint as a discriminated union; the typed client must branch on status code.

**Import directive (binding for `backend/app/api/routes/deals.py`):** the current HEAD imports at lines 7-29 cover `APIRouter, Depends, HTTPException, Query, Request, Response, status` from `fastapi`, `get_current_actor_sub, require_any_role, require_role` from `app.core.auth`, plus `audit_event, mark_audit_success, unit_of_work` and the deal schemas. The gate addition introduces THREE new identifiers the file does not currently import: `get_current_actor_roles` (from `app.core.auth`), `Header` (from `fastapi`), and a uuid generator. The executor MUST extend the existing import lines (binding):

```python
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from app.core.auth import get_current_actor_roles, get_current_actor_sub, require_any_role, require_role
import uuid as _uuid  # for correlation_id=_uuid.uuid4() at the gate site
from app.models.workflow_approval import MutationType
from app.services import workflow_approval_service
```

Plus the `approval_response_body` helper import from the new approval router module (§4.4.7). Per `feedback_dispatch_verify_imports`: a silent NameError at module load is a P1 dispatch defect; this directive is enforced by §10 acceptance #29.

**`unit_of_work` scope (binding for all three gate sites in §4.3):** the WHOLE handler body lives inside a single `unit_of_work(session, request=request)` block — both the 202 (approval-row creation) path AND the synchronous-mutation path. The §4.1 binding requires the row creation + `workflow_approval_requested` audit event to commit atomically on the route's request session; placing the `evaluate_and_maybe_create` call OUTSIDE `unit_of_work` would leave the row uncommitted under the existing session DI pattern (`backend/app/api/dependencies/session.py` provides a session with no auto-commit; the `unit_of_work` context is what triggers commit per `backend/app/api/dependencies/uow.py:19-29`). The same wrapping pattern repeats verbatim in §4.3.2 + §4.3.3.

#### §4.3.2 `POST /rfqs/{rfq_id}/actions/award` (`backend/app/api/routes/rfqs.py:474`)

Current handler (verified at HEAD `7c0588a8d`): `award_rfq(rfq_id: UUID, payload: RFQAwardRequest, ...)` at lines 474-493. The award path materializes one or two `HedgeContract` rows (single-trade vs spread) in the same transaction via `RFQService.award`. There is NO synchronous Deal creation in the current `RFQService.award` flow — the route's existing `entity_type="rfq", event_type="awarded"` audit event represents the RFQ state transition, not a Deal mutation. The HB-2 gate frames `deal_award` because the awarded RFQ is the institutional point at which a deal becomes a binding obligation; the gate label is `MutationType.deal_award` per the amendment.

**Notional computation (binding, verified field names):** the awarded `RFQQuote` exposes `fixed_price_value: Decimal` (column-mapped as `price_value`; verified at `backend/app/models/quotes.py:41-45`). The `RFQQuote` model does NOT carry a `quantity` field — quantity lives on the parent `RFQ` row as `quantity_mt: Decimal` (verified at `backend/app/models/rfqs.py:46-48`). For spread RFQs, each leg's quantity lives on the corresponding child `RFQ.quantity_mt`. The gate runs AFTER the awarded quotes are loaded but BEFORE any state mutation on `RFQ` or `HedgeContract`. The notional dimension is computed in Decimal precision per the platform contract.

**Awarded-quote reference (binding for the 202 path):** when above threshold, the `WorkflowApprovalRequest` row's `mutation_payload_canonical` MUST include the awarded `RFQQuote.id` so the consume path (§4.4.5) can reconstruct the award call deterministically. The payload obj is `{"rfq_id": str(rfq_id), "awarded_quote_id": str(quote.id)}` — a small, deterministic shape that the consume endpoint can verify the hash of and then thread through `RFQService.award`. The Deal is NOT created on the 202 path; it materializes only when the consume endpoint fires `RFQService.award`.

**Awarded-quote selection (binding, REFACTOR path):** dispatch author verified at HEAD `7c0588a8d`: `RFQService.award` at `backend/app/services/rfq_service.py:1393` takes `(session, rfq_id, actor_sub)` and computes the awarded quotes internally via an inline ranking step that produces `top.buy_quote` + `top.sell_quote` (verified at lines 1426-1443: `top.buy_quote.id`, `top.sell_quote.id`). `RFQAwardRequest` (`backend/app/schemas/rfq.py:233`) is an empty marker class — it does NOT carry a `quote_id` payload. The selection is purely inline.

The dispatch binds the executor PR to take the REFACTOR path (consistent with the dispatch-vs-executor-PR scope convention from §1: this markdown is documentation-only; every §4 prescription is work the executor PR performs). Concretely the executor extracts the existing ranking + top-quote selection block from `RFQService.award` into a new read-only helper named `RFQService.resolve_awarded_quote(session: Session, rfq_id: UUID) -> tuple[RFQQuote, RFQQuote]` returning the `(buy_quote, sell_quote)` pair. The helper does NOT mutate state, does NOT change RFQ.state, does NOT create contracts — it only reads the ranking and returns the winners. `RFQService.award` then calls `buy_quote, sell_quote = self.resolve_awarded_quote(session, rfq_id)` as its first executable line after the existing `get_live_for_update` + state assertions. The refactor is purely mechanical (extract method) — every test that exercises `RFQService.award` continues to pass unchanged. The §10 acceptance criteria include a grep-based assertion that `resolve_awarded_quote` exists at the merged HEAD of the executor PR.

**Notional computation for two-quote awards (binding, spread case):** for `rfq.intent == RFQIntent.spread`, the awarded pair is `(top.buy_quote, top.sell_quote)` against the two child trade RFQs `(rfq.buy_trade_id, rfq.sell_trade_id)` (verified at `rfq_service.py:1441-1444`). Each child's quantity is read from `trade_rfq.quantity_mt` (verified at `rfq_service.py:1491`). The threshold dimension `notional_usd` is `max(buy_quote.fixed_price_value * buy_trade_rfq.quantity_mt, sell_quote.fixed_price_value * sell_trade_rfq.quantity_mt)` — the larger of the two legs. For non-spread (`RFQIntent.commercial_hedge` / `RFQIntent.standalone`), only one quote+RFQ pair exists, the notional is `top_quote.fixed_price_value * rfq.quantity_mt`, and the `sell_*` fields in the payload are absent. The gate fires if the resulting notional crosses the threshold. The `mutation_payload_canonical` for the 202 path stores `{"rfq_id", "intent", "buy_quote_id", "sell_quote_id"?}` (last key only present for spread) so the consume endpoint reconstructs the same selection deterministically.

**Gate insertion shape:**

```python
@router.post(
    "/{rfq_id}/actions/award",
    responses={
        200: {"model": RFQRead},
        202: {"model": ApprovalPendingResponseBody},
    },
)
@limiter.limit(RATE_LIMIT_MUTATION)
def award_rfq(
    rfq_id: UUID,
    payload: RFQAwardRequest,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    actor_roles: set[str] = Depends(get_current_actor_roles),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _: None = Depends(audit_event(entity_type="rfq", event_type="awarded")),
    __: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    with unit_of_work(session, request=request):
        # resolve_awarded_quote returns the institutional notional shape:
        # (intent, [(quote, quantity_mt), ...]) — a list of (quote, qty)
        # pairs covering single-trade (1-tuple) and spread (2-tuple).
        intent, legs = RFQService.resolve_awarded_quote(session, rfq_id)
        notional_usd = max(
            quote.fixed_price_value * quantity_mt for quote, quantity_mt in legs
        )
        payload_obj: dict = {"rfq_id": str(rfq_id), "intent": intent.value}
        if len(legs) == 2:
            payload_obj["buy_quote_id"] = str(legs[0][0].id)
            payload_obj["sell_quote_id"] = str(legs[1][0].id)
        else:
            payload_obj["awarded_quote_id"] = str(legs[0][0].id)
        approval = workflow_approval_service.evaluate_and_maybe_create(
            session,
            mutation_type=MutationType.deal_award,
            payload_obj=payload_obj,
            threshold_value=notional_usd,
            requesting_actor_sub=actor_sub,
            requesting_actor_ip=request.client.host if request.client else None,
            requesting_actor_session_id=request.headers.get("X-Session-ID"),
            correlation_id=_uuid.uuid4(),
            idempotency_key=idempotency_key,
            request_role_set=actor_roles,
        )
        if approval is not None:
            mark_audit_success(request, approval.id, metadata={
                "actor_sub": actor_sub,
                "approval_path": "pending",
            })
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=approval_response_body(session, approval),
            )
        # Below threshold — synchronous award. Note: RFQService.award at
        # rfq_service.py:1393 takes (session, rfq_id, actor_sub) and
        # mutates rfq state internally. The current HEAD route returns
        # _build_rfq_read(session, rfq_id) (rfqs.py:493), so the gate
        # variant MUST preserve that response shape (binding):
        RFQService.award(session, rfq_id, actor_sub)
        mark_audit_success(request, rfq_id, metadata={"actor_sub": actor_sub})
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=_build_rfq_read(session, rfq_id).model_dump(mode="json"),
    )
```

**Awarded-quote selection helper signature (binding):** `RFQService.resolve_awarded_quote(session: Session, rfq_id: UUID) -> tuple[RFQIntent, list[tuple[RFQQuote, Decimal]]]`. The first element is the RFQ intent (so the gate site can branch payload-shape on spread vs single without re-reading the RFQ row); the second is the ordered list of `(quote, quantity_mt)` pairs the awarded contracts will use. For spread, the order is `[(buy_quote, buy_trade_rfq.quantity_mt), (sell_quote, sell_trade_rfq.quantity_mt)]` mirroring the existing iteration order at `rfq_service.py:1441-1444`. For non-spread, the list contains exactly one element `[(top_quote, rfq.quantity_mt)]`. `RFQService.award` then calls `intent, legs = self.resolve_awarded_quote(...)` as its first executable line after the existing `get_live_for_update` + state assertions; every existing test that exercises `RFQService.award` continues to pass unchanged because the refactor is a pure extract-method (the ranking logic moves, the contract-creation loop reads from `legs` instead of re-computing).

**Import directive (binding for `backend/app/api/routes/rfqs.py`):** the current HEAD imports cover `Depends, Request, status, get_current_actor_sub, require_role, audit_event, mark_audit_success, unit_of_work, RFQService, RFQAwardRequest, _build_rfq_read`. The gate addition introduces the same new identifiers as deals.py: `get_current_actor_roles`, `Header`, `Response`, `import uuid as _uuid`, `from app.models.workflow_approval import MutationType`, `from app.services import workflow_approval_service`, plus `approval_response_body` from the approval router module. The executor MUST extend the existing import lines accordingly. Per `feedback_dispatch_verify_imports`: enforced by §10 acceptance #29.

**Payload shape contract (binding for §4.3.1 / §4.3.2 / §4.3.3):** each gate site passes a `payload_obj` (dict) into `evaluate_and_maybe_create` that:
- contains EVERY field the consume endpoint needs to reconstruct the mutation deterministically (NOT a denormalized snapshot of unrelated request state),
- is stable under JSON canonicalization (UUIDs serialized as `str`, Decimals serialized via Pydantic's `mode="json"`, no embedded Python objects),
- excludes ephemeral fields that change between request and consume time (e.g. timestamps, idempotency keys — those live on the row's own columns, not in `mutation_payload_canonical`).

The three resulting shapes — `body.model_dump(mode="json")` for deal_create, `{rfq_id, intent, awarded_quote_id}` (single-trade) or `{rfq_id, intent, buy_quote_id, sell_quote_id}` (spread) for deal_award, `{contract_id, ...payload.model_dump(mode="json")}` for hedge_contract_settle — share the property that `_compute_payload_hash` on the same logical mutation always produces the same hash (the canonical form is order-stable per `normalize_payload_raw`). The consume endpoint (§4.4 #6) submits the same shape, so hash recomputation matches by construction unless the caller actually changed a field.

**Threshold-computation contract (binding — all server-side):** all three gate sites compute `threshold_value` server-side from persisted-entity primitives — NEVER from client-supplied scalars. The derivation path differs by route per the existing request schema, but the trust boundary is uniform: client cannot supply the threshold value. The three derivations:
- **§4.3.1 deal_create**: the `DealCreate` body has only `name`, `commodity`, and polymorphic `links`. The gate computes `notional_usd` server-side by loading the `HedgeContract` rows referenced by `body.links` (filtering for `linked_type == DealLinkedType.contract`) and summing `fixed_price_value * quantity_t`. The threshold value is NEVER read from a client-supplied field per the Greptile iter 3 security catch — trusting a client scalar on a security-boundary gate would let any deal-create-authorized actor evade the gate by lying about notional.
- **§4.3.2 deal_award**: the route loads the awarded `(intent, [(quote, quantity_mt), ...])` shape via the `resolve_awarded_quote` helper (now a binding refactor); each quote carries `fixed_price_value: Decimal` (verified at `models/quotes.py:41-45`) and each pair's quantity comes from the parent or child `RFQ.quantity_mt: Decimal` (`models/rfqs.py:46`). The gate computes `notional_usd = max(quote.fixed_price_value * quantity_mt for quote, quantity_mt in legs)` server-side from these primitives, never from a frontend-supplied value. The frontend never sees the per-leg notional until it polls the resulting 202 response.
- **§4.3.3 hedge_contract_settle**: the `HedgeContractSettlementCreate` body has `legs: list[HedgeContractSettlementLeg]` with `leg.amount: Decimal`; `settlement_amount_usd = max(leg.amount)` is a direct server-side compute from the payload.

The shared invariant across all three: `threshold_value` is a `Decimal` computed at the gate site BEFORE `evaluate_and_maybe_create` is called, and gets persisted onto `WorkflowApprovalRequest.threshold_at_request` exactly as observed. The asymmetry is in HOW each route computes its `threshold_value` — driven by what each route's existing request schema makes derivable — not in what the gate does with it.

#### §4.3.3 `POST /cashflow/contracts/{contract_id}/settle` (`backend/app/api/routes/cashflow_ledger.py:28`)

Current handler (verified at HEAD `7c0588a8d`): `settle_hedge_contract(contract_id: UUID, payload: HedgeContractSettlementCreate, ...)` at lines 28-58 of `cashflow_ledger.py`. The settlement creates a 2-leg cashflow (FIXED + FLOAT, IN/OUT directions) per `backend/app/schemas/cashflow.py:91-106` (which enforces `len(legs) == 2`, leg ids `{FIXED, FLOAT}`, and `currency == "USD"`). The write path calls `ingest_hedge_contract_settlement(session, contract_id, payload, commit=False)` (a module-level function imported from `app.services.cashflow_ledger_service` — verified at `cashflow_ledger.py:17-22, 49-51`). The function returns `(event, ledger_entries)`; the route then composes `HedgeContractSettlementResponse(event=event, ledger_entries=[CashFlowLedgerEntryRead.model_validate(e) for e in ledger_entries])`. There is NO `HedgeContractSettlementService` class.

**Settle route current audit decorator (verified at `cashflow_ledger.py:38-43`):** `audit_event(entity_type="hedge_contract_settlement", event_type="settled")`. The HB-2 gate MUST preserve this exact `entity_type` string — changing it would break audit-event correlation against historical rows already emitted under that name. Per `feedback_dispatch_verify_imports`: silently renaming entity_type is a P1 dispatch defect.

**Settlement-amount computation (binding):** the gate computes `settlement_amount_usd = max(leg.amount for leg in payload.legs)` — the larger of the FIXED and FLOAT leg amounts, representing the institutional notional exposure of the settlement. The validator at `cashflow.py:84-88` already enforces `leg.amount > 0` for each leg, so the max is well-defined. The `max(leg.amount)` binding is the conservative measure (above threshold for the worst case). The dispatch deliberately does NOT introduce a new `total_settlement_usd` helper — the institutional convention `max(leg.amount)` is the binding here.

**Gate insertion shape:**

```python
@router.post(
    "/contracts/{contract_id}/settle",
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"model": HedgeContractSettlementResponse},
        202: {"model": ApprovalPendingResponseBody},
    },
)
@limiter.limit(RATE_LIMIT_MUTATION)
def settle_hedge_contract(
    contract_id: UUID,
    payload: HedgeContractSettlementCreate,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    actor_roles: set[str] = Depends(get_current_actor_roles),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _: None = Depends(
        audit_event(entity_type="hedge_contract_settlement", event_type="settled")
    ),
    __: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    with unit_of_work(session, request=request):
        settlement_amount_usd = max(leg.amount for leg in payload.legs)
        approval = workflow_approval_service.evaluate_and_maybe_create(
            session,
            mutation_type=MutationType.hedge_contract_settle,
            payload_obj={
                "contract_id": str(contract_id),
                **payload.model_dump(mode="json"),
            },
            threshold_value=settlement_amount_usd,
            requesting_actor_sub=actor_sub,
            requesting_actor_ip=request.client.host if request.client else None,
            requesting_actor_session_id=request.headers.get("X-Session-ID"),
            correlation_id=_uuid.uuid4(),
            idempotency_key=idempotency_key,
            request_role_set=actor_roles,
        )
        if approval is not None:
            mark_audit_success(request, approval.id, metadata={
                "actor_sub": actor_sub,
                "approval_path": "pending",
            })
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=approval_response_body(session, approval),
            )
        # Below threshold — synchronous settlement. Verified at
        # cashflow_ledger.py:49-51: the write path returns
        # (event, ledger_entries) and the route composes the response.
        event, ledger_entries = ingest_hedge_contract_settlement(
            session, contract_id, payload, commit=False
        )
        mark_audit_success(request, event.id, metadata={"actor_sub": actor_sub})
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=HedgeContractSettlementResponse(
            event=event,
            ledger_entries=[
                CashFlowLedgerEntryRead.model_validate(entry) for entry in ledger_entries
            ],
        ).model_dump(mode="json"),
    )
```

**Import directive (binding for `backend/app/api/routes/cashflow_ledger.py`):** the current HEAD already imports `ingest_hedge_contract_settlement`, `HedgeContractSettlementResponse`, `HedgeContractSettlementCreate`, `CashFlowLedgerEntryRead`, `get_current_actor_sub`, `require_role`, `audit_event`, `mark_audit_success`, `unit_of_work`. The gate adds: `get_current_actor_roles` (from `app.core.auth`), `Header` (from `fastapi`), `JSONResponse` (from `fastapi.responses`), `import uuid as _uuid`, `from app.models.workflow_approval import MutationType`, `from app.services import workflow_approval_service`, plus `approval_response_body` and `ApprovalPendingResponseBody`. Per `feedback_dispatch_verify_imports`: enforced by §10 acceptance #29.

PR #76 / Cluster 1 settlement path is the institutional canonical route. Generic status-patch settlement remains forbidden per PR #76 §4 closure (the amendment's lines 590-593 reproduce this).

### §4.4 New approval router under `/workflow-approvals`

Create a new module `backend/app/api/routes/workflow_approvals.py` and register it in `backend/app/main.py` (alongside the existing routers — the include pattern at `backend/app/main.py:225` is the template).

**Router prefix:** `/workflow-approvals` (no leading `/api` — the StripApiPrefix middleware handles the prefix). The frontend consumes `/api/workflow-approvals/...` per the existing `frontend-svelte/src/lib/api/client.ts` base URL.

**Endpoint table (binding):**

| # | Route | Required role | Behavior | Returns |
|---|---|---|---|---|
| 1 | `GET /workflow-approvals/{approval_id}` | `risk_manager`, `auditor`, OR the original requester regardless of role | Polling endpoint per the amendment's Pending-mutation behavior clause line 833. Returns the current row state without side effects. | `WorkflowApprovalRequestRead` |
| 2 | `GET /workflow-approvals` | `risk_manager`, `auditor` | List endpoint with filters: `status`, `mutation_type`, `requested_by`, `expires_before`, `page`, `page_size`. Frontend uses this to render the pending-approvals panel. | `WorkflowApprovalRequestListResponse` |
| 3 | `POST /workflow-approvals/{approval_id}/grant` | role intersects `approval_policy.required_approver_roles` for the row's `mutation_type` | Calls `workflow_approval_service.grant_request`. Returns the transitioned row. | `WorkflowApprovalRequestRead` |
| 4 | `POST /workflow-approvals/{approval_id}/reject` | same as grant | Calls `workflow_approval_service.reject_request`. Body: `RejectRequest` with `code: RejectionReasonCode` + `text: str = Field(min_length=8, max_length=2048)`. | `WorkflowApprovalRequestRead` |
| 5 | `POST /workflow-approvals/{approval_id}/supersede` | original requester only (actor-level check inside the service per amendment lines 742-750) | Calls `workflow_approval_service.supersede_request`. Empty body. Route layer only verifies the JWT is valid; the actor-level check (`actor_sub == row.requested_by`) lives in the service to keep authorization centralized. | `WorkflowApprovalRequestRead` |
| 6 | `POST /workflow-approvals/{approval_id}/consume` | original requester only (same actor-level scoping as supersede) | Calls `workflow_approval_service.consume_request(session, approval_id, requesting_actor_sub=actor_sub, consume_payload_obj=body, executor=...)` — the `actor_sub` Depends from `get_current_actor_sub` is threaded as `requesting_actor_sub` so the service can enforce the `actor_sub == row.requested_by` check centrally. The executor callback dispatches per `row.mutation_type` to the underlying mutation service (Deal create / RFQ award / settle). Body: the canonical mutation payload that was originally submitted (the hash recheck validates parity). | `DealRead` / `RFQRead` / `HedgeContractSettlementResponse` — discriminated by `mutation_type` |

**Route-handler audit pattern (binding for ALL six routes):** every transitioning route (#3-6) wires through the institutional `audit_event` Depends + `mark_audit_success` pattern (per HB-1 §4.3.3 precedent and `backend/app/api/dependencies/audit.py:50-112`). The `audit_event` Depends's `entity_type` is `"workflow_approval_request"`; the `event_type` is the COMPOSED form (`"workflow_approval_granted"`, `"workflow_approval_rejected"`, `"workflow_approval_superseded"`, `"workflow_approval_consumed"`) per the amendment Audit events clause lines 862-891. The route handler calls the service method, then calls `mark_audit_success(request, row.id, metadata={...})` with the audit-payload fields (per §8 below).

**Composed `event_type` form (binding asymmetry vs HB-1's verb-only convention):** HB-1 §8 documented an asymmetric naming convention — gate-rejection events use descriptive composed strings (`rfq_invitation_rejected_kyc_not_approved`), entity-internal CRUD events use verb-only (`kyc_status_changed`). HB-2's six audit events take the COMPOSED form because they describe a lifecycle on the approval row itself, where "entity" is the approval and "event" is the lifecycle transition. Composing them into a single `event_type` string keeps cross-event correlation simple: audit consumers filtering on `event_type LIKE 'workflow_approval_%'` find the entire HB-2 lifecycle without joining columns. The `audit_event(...)` Depends at `backend/app/api/dependencies/audit.py:101` stores `entity_type` and `event_type` as separate columns without composing them — the executor passes the already-composed string literal (e.g. `event_type="workflow_approval_granted"`). The §7 tests assert the database row's `event_type` column value matches the composed form for all six events.

**Service-layer audit emission for `workflow_approval_requested` (binding asymmetry):** event 1 (`workflow_approval_requested`) is emitted from inside `workflow_approval_service.evaluate_and_maybe_create` because the row creation happens at the gate site, NOT in a dedicated route handler. Events 2/3/5/6 (granted/rejected/consumed/superseded) emit from route-level `audit_event` Depends on the corresponding approval-router endpoint. Event 4 (`workflow_approval_expired`) emits from the sweeper task only (no route surface — expiry is background-only). This asymmetry is documented in §8.

#### §4.4.1 New schemas in `backend/app/schemas/workflow_approval.py`

```python
# backend/app/schemas/workflow_approval.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.workflow_approval import (
    ApprovalStatus,
    MutationType,
    RejectionReasonCode,
    ThresholdDimension,
)


class WorkflowApprovalRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mutation_type: MutationType
    status: ApprovalStatus
    requested_by: str
    approved_by: str | None
    threshold_at_request: Decimal
    threshold_config_value: Decimal
    threshold_dimension: ThresholdDimension
    mutation_payload_canonical: dict | list
    mutation_payload_hash: str
    correlation_id: UUID
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime | None
    expires_at: datetime
    consumed_at: datetime | None
    approver_ip: str | None
    approver_session_id: str | None
    rejection_reason_code: RejectionReasonCode | None
    rejection_reason_text: str | None


class WorkflowApprovalRequestListResponse(BaseModel):
    items: list[WorkflowApprovalRequestRead]
    total: int
    page: int
    page_size: int


class RejectRequest(BaseModel):
    code: RejectionReasonCode
    text: str = Field(min_length=8, max_length=2048)


class ApprovalPendingResponseBody(BaseModel):
    """Returned with HTTP 202 from the three gated mutation routes."""

    approval_id: UUID
    status: ApprovalStatus = ApprovalStatus.pending
    expires_at: datetime
    required_approvers: list[str]
    polling_url: str
    consume_url: str
```

The `ApprovalPendingResponseBody` shape MUST match the amendment's Pending-mutation behavior clause line 833 verbatim. The `polling_url` and `consume_url` are absolute-path strings (e.g. `/workflow-approvals/{approval_id}`); the frontend prepends the API base URL.

### §4.4.7 `approval_response_body` helper

The three gated routes (§4.3.1 / §4.3.2 / §4.3.3) reference a single shared helper that constructs the HTTP 202 response body from a `WorkflowApprovalRequest` row. The helper lives in the new approval router module (`backend/app/api/routes/workflow_approvals.py`) and is exported as a module-level function so the three gate handlers can import it. Binding shape:

```python
# backend/app/api/routes/workflow_approvals.py (module-level)

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow_approval import (
    ApprovalPolicy, WorkflowApprovalRequest,
)


def approval_response_body(
    session: Session, row: WorkflowApprovalRequest
) -> dict:
    """Construct the HTTP 202 body for a pending approval row.

    `required_approvers` is loaded from the `approval_policy` table —
    NOT hardcoded — so the body reflects the persisted policy seed.
    Per amendment lines 660-665: post-pilot policy changes happen via
    alembic data migration, and the body MUST reflect the current
    persisted policy not a stale code constant.
    """
    policy = session.execute(
        select(ApprovalPolicy).where(
            ApprovalPolicy.mutation_type == row.mutation_type
        )
    ).scalar_one()
    return {
        "approval_id": str(row.id),
        "status": row.status.value,
        "expires_at": row.expires_at.isoformat(),
        "required_approvers": policy.required_approver_roles,  # list[str]
        "polling_url": f"/workflow-approvals/{row.id}",
        "consume_url": f"/workflow-approvals/{row.id}/consume",
    }
```

**Why a separate helper (binding rationale):** the three gate handlers in §4.3 each return the same shape; centralizing the construction prevents drift between routes. The helper is imported by each gate handler (per §4.3 import-directive note line 417); a silent NameError at module load if the import is missed is a P1 dispatch defect.

**Why load `required_approvers` from `approval_policy` (binding):** the persisted seed is the source of truth (per amendment lines 660-665). Hardcoding `["risk_manager"]` / `["auditor"]` into the response body would diverge from the policy table if a future amendment ever ships a data migration revising the seed — the 202 body would advertise stale required approvers while the grant route rejects the wrong role. Reading the policy at every 202 keeps the body source-of-truth-consistent at the cost of one indexed PK lookup per 202.

**Why the call happens inside `unit_of_work` (binding):** the route handlers in §4.3.1/4.3.2/4.3.3 invoke `approval_response_body(session, approval)` inside the route's `unit_of_work(session, request=request)` block — the session is still alive at that point. Per the §4.3 unit_of_work scope binding, the WHOLE handler body lives inside one unit_of_work; the response-body construction is no exception.

### §4.5 Expiry sweeper background task

Create `backend/app/tasks/workflow_approval_sweeper.py`. Register it in `backend/app/tasks/scheduler.py` alongside the existing `run_westmetall_ingestion` job (`scheduler.py:39`).

**Cadence (binding):** every 15 minutes. The amendment's Phase 2 deferral clause (lines 1117-1122) sets this as the recommended cadence and explicitly leaves the specific value as an implementation decision. The executor MAY make this env-var-configurable as `WORKFLOW_APPROVAL_SWEEPER_INTERVAL_MINUTES` with default `15`; the BINDING default is 15.

**Sweeper body:**

```python
# backend/app/tasks/workflow_approval_sweeper.py
"""Expiry sweeper for WorkflowApprovalRequest rows.

Constitutional anchor: docs/governance.md "Workflow Approval gate"
Phase 2 deferral clause lines 1117-1122. The sweeper transitions
`pending` AND `approved` rows past `expires_at` to `expired`; the
`(status, expires_at)` composite index on workflow_approval_requests
covers the lookup.
"""
from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.services import workflow_approval_service

_logger = logging.getLogger(__name__)


def run_workflow_approval_sweeper() -> None:
    session = SessionLocal()
    try:
        count = workflow_approval_service.sweep_expired(session)
        if count > 0:
            _logger.info(
                "workflow_approval_sweeper.transitioned",
                extra={"expired_count": count},
            )
        session.commit()
    except Exception:
        session.rollback()
        _logger.exception("workflow_approval_sweeper.error")
        raise
    finally:
        session.close()
```

**Scheduler registration (`backend/app/tasks/scheduler.py`):** add an `add_job` block alongside the existing ingestion job:

```python
# In start_scheduler() after the westmetall block:
_scheduler.add_job(
    run_workflow_approval_sweeper,
    "interval",
    minutes=settings.workflow_approval_sweeper_interval_minutes,
    id="workflow_approval_sweeper",
    replace_existing=True,
)
```

**`SCHEDULER_DISABLED` interaction (binding — guards against double-run):** per `CLAUDE.md`, the scheduler is disabled in web workers via `SCHEDULER_DISABLED=true` (Railway production has a separate `scheduler` service that runs `python -m app.scheduler_main` with `SCHEDULER_DISABLED=false`). The sweeper inherits this guard automatically — `start_scheduler()` is a no-op when `SCHEDULER_DISABLED=true`. The executor MUST NOT add a parallel sweeper invocation path that bypasses this guard.

### §4.6 SSE broadcast on state-change

Per amendment lines 852-860, every state transition broadcasts on the existing SSE channel as `workflow_approval_state_changed`. The executor MUST verify the current SSE broadcast wiring at branch HEAD (`grep -rn "sse\|EventSourceResponse\|stream_events" backend/app/`); if a centralized broadcast helper exists, route through it. If no centralized helper exists, this PR introduces one as `app/services/sse_broadcaster.py` (minimal — a single `broadcast(event_type: str, payload: dict)` function the lifecycle service calls).

**Broadcast payload (binding):** `{"approval_id": str, "old_status": str, "new_status": str, "transitioned_at": iso8601}`. The SSE `event_type` is the literal string `workflow_approval_state_changed`. The executor MUST NOT broadcast partial state (e.g. omit `old_status`) — frontend consumers depend on the field set.

If the codebase does NOT currently have an SSE infrastructure (the amendment refers to `/events` "or equivalent backend-events stream"), the executor MUST add a minimal one: a singleton in-process `asyncio.Queue` per connection, a `GET /events` endpoint streaming `text/event-stream` with a 25s keep-alive heartbeat, and the broadcast helper writing into all connected queues. Cluster 3 (PR #84) introduced the broader streaming/Clerk session lifecycle and SHOULD have left a hook; executor confirms.

### §4.7 Defense-in-depth "lacks risk_manager" assertion

Per amendment lines 1003-1024, the gate emits HTTP 403 BEFORE creating the approval row when the requesting JWT's role set lacks `risk_manager`. Implementation lives in `workflow_approval_service.evaluate_and_maybe_create`:

```python
def evaluate_and_maybe_create(
    session,
    *,
    mutation_type,
    payload_obj,
    threshold_value,
    requesting_actor_sub,
    requesting_actor_ip,
    requesting_actor_session_id,
    correlation_id,
    idempotency_key,
    request_role_set,  # set[str] from get_current_actor_roles
):
    threshold_config_value = _THRESHOLD_BY_MUTATION_TYPE[mutation_type]()
    if threshold_value <= threshold_config_value:
        return None  # below threshold — caller proceeds synchronously
    # Defense-in-depth: trader-only actors must not create approval rows.
    # The RBAC matrix already denies them at the route gate; this is
    # the structural guard against a regression in route-decorator
    # wiring that would silently admit a trader-only JWT here.
    if "risk_manager" not in request_role_set:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "role lacks risk_manager — institutional-threshold "
                "mutations require risk_manager scope"
            ),
        )
    # ... continue with idempotency-key lookup + row creation
```

The `{trader, risk_manager}` combinability case passes via the `risk_manager` membership — explicitly permitted per the amendment combinability clause and the AUTHORIZATION MATRIX lines 236-241.

### §4.8 Settings additions (env vars)

Extend `backend/app/core/config.py` `Settings` class with THREE new fields:

```python
# In Settings:
workflow_approval_deal_threshold_usd: Decimal = Field(
    default=Decimal("500000"),
    description="USD notional threshold above which deal_create / deal_award "
                "mutations require two-signatory approval per HB-2.",
)
workflow_approval_settle_threshold_usd: Decimal = Field(
    default=Decimal("250000"),
    description="USD settlement amount threshold above which "
                "hedge_contract_settle mutations require two-signatory "
                "approval per HB-2.",
)
workflow_approval_sweeper_interval_minutes: int = Field(
    default=15,
    ge=1,
    description="Expiry sweeper cadence per HB-2 Phase 2 deferral clause.",
)
```

Per the amendment lines 610-618, the pilot defaults are technical placeholders pending risk_committee ratification; the implementation MUST surface them in a clearly flagged operational note. Concrete binding: log the resolved threshold values on backend boot via the existing `startup_log` pattern (e.g. in `backend/app/main.py` lifespan startup), structured as:

```
INFO backend.startup workflow_approval_thresholds: deal=USD 500000.00 settle=USD 250000.00 (pilot defaults; awaiting risk_committee ratification)
```

The frontend pending-approvals panel (§6.2) renders a banner with the same content for risk_manager/auditor users.

## §5 Database / Alembic changes

**One new revision: `046_workflow_approval_gate.py`** continuing from `045_market_data_governance_columns`. The current head verified by `cd backend && python -m alembic heads` returns `045_market_data_governance_columns (head)` pre-merge; post-merge MUST return `046_workflow_approval_gate (head)`.

**Revision shape (binding):**

```python
"""046_workflow_approval_gate.

Revision ID: 046_workflow_approval_gate
Revises: 045_market_data_governance_columns
Create Date: 2026-05-XX (executor sets)

Constitutional anchor: docs/governance.md "Workflow Approval gate
(binding, Pilot Hard Blocker 2)" — Schema clause lines 1026-1097.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "046_workflow_approval_gate"
down_revision = "045_market_data_governance_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. CREATE TYPE enums (postgres). On sqlite, Enum() emits CHECK constraints.
    op.create_table(
        "workflow_approval_requests",
        sa.Column(
            "id",
            UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite"),
            primary_key=True,
        ),
        sa.Column(
            "mutation_type",
            sa.Enum(
                "deal_create", "deal_award", "hedge_contract_settle",
                name="workflow_approval_mutation_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "approved", "rejected", "expired", "consumed", "superseded",
                name="workflow_approval_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("threshold_at_request", sa.Numeric(20, 4), nullable=False),
        sa.Column("threshold_config_value", sa.Numeric(20, 4), nullable=False),
        sa.Column(
            "threshold_dimension",
            sa.Enum(
                "notional_usd", "settlement_amount_usd",
                name="workflow_approval_threshold_dimension",
            ),
            nullable=False,
        ),
        sa.Column(
            "mutation_payload_canonical",
            JSONB().with_variant(sa.Text(), "sqlite"),
            nullable=False,
        ),
        sa.Column("mutation_payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "correlation_id",
            UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approver_ip", sa.String(length=64), nullable=True),
        sa.Column("approver_session_id", sa.String(length=128), nullable=True),
        sa.Column(
            "rejection_reason_code",
            sa.Enum(
                "policy_violation", "counterparty_risk", "payload_concern",
                "threshold_inappropriate", "other",
                name="workflow_approval_rejection_reason_code",
            ),
            nullable=True,
        ),
        sa.Column("rejection_reason_text", sa.String(length=2048), nullable=True),
        sa.CheckConstraint(
            "requested_by != approved_by",
            name="ck_workflow_approval_requests_distinct_actors",
        ),
        sa.CheckConstraint(
            "(rejection_reason_code IS NULL AND rejection_reason_text IS NULL) "
            "OR (rejection_reason_code IS NOT NULL AND rejection_reason_text IS NOT NULL "
            "AND LENGTH(rejection_reason_text) >= 8)",
            name="ck_workflow_approval_requests_rejection_complete",
        ),
        sa.Index(
            "ix_workflow_approval_requests_correlation_id",
            "correlation_id",
        ),
    )
    # Composite index for the sweeper.
    op.create_index(
        "ix_workflow_approval_requests_status_expires_at",
        "workflow_approval_requests",
        ["status", "expires_at"],
    )
    # Partial UNIQUE on idempotency_key (postgres + sqlite 3.8+ both support).
    op.create_index(
        "ux_workflow_approval_requests_idempotency_key",
        "workflow_approval_requests",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "approval_policy",
        sa.Column(
            "mutation_type",
            sa.Enum(
                "deal_create", "deal_award", "hedge_contract_settle",
                name="workflow_approval_mutation_type",
                create_type=False,  # reuse the enum created above
            ),
            primary_key=True,
        ),
        sa.Column(
            "required_approver_roles",
            JSONB().with_variant(sa.Text(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "fallback_when_requester_is",
            JSONB().with_variant(sa.Text(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "threshold_dimension",
            sa.Enum(
                "notional_usd", "settlement_amount_usd",
                name="workflow_approval_threshold_dimension",
                create_type=False,
            ),
            nullable=False,
        ),
    )
    # Seed approval_policy per amendment lines 635-658. The
    # required_approver_roles + fallback_when_requester_is columns are
    # JSONB on postgres and TEXT-holding-JSON on sqlite — the bulk_insert
    # column types declare the variant-aware shape so SQLAlchemy passes
    # the dict/list directly to the JSONB adapter on postgres (no
    # double-encoding via json.dumps) and TEXT-coerces the value on
    # sqlite (which serializes through the same adapter path because
    # JSONB().with_variant(sa.Text(), "sqlite") inherits TypeEngine's
    # bind_processor / result_processor pair).
    op.bulk_insert(
        sa.table(
            "approval_policy",
            sa.column(
                "mutation_type",
                sa.Enum(
                    "deal_create", "deal_award", "hedge_contract_settle",
                    name="workflow_approval_mutation_type",
                    create_type=False,
                ),
            ),
            sa.column(
                "required_approver_roles",
                JSONB().with_variant(sa.Text(), "sqlite"),
            ),
            sa.column(
                "fallback_when_requester_is",
                JSONB().with_variant(sa.Text(), "sqlite"),
            ),
            sa.column(
                "threshold_dimension",
                sa.Enum(
                    "notional_usd", "settlement_amount_usd",
                    name="workflow_approval_threshold_dimension",
                    create_type=False,
                ),
            ),
        ),
        [
            {
                "mutation_type": "deal_create",
                "required_approver_roles": ["risk_manager"],
                "fallback_when_requester_is": {},
                "threshold_dimension": "notional_usd",
            },
            {
                "mutation_type": "deal_award",
                "required_approver_roles": ["risk_manager"],
                "fallback_when_requester_is": {},
                "threshold_dimension": "notional_usd",
            },
            {
                "mutation_type": "hedge_contract_settle",
                "required_approver_roles": ["auditor"],
                "fallback_when_requester_is": {},
                "threshold_dimension": "settlement_amount_usd",
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("approval_policy")
    op.drop_index(
        "ux_workflow_approval_requests_idempotency_key",
        table_name="workflow_approval_requests",
    )
    op.drop_index(
        "ix_workflow_approval_requests_status_expires_at",
        table_name="workflow_approval_requests",
    )
    op.drop_table("workflow_approval_requests")
    # Drop enum types (postgres only).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS workflow_approval_rejection_reason_code")
        op.execute("DROP TYPE IF EXISTS workflow_approval_threshold_dimension")
        op.execute("DROP TYPE IF EXISTS workflow_approval_status")
        op.execute("DROP TYPE IF EXISTS workflow_approval_mutation_type")
```

**Variant constraints (binding):** the `requested_by != approved_by` CHECK and the rejection-fields CHECK both ship inline in `create_table` per the alembic standard. The partial UNIQUE on `idempotency_key` uses `postgresql_where` + `sqlite_where` keyword arguments (both SQLAlchemy + SQLite 3.8+ support the WHERE clause on indexes). The executor MUST verify the test SQLite version (`python -c "import sqlite3; print(sqlite3.sqlite_version)"`) is ≥ 3.8; this is true for all supported Python/CI runners but the verification belongs in the executor's branch-HEAD sanity check.

**Chain hygiene (binding):** never rewrite `045_market_data_governance_columns.down_revision`. The new `046_workflow_approval_gate` revision is a linear continuation; `tests/test_alembic_chain.py` enforces single-head post-merge.

## §6 Frontend changes (minimum-viable consumer)

Per `feedback_dispatch_transport_partner_clause`: §4.3 + §4.4 ship new backend endpoints. To keep the contract end-to-end testable in the same PR, ship the minimum-viable frontend consumer.

### §6.1 Regenerate API types

`cd frontend-svelte && npm run api:types` — picks up the new `/workflow-approvals/*` routes + the dual-response-shape on the three gated mutations. The dual shape is declared via the `responses={201: {"model": DealRead}, 202: {"model": ApprovalPendingResponseBody}}` pattern (§4.3 handler shape); openapi-typescript renders this as a per-status-code discriminated type on each path. The typed client wrapper in `src/lib/api/client.ts` MUST branch on response status code to select the correct return shape — a 202 carries `ApprovalPendingResponseBody`, a 201/200 carries the original mutation read shape.

**Field-constraint drift callout (binding per `feedback_pydantic_field_constraints_drift`):** `RejectRequest.text` ships with `Field(min_length=8, max_length=2048)`. Adding a constrained `Field()` surfaces a `title` in OpenAPI, which openapi-typescript renders as a `/** Title */` JSDoc on the generated TS type. The executor MUST regenerate `frontend-svelte/src/lib/api/schema.d.ts` in the SAME commit that introduces the schema field — calibrated on PR #95 E2E `Check schema drift` failure. Similarly: `WorkflowApprovalRequestRead.mutation_payload_hash` (`String(length=64)` reflected as bounded string) and `ApprovalPendingResponseBody` add new TS types that must land in the same commit. §10 #23 enforces this via `git diff --exit-code`. (`DealCreate` is UNCHANGED per §4.3.1 server-compute binding — no new field added to its TS type.)

CI guard `npm run api:types:check` MUST pass on push.

### §6.2 Pending-approvals panel (minimum viable)

Create a new route `frontend-svelte/src/routes/(protected)/workflow-approvals/+page.svelte` rendering the list + per-row detail. Minimum surface:

- **List view:** table of pending+approved+expired+rejected+superseded+consumed rows from `GET /workflow-approvals`, with filters (status, mutation_type, requested_by, time range) and pagination. Row click expands the detail.
- **Detail view:** shows `requested_by`, `threshold_at_request`, `threshold_config_value`, `mutation_type`, `mutation_payload_canonical` (pretty-printed JSON), `status`, `expires_at` (with countdown for pending/approved), `approved_by`/`approver_ip`/`approver_session_id` (if granted), `rejection_reason_*` (if rejected), `consumed_at` (if consumed).
- **Action buttons (visible per role + status):**
  - **Grant** + **Reject** (visible to roles intersecting `required_approver_roles` for the row's mutation_type; the frontend reads the policy from a new `GET /workflow-approvals/policies` endpoint OR inlines the seed values from amendment lines 635-658 with a `// HB-2 binding` comment — executor's choice, the binding is "the buttons appear only for authorized roles"). Grant is one-click; Reject opens a modal with the `code` dropdown + `text` input (min 8 chars client-validated).
  - **Supersede** + **Consume** (visible only when the logged-in user is the original requester per `row.requested_by`). Consume opens a modal pre-populated with the canonical mutation payload (the row's `mutation_payload_canonical`) so the user can either submit it verbatim (typical) or edit before submit (rare; will trigger payload-drift 422).
- **Live updates:** subscribe to the SSE `workflow_approval_state_changed` event and refresh the affected row's display without polling.
- **Threshold banner:** on first load, fetch the configured thresholds (a new `GET /workflow-approvals/config` endpoint returning `{deal_threshold_usd, settle_threshold_usd, sweeper_interval_minutes}` OR hardcoded with a "pilot defaults pending ratification" warning per amendment lines 610-618).

UI visibility gating:
- The page renders for `risk_manager` and `auditor` roles. Trader sessions see nothing (the page is not in the trader nav).
- Per-row actions render per role+status logic above; non-authorized actors see read-only detail.

Error handling: HTTP 422 on consume with `code: payload_drift_detected` displays an inline diff (or a simple "Payload changed since approval" message) and offers the user three actions matching the amendment (resubmit, supersede, wait); HTTP 403 on grant/reject (role intersection failure) displays a generic permission-denied toast; HTTP 410 / 404 on operations against terminal rows displays the row's current state.

### §6.3 Pending-approvals indicator in the existing nav

In the protected layout (`frontend-svelte/src/routes/(protected)/+layout.svelte` — executor verifies path), add a small badge showing the count of `pending` rows the logged-in user is authorized to grant/reject (i.e. count from `GET /workflow-approvals?status=pending&required_approver_role={my_role}`). The badge is a single number; clicking navigates to the panel. Refreshed via SSE.

### §6.4 Gated-mutation 202 handling in existing pages

The Deal create form, the RFQ award button, and the HedgeContract settle form (under `frontend-svelte/src/routes/(protected)/...` — executor verifies paths) MUST handle the new 202 response shape:

- On 202: redirect to (or surface inline) the new pending-approvals panel detail view for `response.approval_id`, with a banner explaining "Your request requires approval before it can take effect." Include a "View pending approval" link.
- On 200/201 (below-threshold path): unchanged from current behavior.

This is the minimum end-to-end testable surface. Polish (Slack notifications to co-signers, mobile-friendly approval modal, etc.) is post-pilot.

## §7 Tests

### §7.1 New test file `backend/tests/test_workflow_approval_service.py`

Comprehensive coverage for the lifecycle service primitives. Minimum suite:

- `test_below_threshold_returns_none` — `evaluate_and_maybe_create` with `threshold_value < threshold_config_value` returns `None`; no row created; no audit event emitted.
- `test_above_threshold_creates_pending_row` — returns a `WorkflowApprovalRequest` row in `pending` state with `mutation_payload_hash` populated, `threshold_at_request` matching the input, `threshold_config_value` matching settings; emits `workflow_approval_requested` audit event with HMAC signature.
- `test_lacks_risk_manager_raises_403` — request_role_set excludes `risk_manager` → HTTPException(403) with detail matching the amendment's exact wording ("role lacks risk_manager — institutional-threshold mutations require risk_manager scope"). NO row created; NO audit event emitted.
- `test_combined_trader_risk_manager_passes_assertion` — `request_role_set={"trader", "risk_manager"}` → row created normally; the assertion passes via risk_manager membership per amendment combinability clause.
- `test_idempotency_key_returns_existing_row` — two `evaluate_and_maybe_create` calls with the same `idempotency_key` and same hashed payload return the SAME row (no second row created; the partial-UNIQUE index would also enforce this at the DB layer if the application-level check fails).
- `test_grant_transitions_pending_to_approved` — emits `workflow_approval_granted` audit event; populates `approved_by`, `approver_ip`, `approver_session_id`; broadcasts SSE.
- `test_grant_rejects_same_actor_as_requester` — `approver_actor_sub == row.requested_by` → HTTPException(422) with detail matching `requested_by != approved_by` invariant. The DB constraint would also catch this; the application-layer 422 is the friendly path.
- `test_grant_rejects_unauthorized_role` — approver role does NOT intersect `required_approver_roles` → HTTPException(403). For `hedge_contract_settle`, only `auditor` passes; for `deal_create`/`deal_award`, only `risk_manager` passes.
- `test_reject_transitions_pending_to_rejected_with_reason` — emits `workflow_approval_rejected`; persists `rejection_reason_code` + `rejection_reason_text`; CHECK constraint passes.
- `test_reject_with_short_reason_text_rejected` — `reason_text` length 7 → Pydantic 422 at the route layer (the `RejectRequest.text` field has `Field(min_length=8)`); no row mutation.
- `test_supersede_pending_by_requester` — `pending → superseded`; emits `workflow_approval_superseded` with `previous_status="pending"`; broadcasts SSE.
- `test_supersede_approved_by_requester` — `approved → superseded`; emits with `previous_status="approved"`.
- `test_supersede_by_non_requester_rejected` — `actor_sub != row.requested_by` → HTTPException(403). Same-role peer cannot supersede another's request per amendment actor-level scope.
- `test_consume_matching_hash_transitions_to_consumed` — payload-hash recomputes to the stored value → executor callback invoked; row transitions to `consumed`; `consumed_at` populated; emits `workflow_approval_consumed`.
- `test_consume_mismatched_hash_returns_422_and_keeps_approved` — payload-hash differs from stored → HTTPException(422) with `detail.code == "payload_drift_detected"`; row stays `approved` (NOT superseded); NO `workflow_approval_consumed` event emitted; NO `workflow_approval_superseded` event emitted (the row's state is unchanged).
- `test_consume_concurrent_double_consume` — two concurrent threads (or two async tasks) attempt `consume_request` against the same `approved` row with matching payload hashes. Only ONE thread's executor callback fires; the second observes the row as `consumed` after the first transaction commits and raises HTTP 409 Conflict from the status check. The `with_for_update()` lock serializes the two attempts on postgres; on sqlite the test driver's global write serialization produces the same outcome. Assertion: exactly ONE `workflow_approval_consumed` audit event row, and exactly ONE downstream mutation row (deal / settlement) created.
- `test_consume_executor_failure_keeps_approved` — executor callback raises an uncaught exception → outer `unit_of_work` rolls back; row state in DB stays `approved` (the consume audit event was not committed); failure is surfaced to the caller as an HTTP 5xx.
- `test_consume_non_requester_rejected` — supersede authorization is actor-level; consume MUST be the same (the user submitting the consume payload is necessarily the same actor that originally requested, per the institutional flow). If a peer with the same role tries to consume, the actor-level check raises 403.
- `test_sweep_expired_transitions_pending_past_expiry` — `pending` row with `expires_at < now()` transitions to `expired`; emits `workflow_approval_expired` with `previous_status="pending"`; broadcasts SSE.
- `test_sweep_expired_transitions_approved_past_expiry` — same shape; `previous_status="approved"`.
- `test_sweep_expired_idempotent` — running the sweeper twice on the same `pending`/`approved` rows past expiry only transitions each ONCE (the second pass finds no eligible rows).
- `test_payload_hash_uses_normalize_payload_raw` — institutional binding test: monkey-patches `normalize_payload_raw` and asserts the hash helper calls through it (NOT a json.dumps shim). The amendment binds this canonicalization at lines 808-811 — this test is the institutional forward-compatibility guard.
- `test_audit_events_use_composed_event_type` — for each of the 6 events, the AuditEvent row's `event_type` column value is the composed string (`workflow_approval_requested`, etc.), NOT the verb-only form.
- `test_audit_events_carry_previous_status_on_transitions` — granted/rejected/expired/consumed/superseded events have `previous_status` field populated in the payload; `requested` event has `previous_status=null`.
- `test_audit_events_carry_threshold_dimension_used_and_threshold_at_request` — payload field names match amendment lines 902-911 (`threshold_dimension_used`, `threshold_at_request`) with values matching the row's columns.
- `test_approval_policy_seed` — after `alembic upgrade head` runs, the `approval_policy` table contains exactly 3 rows matching the amendment seed: `deal_create → required_approver_roles=["risk_manager"], fallback_when_requester_is={}, threshold_dimension=notional_usd`; `deal_award → required_approver_roles=["risk_manager"], fallback_when_requester_is={}, threshold_dimension=notional_usd`; `hedge_contract_settle → required_approver_roles=["auditor"], fallback_when_requester_is={}, threshold_dimension=settlement_amount_usd`. (Enforces amendment lines 635-658 + §10 acceptance #7.)

### §7.2 New test file `backend/tests/test_workflow_approval_routes.py`

End-to-end route coverage via FastAPI TestClient. Minimum:

- `test_post_deals_below_threshold_synchronous_path` — `POST /deals` with notional < 500k returns 201 + `DealRead`; `Deal` row created; NO `WorkflowApprovalRequest` row.
- `test_post_deals_above_threshold_returns_202` — POST with notional ≥ 500k returns 202 + body matching `ApprovalPendingResponseBody`; `WorkflowApprovalRequest` row in `pending`; NO `Deal` row.
- `test_post_rfqs_award_above_threshold_returns_202` — same shape on the award route.
- `test_post_settle_above_threshold_returns_202` — same shape on the settle route.
- `test_grant_workflow_route_authorized_role` — risk_manager grants a deal-create request; row transitions to `approved`; audit event emitted.
- `test_grant_workflow_route_unauthorized_role` — auditor tries to grant a deal-create request → 403 (auditor is not in `required_approver_roles` for deal_create).
- `test_reject_workflow_route` — risk_manager rejects with valid reason; row transitions to `rejected`.
- `test_supersede_workflow_route_by_requester` — original requester supersedes pending row.
- `test_consume_workflow_route_below_threshold_path_unreachable` — defensive: confirm that calling the consume endpoint on a `WorkflowApprovalRequest` that was created from a below-threshold flow (impossible by construction since below-threshold creates no row) returns 404. This is a regression guard against a future refactor that might accidentally create rows for below-threshold mutations.
- `test_consume_workflow_route_happy_path` — risk_manager creates deal-create approval, second risk_manager grants, original requester consumes with matching payload → 200 + `DealRead`; `Deal` row created at consume time (NOT at the original 202).
- `test_consume_workflow_route_payload_drift` — same setup but consume payload differs → 422 with `code: payload_drift_detected`; row stays `approved`; no `Deal` row.
- `test_workflow_approval_idempotency_key_dedup_concurrent` — two parallel `POST /deals` with the same `Idempotency-Key` header and the same above-threshold payload → only ONE `WorkflowApprovalRequest` row created (partial-UNIQUE index on `idempotency_key` blocks the race); the second request returns 202 with the same `approval_id`.
- `test_workflow_approval_audit_events_all_six_emitted` — sequence test: create (1) → grant (2) → consume (5); separate row: create → reject (3); separate: create → supersede (6); separate: create → expire via sweeper (4). Each step asserts the corresponding audit event row exists with valid HMAC signature and composed `event_type`.
- `test_sse_broadcast_on_state_change` — connect to the SSE endpoint; trigger a grant; observe the `workflow_approval_state_changed` event with `{approval_id, old_status: "pending", new_status: "approved", transitioned_at: ...}` payload.

### §7.3 RBAC matrix tests in `backend/tests/test_rbac_matrix_enforcement.py`

Append entries for the new approval-router routes:

- `GET /workflow-approvals/{id}` — accept: risk_manager, auditor, OR original requester (special case — assert in a dedicated test); reject: unrelated trader, unauthenticated.
- `GET /workflow-approvals` — accept: risk_manager, auditor; reject: trader (403), unauthenticated (401).
- `POST /workflow-approvals/{id}/grant` — accept: roles intersecting `required_approver_roles` per row's `mutation_type`; reject: others.
- `POST /workflow-approvals/{id}/reject` — same as grant.
- `POST /workflow-approvals/{id}/supersede` — accept: only the original requester (actor-level); reject: every other actor including same-role peers.
- `POST /workflow-approvals/{id}/consume` — same as supersede.

### §7.4 Alembic chain test (existing)

`backend/tests/test_alembic_chain.py` already enforces single-head. Post-merge, the head MUST be `046_workflow_approval_gate`. No new test needed; the existing test catches any chain fork.

### §7.5 Settings tests

In `backend/tests/test_config.py` (or wherever Settings is tested at HEAD — executor verifies), assert the three new fields default to the binding values: `workflow_approval_deal_threshold_usd == Decimal("500000")`, `workflow_approval_settle_threshold_usd == Decimal("250000")`, `workflow_approval_sweeper_interval_minutes == 15`. Assert env-var override works (`WORKFLOW_APPROVAL_DEAL_THRESHOLD_USD=750000` → `Decimal("750000")`).

### §7.6 Frontend tests

Vitest coverage:
- Pending-approvals panel renders list, detail, action buttons per role+status logic.
- Reject modal validates `text` minimum 8 chars client-side.
- 202 handling on gated-mutation pages redirects to the pending-approval detail.
- SSE state-change updates the row without polling.

E2E Playwright is RECOMMENDED but not blocking. If the executor extends the existing E2E suite with a "create deal above threshold → grant → consume → deal appears" flow, that's high-value institutional coverage; if not, the backend tests suffice for this PR.

## §8 Audit-trail emission

Exactly SIX audit `event_type` values land in this PR. All emitted via `AuditTrailService.record(...)` (cite `backend/app/services/audit_trail_service.py:74-119`). All HMAC-signed.

The composed-string convention (NOT verb-only) applies to all six per the amendment lines 870-891. The asymmetric naming rationale matches HB-1's gate events (cross-entity institutional conditions; composed name uniquely identifies the institutional condition without requiring a join across columns).

| # | event_type | emitted from | entity_type | trigger | payload shape (binding per amendment lines 893-994) |
|---|---|---|---|---|---|
| 1 | `workflow_approval_requested` | `workflow_approval_service.evaluate_and_maybe_create` (§4.1) — service-layer emission because the row creation lives in the service, not in a dedicated route | `workflow_approval_request` | each `pending` row creation (one per gated mutation 202) | common payload (§ amendment 893-994); `previous_status=null`; `approver_*=null`; `rejection_reason=null`; `time_to_approval_ms=null` |
| 2 | `workflow_approval_granted` | route-level `audit_event` Depends + `mark_audit_success` in `POST /workflow-approvals/{id}/grant` (§4.4 #3) | `workflow_approval_request` | each `pending → approved` transition | common payload; `previous_status="pending"`; `approver_sub`/`approver_ip`/`approver_session_id` populated; `rejection_reason=null`; `time_to_approval_ms` = audit-event timestamp − row.created_at |
| 3 | `workflow_approval_rejected` | route-level (§4.4 #4) | `workflow_approval_request` | each `pending → rejected` transition | common payload; `previous_status="pending"`; approver fields populated; `rejection_reason={code, free_text}` populated; `time_to_approval_ms` populated |
| 4 | `workflow_approval_expired` | `workflow_approval_sweeper.run_workflow_approval_sweeper` (§4.5) — background task, not a route | `workflow_approval_request` | each `(pending|approved) → expired` transition by the sweeper | common payload; `previous_status="pending"` or `"approved"` (distinguishes the source state); `approver_*` carry over from the row if `approved → expired` (read-back from persisted columns); `time_to_approval_ms` = audit-event timestamp − row.created_at |
| 5 | `workflow_approval_consumed` | route-level (§4.4 #6) | `workflow_approval_request` | each `approved → consumed` transition (only after successful executor callback) | common payload; `previous_status="approved"`; `approver_sub`/`approver_ip`/`approver_session_id` read back from the row (denormalized from the grant-time capture per amendment lines 928-947 — the consumed event carries the original co-signer's IP, NOT the consumer's); `rejection_reason=null`; `time_to_approval_ms` populated |
| 6 | `workflow_approval_superseded` | route-level (§4.4 #5) | `workflow_approval_request` | each `(pending|approved) → superseded` transition (requester-initiated only) | common payload; `previous_status="pending"` or `"approved"`; `approver_*=null` (no approver actor on supersede); `rejection_reason=null`; `time_to_approval_ms` populated |

**`time_to_approval_ms` computation (binding per amendment lines 969-989):** the value is `int((audit_event.created_at - workflow_approval_requests.created_at).total_seconds() * 1000)` — using the AUDIT EVENT'S timestamp, NOT `workflow_approval_requests.updated_at`. Python's `datetime.timedelta` exposes `.total_seconds()` (float) but NO `.total_milliseconds()` method; the `* 1000` multiplication on the float result followed by `int()` cast yields the integer millisecond delta. `updated_at` is excluded from the formula because it shifts on every state mutation; reading it back at a later read would retroactively change past audit records' computed delta. The audit-event row's `created_at` is the canonical transition timestamp; the implementation MUST compute this delta server-side at emission time and persist it in the audit payload.

**`approver_ip` / `approver_session_id` persistence (binding per amendment lines 928-947):** captured from the co-signer's request context at `pending → approved` (or `pending → rejected`) and persisted onto the `workflow_approval_requests.approver_ip` / `.approver_session_id` columns. On `approved → consumed`, the consumed event reads these columns back — does NOT re-capture from the consumer's request context. This is the "denormalized read path" the amendment binds; ensures the consumed-event's approver attribution stays consistent with the grant-time record.

**`audit_event` Depends does NOT compose entity_type and event_type into a single string** — the audit row stores `entity_type="workflow_approval_request"` + `event_type="workflow_approval_requested"` (or the corresponding composed string for events 2-6) as separate columns. This is contrary to HB-1's convention for entity-internal CRUD events (which use verb-only). The reason for the asymmetry: HB-2 audit events describe a lifecycle on the approval row itself, where the "entity" is the approval and the "event" is the lifecycle transition — composing them into a single string keeps the cross-event correlation simple (audit consumers filtering on `event_type LIKE 'workflow_approval_%'` find the entire HB-2 lifecycle without joining columns). The asymmetric naming convention HB-1 §8 documented holds: HB-2 events are CLOSER to gate-rejection events than to entity-internal CRUD events.

Audit emission timing rule (binding): events 2/3/5/6 emit via the institutional route-level `audit_event` Depends + `mark_audit_success` pattern inside `unit_of_work`. The mutation (state transition) and the audit row commit atomically on the same session — same-rollback safety. Event 1 emits from inside the service method `evaluate_and_maybe_create`; the service is called from inside the gated route's `unit_of_work`, so the row creation + the audit event commit atomically on the SAME session as the rest of the route. Event 4 emits from the sweeper task, which opens its own `SessionLocal()` per iteration and commits the transition + audit atomically.

No companion audit-trail evidence PR ships separately for HB-2 — the audit events are internal to this dispatch's scope.

## §9 Docs

- No `docs/governance.md` change. The constitutional amendment was merged in PR #96 and is the source of truth for this dispatch.
- No `docs/systemconstitucion.md` change.
- No `docs/runbook-railway.md` change directly — but the executor MUST verify the runbook documents the existing `scheduler` service (separate from `backend`) per `CLAUDE.md`; the new sweeper job inherits the existing scheduler infrastructure with no infra change required. If the runbook does not document the scheduler explicitly, that is a known doc gap NOT in HB-2 scope.
- `CLAUDE.md` change: NOT REQUIRED. The Workflow Approval gate is a constitutional rule already covered by the AUTHORIZATION MATRIX subsection of `docs/governance.md`; CLAUDE.md does not repeat it.
- `docs/GAP_ANALYSIS_LEGACY_VS_NEW.md` change: NOT REQUIRED in this PR. After merge, the next GAP refresh will move HB-2 from "ABSENT" to "LANDED (HB-2)" — that update is part of the HB-2 closure memo, not this PR.
- `docs/2026-05-tech-lead-executive-analysis.md` (pilot brief) change: NOT REQUIRED. The brief's §2 HB-2 already prescribes this scope; the executor PR closes the HB rather than amending the brief. Brief §7 sign-off acknowledges HB-2 closed when this PR merges.

## §10 Acceptance criteria

Every item below is verifiable post-merge by running the cited command against the merged HEAD.

1. **Alembic head advances.** `cd backend && python -m alembic heads` returns exactly `046_workflow_approval_gate (head)`. Exactly one new revision file under `backend/alembic/versions/` named `046_workflow_approval_gate.py`. (Enforces §5.)
2. **Both new tables exist with all binding columns.** `cd backend && python -m alembic upgrade head && python -m alembic check` (or equivalent introspection) confirms `workflow_approval_requests` and `approval_policy` tables exist with every column from §4.2 / §5 present. (Enforces §5 schema clause.)
3. **Partial UNIQUE on `idempotency_key` exists.** Postgres: `SELECT indexdef FROM pg_indexes WHERE indexname = 'ux_workflow_approval_requests_idempotency_key'` returns a definition containing `WHERE (idempotency_key IS NOT NULL)`. SQLite: `SELECT sql FROM sqlite_master WHERE name = 'ux_workflow_approval_requests_idempotency_key'` returns a CREATE INDEX with `WHERE idempotency_key IS NOT NULL`. (Enforces amendment lines 1038-1050.)
4. **Composite `(status, expires_at)` index exists.** Same shape as #3, index name `ix_workflow_approval_requests_status_expires_at`. (Enforces amendment lines 1068-1072 sweeper invariant.)
5. **`requested_by != approved_by` CHECK constraint exists.** Postgres: `SELECT conname FROM pg_constraint WHERE conname = 'ck_workflow_approval_requests_distinct_actors'` returns 1 row. SQLite: `SELECT sql FROM sqlite_master WHERE tbl_name = 'workflow_approval_requests'` contains `CHECK (requested_by != approved_by)`. (Enforces amendment lines 1085-1096.)
6. **Rejection-fields CHECK constraint exists.** Same shape, constraint name `ck_workflow_approval_requests_rejection_complete`; predicate enforces both NULL or both NOT NULL with `LENGTH(rejection_reason_text) >= 8`. (Enforces amendment lines 1073-1077.)
7. **`approval_policy` seeded with three rows.** `cd backend && python -m pytest backend/tests/test_workflow_approval_service.py::test_approval_policy_seed -v` passes; asserts: `deal_create → ["risk_manager"], {}`, `deal_award → ["risk_manager"], {}`, `hedge_contract_settle → ["auditor"], {}`. (Enforces amendment lines 635-658.)
8. **Service module exists.** `grep -n "def evaluate_and_maybe_create\|def grant_request\|def reject_request\|def supersede_request\|def consume_request\|def sweep_expired" backend/app/services/workflow_approval_service.py` returns 6 matches — one per public lifecycle function. (Enforces §4.1.)
9. **All three gated routes invoke the gate.** `grep -nB2 "evaluate_and_maybe_create" backend/app/api/routes/deals.py backend/app/api/routes/rfqs.py backend/app/api/routes/cashflow_ledger.py` returns 3 matches, one per gated route, with the call preceding the synchronous mutation path. (Enforces §4.3.)
9a. **`RFQService.resolve_awarded_quote` refactor landed.** `grep -n "def resolve_awarded_quote" backend/app/services/rfq_service.py` returns exactly 1 match. `grep -nA3 "def award" backend/app/services/rfq_service.py | grep "resolve_awarded_quote"` returns ≥1 match (the existing `award` method now calls the helper as its first executable step after `get_live_for_update`). The helper signature returns `tuple[RFQIntent, list[tuple[RFQQuote, Decimal]]]` per §4.3.2 binding — a list of `(quote, quantity_mt)` pairs of length 1 (single-trade) or 2 (spread). (Enforces §4.3.2 REFACTOR path.)
9b. **`_compute_deal_notional_from_links` helper exists + `DealCreate` unchanged.** `grep -n "def _compute_deal_notional_from_links" backend/app/api/routes/deals.py backend/app/services/deal_notional.py 2>/dev/null` returns ≥1 match. `grep -nA10 "class DealCreate" backend/app/schemas/deal.py | grep "notional_usd"` returns 0 matches — confirming the schema is unchanged and the gate computes notional server-side from links per the §4.3.1 security binding. (Enforces the post-iter-3 security fix.)
10. **Approval router registered.** `grep -n "workflow_approvals\|workflow_approval" backend/app/main.py` returns matches showing the router import + `app.include_router(workflow_approvals.router, prefix="/workflow-approvals", tags=["WorkflowApprovals"])`. (Enforces §4.4 router registration.)
11. **All six approval-router endpoints exist.** `grep -nE "@router\.(post|get).*\"/?\\{approval_id\\}/(grant|reject|supersede|consume)\"|@router\\.get.*\"/?(\\{approval_id\\}|\"\")" backend/app/api/routes/workflow_approvals.py` returns ≥6 distinct decorator lines (1 GET single, 1 GET list, 4 POST actions). (Enforces §4.4 endpoint table.)
12. **Defense-in-depth assertion exists.** `grep -n "lacks risk_manager" backend/app/services/workflow_approval_service.py` returns at least one match in the body of `evaluate_and_maybe_create`. (Enforces §4.7 + amendment lines 1003-1024.)
13. **Sweeper task registered.** `grep -n "workflow_approval_sweeper" backend/app/tasks/scheduler.py backend/app/tasks/workflow_approval_sweeper.py` returns matches in both files. `grep -n "add_job\|workflow_approval_sweeper" backend/app/tasks/scheduler.py` shows the registration with `interval` trigger. (Enforces §4.5.)
14. **`SCHEDULER_DISABLED` guard preserved.** `grep -n "SCHEDULER_DISABLED" backend/app/tasks/scheduler.py backend/app/main.py` returns the existing guard unchanged; the new sweeper job does NOT bypass it. (Enforces §4.5 web-worker safety.)
15. **`mutation_payload_hash` uses `normalize_payload_raw`.** `grep -nA3 "def _compute_payload_hash" backend/app/services/workflow_approval_service.py` shows `normalize_payload_raw(payload_obj)` called inside the helper. (Enforces amendment lines 808-811.)
16. **Six audit `event_type` constants exist.** `grep -rnE "workflow_approval_(requested|granted|rejected|expired|consumed|superseded)" backend/app/` returns ≥6 distinct matches (one per event-type constant string). (Enforces §8.)
17. **`compliance_officer` is not introduced.** `grep -rni "compliance_officer" backend/` returns 0 matches. (Enforces §2 boundary + amendment Role additions clause.)
18. **No new admin route for `approval_policy`.** `grep -nE "@router\\.(post|put|patch|delete).*approval_policy|/approval-polic" backend/app/api/routes/` returns 0 matches. (Enforces §2 boundary + amendment lines 660-665.)
19. **Settings fields exist.** `grep -nE "workflow_approval_deal_threshold_usd|workflow_approval_settle_threshold_usd|workflow_approval_sweeper_interval_minutes" backend/app/core/config.py` returns ≥3 matches. (Enforces §4.8.)
20. **Threshold values logged on startup.** `grep -n "workflow_approval_thresholds" backend/app/main.py` (or wherever lifespan startup logs land at HEAD) shows the startup log line per §4.8. (Enforces amendment lines 612-616 operational note clause.)
21. **Backend tests pass.** `cd backend && python -m pytest tests/test_workflow_approval_service.py tests/test_workflow_approval_routes.py tests/test_rbac_matrix_enforcement.py -v` exits 0 with ≥30 new test cases (per §7.1+§7.2+§7.3).
22. **Full suite green.** `cd backend && python -m pytest -q` exits 0; passing-test count is at least `<baseline + 30>`.
23. **OpenAPI regen + frontend type drift check pass.** `cd frontend-svelte && npm run api:types && git diff --exit-code src/lib/api/schema.d.ts` shows the regenerated file matches the committed file. `npm run api:types:check` passes.
24. **Frontend vitest passes.** `cd frontend-svelte && npm run test` exits 0 with the new approval-panel test cases included.
25. **Frontend build passes.** `cd frontend-svelte && npm run build` exits 0; ECharts bundle-size budget passes.
26. **Pre-push hook v2 clean.** The hook run on the final implementation push produces 0 P1 findings.
27. **AugmentCode + Greptile gates green.** Per `reference-review-gates-2026-05-17`: Greptile +1 reaction on the implementation PR + all inline comments resolved + `Greptile Review` CI check green + AugmentCode catches absorbed.
28. **Threshold ratification recorded (operational, NOT a code gate).** Verifiable by Andrei post-merge: if risk_committee ratifies values different from the defaults (USD 500k deal / USD 250k settle), Railway dashboard env-var overrides set per §3 #1. This is recorded in the pilot brief §7 sign-off notes, NOT in the PR.
29. **Import directive sweep clean.** All three gated route modules import `get_current_actor_roles` and `Header` plus the new approval-service identifiers. `grep -n "get_current_actor_roles\|Header\|workflow_approval_service\|MutationType" backend/app/api/routes/deals.py backend/app/api/routes/rfqs.py backend/app/api/routes/cashflow_ledger.py` returns ≥4 matches per file. `cd backend && python -c "import app.api.routes.deals, app.api.routes.rfqs, app.api.routes.cashflow_ledger"` exits 0 (no `NameError` at module load). (Enforces `feedback_dispatch_verify_imports` across all three gate sites.)
30. **Settle entity_type preserved.** `grep -n 'entity_type="hedge_contract_settlement"' backend/app/api/routes/cashflow_ledger.py` returns ≥1 match — the audit decorator on `settle_hedge_contract` retains the existing `entity_type="hedge_contract_settlement"` (NOT renamed to `"hedge_contract"`). (Enforces §4.3.3 audit-correlation invariant.)
31. **Settle write-path identity preserved.** `grep -n "ingest_hedge_contract_settlement\|HedgeContractSettlementService" backend/app/api/routes/cashflow_ledger.py backend/app/services/` shows the route calls `ingest_hedge_contract_settlement` (NOT a `HedgeContractSettlementService.settle` class method) and no `HedgeContractSettlementService` class is introduced. (Enforces §4.3.3 write-path identity.)
32. **Deal write-path identity preserved.** `grep -n "DealEngineService\|DealEngine\b" backend/app/api/routes/deals.py backend/app/services/deal_engine.py` shows the route calls `DealEngineService.create_deal` (the existing class name; NOT a non-existent `DealEngine`). (Enforces §4.3.1 write-path identity.)

## §11 Workflow

1. Executor session opens isolated branch from current main HEAD `7c0588a8d` (or whatever main is at session-start; executor verifies with `git fetch origin && git log origin/main -1`).
2. Executor reads this dispatch end-to-end, reads `docs/governance.md` "Workflow Approval gate" subsection in full (lines 554-1128), reads the cited code excerpts in `backend/app/api/routes/deals.py:94`, `backend/app/api/routes/rfqs.py:474`, `backend/app/api/routes/cashflow_ledger.py:28`, `backend/app/services/audit_trail_service.py:74-216`, `backend/app/api/dependencies/audit.py:50-112`, `backend/app/api/dependencies/uow.py`, `backend/app/tasks/scheduler.py`, `backend/app/core/config.py`, `backend/app/models/deal.py`, `backend/app/schemas/cashflow.py:91-106`, `backend/app/schemas/rfq.py:221-247` to verify identifiers and offsets at branch HEAD.
3. Executor verifies the notional-computation contract for §4.3.1 by reading the current `DealCreate` at `backend/app/schemas/deal.py:38-41` and the `Deal` ORM model. The dispatch BINDS the server-side computation path (§4.3.1): notional is summed from the `HedgeContract` rows referenced by `body.links` via the new `_compute_deal_notional_from_links` helper; `DealCreate` schema is UNCHANGED (no `notional_usd` field — trusting client input on a security boundary was rejected after Greptile iter 3 surfaced the bypass). The executor confirms by reading §4.3.1 that no Path-A/Path-B re-litigation is open; documents in the PR description that the server-compute path is the bound contract.
4. Executor implements alembic 046 first (§5), runs `cd backend && python -m alembic upgrade head` against a clean SQLite test DB, then runs a downgrade + upgrade cycle to verify reversibility. Confirms enum types are created/dropped correctly on postgres via a quick local-docker postgres run.
5. Executor implements §4.2 (ORM models) + §4.1 (lifecycle service) + §4.8 (Settings fields). Runs `cd backend && python -m pytest tests/test_workflow_approval_service.py -x -q` after each major milestone.
6. Executor implements §4.5 (sweeper task + scheduler registration) + §4.6 (SSE broadcast helper).
7. Executor implements §4.3.1 / §4.3.2 / §4.3.3 (gate insertions) + §4.4 (approval router) + §4.7 (defense-in-depth). Runs the full backend test suite (`cd backend && python -m pytest -x -q`).
8. Executor runs `cd backend && ruff check . && ruff format .`.
9. Executor implements §6 (frontend changes): regenerate API types, build the pending-approvals panel + nav badge + 202-handlers on gated-mutation pages. Runs `cd frontend-svelte && npm run check && npm run test && npm run build`.
10. Executor pushes the branch. Pre-push hook v2 reviews any new `docs/audits/` file IF the executor adds a per-PR summary file there; the hook is silent if not. The branch name follows the convention `feat/hb-2-workflow-approvals-implementation`.
11. Executor opens the PR linking back to this dispatch + the amendment PR #96.
12. AugmentCode + Greptile review. Per `reference-review-gates-2026-05-17`: silent re-review on absorption pushes is acceptance (no second +1 needed). Convergent catches (Greptile + AugmentCode same locus) are high-confidence P1 regardless of individual rating per `convergent-catch-signal`.
13. Optional but recommended for institutional-weight PRs: orchestrator runs `/codex:adversarial-review` after first round of bot reviewers absorbed. Per `reference-review-gates-2026-05-17`, Codex catches design-level issues the precision-reviewers miss.
14. Andrei merges when: Greptile +1 reaction present + zero unresolved threads + CI all SUCCESS + AugmentCode catches absorbed + Andrei's explicit text authorization (per `feedback_dispatch_transport_partner_clause` and the prior session merges of HB-1 #94 and HB-2 amendment #96).
15. After merge, Andrei (or orchestrator on Andrei's authorization) executes the operational pre-condition #1 from §3 if production thresholds differ from the binding defaults: sets the `WORKFLOW_APPROVAL_DEAL_THRESHOLD_USD` / `WORKFLOW_APPROVAL_SETTLE_THRESHOLD_USD` env vars on the Railway `backend` and `scheduler` services. Records the values in the pilot brief §7 sign-off notes.
16. HB-2 is closed. Pilot conditional-go progress: 2/4 HBs delivered (HB-1 full + HB-2 full). Next: HB-3 (Finance Pipeline daily) governance amendment authoring — separate audit cycle, separate dispatch.

---

**Executor preference (per `feedback_executor_false_completion_pattern`):** Codex CLI. If another executor is used, mandatory 3-endpoint independent verification (PR + actions + reactions) before merge auth regardless of executor self-report.

**Handoff artifact:** when the executor session begins, create `.handoffs/hb-2-workflow-approvals-implementation.md` (gitignored) summarizing the executor's context-window-friendly briefing (links to this dispatch + amendment PR #96 + HB-1 precedent PRs #94/#95, working-tree expected state, commands to run first).
