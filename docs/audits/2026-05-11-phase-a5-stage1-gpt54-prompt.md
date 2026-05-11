# Phase A5 - Stage 1 Audit Dispatch - Auditor A

**Phase:** A5 - Audit trail, governance enforcement, and cross-cutting reconstruction  
**Stage:** 1 of 3  
**Target auditor:** GPT 5.4  
**Authoring date:** 2026-05-11  
**Repository:** `D:/Projetos/Hedge-Control-New`  
**Branch:** `main`  
**Expected output:** `docs/audits/2026-05-11-phase-a5-findings-gpt54.md`

## 1. Operating Instructions

You are performing a read-only institutional audit. Do not edit code, migrations,
tests, generated schemas, or governance documents. Your job is to inspect the
current codebase and produce an evidence-backed findings report.

This stage replaces the usual Opus auditor because Opus 4.7 is temporarily
unavailable. Treat this as an independent first-pass audit. Do not assume the
Gemini auditor will see the same issues. The final adjudication will be done by
GPT 5.5 in Stage 3.

Use direct code evidence. Every accepted finding must include file and line
references, a concrete failure mode, and the institutional rule it violates. Do
not report style issues, naming preferences, hypothetical rewrites, or refactors
without a demonstrated correctness, auditability, determinism, or reconstruction
impact.

## 2. Institutional Context

Closed phases:

- A1 is closed: economic primitives and lifecycle foundations.
- A2 is closed: RFQ canonical identity, ranking, award, and outbound evidence.
- A3 is closed: valuation, MTM, cashflow baseline, ledger reconciliation, and
  P&L lifecycle.
- A4 is closed: integration trust, inbound durability, replay, and LLM decision
  reconstruction.

Phase A5 is cross-cutting. Its scope is not to reopen A1-A4 business logic
unless the audit/governance layer fails to prove, sign, preserve, or reconstruct
those closed invariants.

Binding governance is `docs/governance.md`. For this audit, the central clauses
are:

- `docs/governance.md:55-56` - auditability and reconstructability are primary
  optimization targets.
- `docs/governance.md:113-115` - RFQ invitations are persisted; terms sent equal
  terms stored; messages are evidence.
- `docs/governance.md:174-181` - evidence missing, ambiguous dates,
  unreconstructible contracts, and unprovable references are hard-fail
  conditions.
- `docs/governance.md:186` - no mutation without evidence.
- `docs/governance.md:188-193` - explicit phased execution and no preemption of
  future phases.

Hard-fail remains the default. Unsigned audit rows, best-effort audit writes,
audit rows committed separately from the mutation they describe, mutable audit
history, or unverifiable checksums are findings when reachable.

## 3. Primary Scope

Start with these files and expand only as needed:

- `backend/app/services/audit_trail_service.py`
- `backend/app/api/dependencies/audit.py`
- `backend/app/api/routes/audit.py`
- `backend/app/models/audit.py`
- `backend/app/schemas/audit.py`
- `backend/app/core/config.py`
- `backend/app/core/database.py`
- `backend/app/core/auth.py`
- `backend/app/core/metrics.py`
- `backend/alembic/versions/015_phase7_audit_events_table.py`
- `backend/alembic/versions/028_reconciliation_run.py`
- `backend/app/models/reconciliation_run.py`
- API routes that mutate institutional state:
  - First derive the current mutating route set with a repo-wide route search,
    for example `rg -n "@router\.(post|put|patch|delete)" backend/app/api/routes`.
    The list below is a starting scope, not permission to ignore other mutating
    routes discovered by that search.
  - `backend/app/api/routes/orders.py`
  - `backend/app/api/routes/deals.py`
  - `backend/app/api/routes/counterparties.py`
  - `backend/app/api/routes/contracts.py`
  - `backend/app/api/routes/linkages.py`
  - `backend/app/api/routes/rfqs.py`
  - `backend/app/api/routes/cashflow.py`
  - `backend/app/api/routes/cashflow_ledger.py`
  - `backend/app/api/routes/pl.py`
  - `backend/app/api/routes/mtm.py`
  - `backend/app/api/routes/exposures.py`
  - `backend/app/api/routes/scenario.py`
  - `backend/app/api/routes/webhooks.py`
  - `backend/app/api/routes/finance_pipeline.py`
  - `backend/app/api/routes/westmetall.py`
- Background and service mutation paths:
  - `backend/app/services/rfq_orchestrator.py`
  - `backend/app/services/rfq_service.py`
  - `backend/app/services/cashflow_ledger_service.py`
  - `backend/app/services/scenario_whatif_service.py`
  - `backend/app/services/exposure_engine.py`
  - `backend/app/tasks/rfq_timeout_task.py`
- Durable evidence models from prior phases:
  - `backend/app/models/rfqs.py`
  - `backend/app/models/inbound_webhook_delivery.py`
  - `backend/app/models/inbound_webhook_message.py`
  - `backend/app/models/llm_decision_artifact.py`
  - `backend/app/models/cashflow.py`
  - `backend/app/models/pl.py`
  - `backend/app/models/mtm.py`
- Tests under:
  - `backend/tests/test_audit_*.py`
  - `backend/tests/test_auth_role_isolation.py`
  - `backend/tests/test_reconciliation_run.py`
  - focused tests for any route or service implicated by a suspected finding.

Do not accept test presence as proof if production code does not enforce the
audit invariant.

## 4. Audit Questions

Answer these questions explicitly. A negative answer is not automatically a
finding; it becomes a finding only if it creates a concrete correctness,
auditability, determinism, or reconstruction failure.

### Q1 - Mutation Coverage

Can every institutional mutation be tied to durable evidence?

Audit HTTP routes and background/service paths. Identify any mutation that can
create, update, delete, archive, settle, rank, award, reject, submit, reconcile,
or persist financial state without either a signed `AuditEvent` or a more
specific durable evidence artifact.

### Q2 - Audit/Mutation Atomicity

Are audit events committed atomically with the mutation they describe?

Check `audit_event`, `mark_audit_success`, `request.state.audit_commit()`, and
service-level commit boundaries. A mutation must not commit if required audit
evidence cannot be written and signed. An audit row must not claim success for a
mutation that rolled back.

### Q3 - Signature and Key Fail-Closed Behavior

Does audit signing fail closed in every environment that can expose mutation
routes?

Inspect `AUDIT_SIGNING_KEY` validation, `_get_signing_key`, caching, test/local
bypasses, and startup/runtime behavior. Missing or weak keys must not silently
produce unsigned audit rows in production-like deployments.

### Q4 - Checksum Determinism and Verifiability

Is the audit checksum deterministic and independently verifiable?

Inspect canonical serialization, payload ordering, datetime/Decimal/UUID/enum
handling, and `verify_signature`. A verifier must be able to recompute the same
checksum from stored row data without hidden process state.

### Q5 - Append-Only Enforcement

Are audit events immutable at the database layer?

Inspect SQLite and PostgreSQL migration behavior. Verify triggers or constraints
prevent UPDATE and DELETE. Do not accept ORM-only immutability as sufficient for
institutional audit history.

### Q6 - Reconstruction Sufficiency

Do audit rows contain enough before/after context to reconstruct what changed?

Check entity id, entity type, event type, user identity, payload detail, source
request/context, and links to domain-specific evidence. A signed event that only
says "updated" without enough reconstructive payload may be insufficient.

### Q7 - Idempotency and Duplicate Audit Events

Can retries or duplicate submissions create duplicate audit rows, conflicting
rows, or a false success trail?

Inspect idempotency handling in `AuditTrailService.record`, event IDs, route
dependencies, webhook replay paths, RFQ retries, and settlement/reconciliation
jobs.

### Q8 - Authorization and Audit Read Surface

Are audit read and verify endpoints restricted appropriately and deterministic?

Check `/audit/events`, `/audit/events/{id}/verify`, cursor/pagination behavior,
filters, ordering, and role checks. Auditors should be able to inspect evidence;
non-auditors should not receive inappropriate audit payloads.

### Q9 - Cross-Artifact Consistency

Do specialized evidence tables remain consistent with signed audit events?

Compare `RFQStateEvent`, `RFQInvitation`, inbound webhook delivery/message rows,
LLM decision artifacts, cashflow ledger entries, reconciliation runs, MTM/P&L
snapshots, and `AuditEvent`. Missing linkage between specialized evidence and
signed audit trail is a finding only if it prevents reconstruction or violates
"no mutation without evidence."

### Q10 - Migration and Dialect Portability

Do migrations enforce audit/governance invariants consistently across SQLite
tests and PostgreSQL production?

Inspect CHECK constraints, triggers, FK restrictions, downgrade behavior,
JSON/JSONB portability, UUID types, version ID length, and test coverage.

## 5. Severity Taxonomy

Use this taxonomy:

- **Tier 1 / Blocking:** A concrete path can mutate institutional state without
  required evidence; commit a mutation when audit signing/persistence failed;
  alter/delete audit history; create unverifiable signatures/checksums; or make
  a closed A1-A4 decision unreconstructible.
- **Tier 2 / High:** A real edge case can impair auditability, retry semantics,
  verification, evidence linkage, or operator diagnosis, but does not by itself
  commit incorrect economic state under normal flow.
- **Tier 3 / Medium:** A localized robustness or coverage gap with plausible
  operational impact but no immediate institutional invariant breach.
- **Tier 4 / Low:** Documentation, test, or observability improvement only. Do
  not include Tier 4 unless it protects a concrete A5 boundary.

When uncertain between two severities, choose the lower severity and explain the
missing evidence that would make it higher.

## 6. Finding Format

Write findings in this format:

```markdown
## Finding J-A5-GPT54-XX - Short imperative title

**Severity:** Tier N / Blocking|High|Medium|Low
**Status:** Open
**Evidence:**
- `path/to/file.py:123` - what the code does
- `path/to/test.py:456` - relevant test gap or assertion, if any

**Failure mode:**
Describe the concrete sequence that breaks correctness, auditability,
determinism, or reconstruction.

**Governance impact:**
Name the exact governance clause or institutional invariant.

**Recommended remediation boundary:**
State the smallest acceptable fix boundary. Do not prescribe broad refactors.
```

After findings, include:

- `Anti-findings considered` - issues you inspected and rejected, with evidence.
- `Cross-phase deferrals` - items that belong to A6 or a later cross-phase
  cleanup.
- `Recommended remediation waves` - group accepted findings into coherent PR
  waves, preserving small blast radius.

## 7. Anti-Finding Rules

Do not report:

- Merely missing comments.
- Pure naming or formatting concerns.
- A refactor preference with no concrete failure mode.
- Test gaps when production code already hard-fails correctly and the gap does
  not protect an institutional boundary.
- A1-A4 issues unless current audit/governance code reintroduces or fails to
  evidence a closed invariant.
- "There should be more audit logging" as a generic finding. Tie every audit
  finding to a missing mutation evidence boundary, unverifiable signature,
  non-atomic write, mutable history, or reconstruction failure.

## 8. Required Workflow

1. Read `docs/governance.md`.
2. Inspect the primary scope files.
3. Inspect migrations and tests relevant to any suspected finding.
4. Validate each finding against current code, not memory or prior PR summaries.
5. Write the report to `docs/audits/2026-05-11-phase-a5-findings-gpt54.md`.
6. Do not edit anything else.
