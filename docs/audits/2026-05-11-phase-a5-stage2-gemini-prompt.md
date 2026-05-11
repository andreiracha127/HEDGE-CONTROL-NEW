# Phase A5 - Stage 2 Audit Dispatch - Auditor B

**Phase:** A5 - Audit trail, governance enforcement, and cross-cutting reconstruction  
**Stage:** 2 of 3  
**Target auditor:** Gemini 3.1 Pro  
**Authoring date:** 2026-05-11  
**Repository:** `D:/Projetos/Hedge-Control-New`  
**Branch:** `main`  
**Expected output:** `docs/audits/2026-05-11-phase-a5-findings-gemini.md`

## 1. Operating Instructions

You are performing an independent read-only institutional audit. Do not edit
code, migrations, tests, generated schemas, or governance documents.

GPT 5.4 is performing Stage 1 separately. GPT 5.5 will adjudicate in Stage 3.
Do not rely on either of them. Your value is independent verification, different
failure modeling, and catching issues a first auditor may normalize.

Use direct code evidence. Every accepted finding must include file and line
references, a concrete failure mode, and the institutional rule it violates. Do
not report style issues, naming preferences, hypothetical rewrites, or refactors
without a demonstrated correctness, auditability, determinism, or reconstruction
impact.

## 2. Institutional Context

Closed phases:

- A1 closed economic primitives.
- A2 closed RFQ lifecycle, deterministic ranking, award, and outbound evidence.
- A3 closed valuation, MTM, cashflow baseline/ledger reconciliation, and P&L
  lifecycle.
- A4 closed integration trust, inbound raw durability, replay protection, and
  LLM decision reconstruction.

Phase A5 is the governance layer over the system. It asks whether the platform
can prove what happened after the fact, whether required evidence is signed and
immutable, and whether audit failure prevents mutation rather than becoming a
best-effort side effect.

Binding governance is `docs/governance.md`. The most relevant rules are:

- auditability and reconstructability are primary optimization targets;
- messages are evidence, not UI artifacts;
- evidence missing is hard-fail;
- contracts cannot be unreconstructible;
- no silent fallback;
- no mutation without evidence;
- one phase at a time, no future-phase preemption.

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
- `backend/alembic/versions/015_phase7_audit_events_table.py`
- Derive the current mutating route set with a repo-wide route search, for
  example `rg -n "@router\.(post|put|patch|delete)" backend/app/api/routes`.
  The route list below is a starting scope, not permission to ignore other
  mutating routes discovered by that search.
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
- `backend/app/services/rfq_service.py`
- `backend/app/services/rfq_orchestrator.py`
- `backend/app/services/cashflow_ledger_service.py`
- `backend/app/services/exposure_engine.py`
- `backend/app/tasks/rfq_timeout_task.py`
- `backend/app/models/rfqs.py`
- `backend/app/models/inbound_webhook_delivery.py`
- `backend/app/models/inbound_webhook_message.py`
- `backend/app/models/llm_decision_artifact.py`
- `backend/app/models/cashflow.py`
- `backend/app/models/reconciliation_run.py`
- audit and route tests under `backend/tests/`.

Do not ignore tests, but do not accept test presence as proof if production code
does not enforce the invariant.

## 4. Audit Questions

### Q1 - Audit Dependency Correctness

Do route-level audit dependencies capture the right entity type, event type,
entity id, user, payload, and success/failure boundary?

Look for routes where `audit_event()` is registered but `mark_audit_success()`
is missing, late, anchored to the wrong entity, or called after a partial
mutation.

### Q2 - Fail-Closed Audit Emission

Can a mutation succeed when audit signing, audit persistence, or audit commit
fails?

Inspect exception paths, `request.state.audit_commit()`, service commits, and
background workers. Audit failures must not be swallowed.

### Q3 - Commit Boundary and Transaction Ownership

Are domain mutations and audit rows in the same transaction boundary?

Identify any route or service that commits internally before audit evidence is
written, especially service helpers used by HTTP routes, background tasks, RFQ
orchestration, settlement, reconciliation, and scenario/cashflow endpoints.

### Q4 - Audit Event Immutability

Can an audit row be updated or deleted through ORM, raw SQL, migration downgrade,
test helper, or production code?

Check database triggers for SQLite and PostgreSQL. Verify production and test
dialects both protect append-only history.

### Q5 - Signature Reconstruction

Can an auditor recompute the checksum and HMAC from stored row data alone?

Check canonical JSON serialization, byte/string handling, payload normalization,
timezones, UUIDs, Decimals, enums, and whether verification depends on mutable
code defaults or omitted fields.

### Q6 - Query and Verification Surface

Are audit read endpoints complete and safe?

Check role enforcement, pagination, ordering, filters, cursor stability, verify
endpoint behavior for unsigned events, missing keys, tampered rows, and
nonexistent rows.

### Q7 - Specialized Evidence Versus Generic Audit Events

Where specialized evidence exists, is it enough without a generic audit event?

Review RFQ state events, RFQ invitations, inbound deliveries, inbound messages,
LLM decision artifacts, settlement events, cashflow ledger entries,
reconciliation runs, MTM/P&L snapshots, and scenario outputs. Report only when
the evidence boundary is insufficient or unlinked for reconstruction.

### Q8 - Background Mutations

Do scheduled/background processes mutate institutional state without the same
evidence discipline as HTTP routes?

Inspect RFQ timeout tasks, inbound queue processing, LLM auto-quote creation,
webhook processing, finance/market data ingestion, and any service method that
calls `session.commit()` outside route audit dependencies.

### Q9 - Governance Enforcement at Startup

Are required governance secrets and safety settings validated before the app can
serve mutation routes?

Check audit signing key, webhook secrets, app environment, and any setting that
switches from hard-fail to bypass. A database URL or test fixture must not be a
production authorization policy.

### Q10 - Audit Schema Evolution

Can migrations preserve audit history and verification over time?

Inspect migration revision ordering, downgrade behavior, trigger portability,
nullable columns, backfill strategy, and whether schema changes make historical
audit rows unverifiable.

## 5. Severity Taxonomy

Use this taxonomy:

- **Tier 1 / Blocking:** A concrete path can mutate institutional state without
  durable evidence; commit after audit/signature failure; mutate/delete audit
  history; make a signed event unverifiable; or break reconstruction of a closed
  A1-A4 decision.
- **Tier 2 / High:** A real edge case can impair auditability, retry semantics,
  verification, or evidence linkage, but does not by itself create incorrect
  economic state under normal flow.
- **Tier 3 / Medium:** A localized robustness or coverage gap with plausible
  operational impact but no immediate institutional invariant breach.
- **Tier 4 / Low:** Documentation, test, or observability improvement only. Do
  not include Tier 4 unless it protects a concrete A5 boundary.

When uncertain between two severities, choose the lower severity and explain the
missing evidence that would make it higher.

## 6. Finding Format

Write findings in this format:

```markdown
## Finding J-A5-GEMINI-XX - Short imperative title

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

- Missing comments or formatting.
- Generic "more logging" recommendations.
- Test gaps that do not protect a real audit boundary.
- A1-A4 domain issues unless the audit/governance layer fails to evidence them.
- A frontend-only concern; that belongs to A6 unless it exposes or corrupts
  audit evidence.
- The mere existence of specialized evidence instead of `AuditEvent`; report
  only if reconstruction, signature, immutability, or linkage is insufficient.

## 8. Required Workflow

1. Read `docs/governance.md`.
2. Inspect the primary scope files.
3. Inspect migrations and tests relevant to any suspected finding.
4. Validate each finding against current code, not memory or prior PR summaries.
5. Write the report to `docs/audits/2026-05-11-phase-a5-findings-gemini.md`.
6. Do not edit anything else.
