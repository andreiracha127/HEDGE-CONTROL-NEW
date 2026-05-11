# Phase A5 Remediation Dispatch - PR-A5-2 Route Coverage and Worker Audit Envelope

**Phase:** A5 - Audit trail, governance enforcement, and cross-cutting reconstruction  
**Wave:** PR-A5-2  
**Authoring date:** 2026-05-11  
**Repository:** `D:/Projetos/Hedge-Control-New`  
**Base branch:** `main`  
**Required branch:** `audit-a5/route-worker-audit-coverage`  
**Source verdict:** `docs/audits/2026-05-11-phase-a5-jury-verdict.md`

## 1. Objective

Close:

- `J-A5-03` - Add signed audit coverage to uncovered and no-op-covered mutation
  routes.
- `J-A5-05` - Give background RFQ auto-quote mutations the same signed audit
  envelope.

This wave covers mutating paths that either lack signed audit coverage entirely
or cannot use the HTTP audit dependency because they execute in a background
worker.

## 2. Non-Negotiable Constraints

- Do not edit `docs/governance.md`.
- Do not implement PR-A5-1 or PR-A5-3 findings in this wave except as needed to
  integrate with already-merged code.
- Do not fabricate a synthetic HTTP request for worker audit emission.
- Do not mark audit success without a durable institutional mutation.
- Do not accept route dependency presence as proof; behavioral tests must show
  an audit row is created.
- Do not broaden the worker change into generic workflow refactoring.

Signed audit evidence must be actor/source-bound and committed atomically with
the mutation it describes.

## 3. Findings and Evidence

### J-A5-03 - Missing and no-op route coverage

The jury accepted that these mutating routes are uncovered or no-op-covered:

- `backend/app/api/routes/counterparties.py:21`
- `backend/app/services/counterparty_service.py:38`
- `backend/app/api/routes/counterparties.py:81`
- `backend/app/services/counterparty_service.py:81`
- `backend/app/api/routes/counterparties.py:106`
- `backend/app/services/counterparty_service.py:86`
- `backend/app/api/routes/orders.py:89`
- `backend/app/services/order_service.py:148`
- `backend/app/api/routes/finance_pipeline.py:23`
- `backend/app/services/finance_pipeline_service.py:77`
- `backend/app/services/finance_pipeline_service.py:107`
- `backend/app/api/routes/westmetall.py:115`
- `backend/app/api/routes/westmetall.py:133`
- `backend/app/services/cash_settlement_prices.py:50`
- `backend/app/api/routes/westmetall.py:161`
- `backend/app/api/routes/westmetall.py:179`
- `backend/app/services/cash_settlement_prices.py:96`
- `backend/app/services/cash_settlement_prices.py:110`
- static coverage gap: `backend/tests/test_audit_economic_mutations.py:398`.

### J-A5-05 - Worker audit envelope

The jury accepted that RFQ auto-quote worker mutation has durable specialized
evidence but no generic signed `AuditEvent` envelope:

- `backend/app/services/rfq_orchestrator.py:717`
- `backend/app/services/rfq_orchestrator.py:743`
- `backend/app/services/rfq_orchestrator.py:785`
- `backend/app/services/rfq_orchestrator.py:815`
- `backend/app/services/rfq_orchestrator.py:1410`
- `backend/app/services/rfq_orchestrator.py:1551`
- `backend/app/services/rfq_orchestrator.py:1564`
- `backend/app/services/rfq_orchestrator.py:1585`
- `backend/app/models/llm_decision_artifact.py:20`.

## 4. Required Implementation Boundary

### Route Coverage

Add signed audit coverage for:

- counterparty create/update/delete;
- SO-PO link creation;
- manual finance pipeline run trigger;
- single-date Westmetall ingest;
- bulk Westmetall ingest.

Westmetall routes already declare `audit_event` but delete `request` and never
call `mark_audit_success()`. Fix the no-op audit coverage; do not leave a
dependency that never emits an event.

For Westmetall, "fix the no-op audit coverage" has a specific meaning:

- retain the `request` object instead of deleting it;
- call `mark_audit_success(request, entity_id)` after a successful ingest
  operation;
- extract `entity_id` from persisted ingest output: the created/updated
  `CashSettlementPrice` row id for single-date ingest; and for bulk ingest a
  deterministic durable batch/run identity, or an explicit persisted
  list/linkage of created/updated `CashSettlementPrice` row ids;
- if the current service response only exposes counts, extend the service or
  route result enough to expose the durable identity required for
  `mark_audit_success()`;
- persist the audit row atomically with the ingest mutation;
- verify with behavioral tests that the audit row is actually durable and
  queryable.

Merely declaring `audit_event` on the route is not a fix.
Do not use the worker audit envelope for Westmetall. Westmetall routes are HTTP
routes and must use the standard route-level `audit_event` plus
`mark_audit_success()` pattern.

Route inventory must be derived from the actual repo state, not a manual
six-route whitelist:

```bash
rg -n "@router\.(post|put|patch|delete)" backend/app/api/routes
```

Every route in the resulting inventory must be classified as one of:

- covered institutional mutation;
- non-mutating command/query with evidence;
- explicitly out of A5 mutation scope, with reason.

For routes newly covered in this wave, adding `audit_event()` is not sufficient.
The route must also be wired so the institutional mutation and signed audit row
share one fail-closed transaction boundary. A missing signing key, audit
persistence error, or audit signing failure must roll back the newly covered
mutation.

### Worker Audit Envelope

Introduce a worker-safe signed audit API for non-HTTP mutations.

Minimum acceptable behavior:

- records a signed `AuditEvent` without requiring a `Request` object;
- includes explicit actor/source metadata for the worker path;
- links to the RFQ, quote, durable inbound message, and `LLMDecisionArtifact`
  where available;
- commits in the same transaction as the quote, RFQ state event, durable message
  status/linkage, and decision artifact;
- fails closed if audit signing or persistence fails.

Do not duplicate the HTTP dependency by constructing fake request state. The
background path should have an explicit service-level API.

The worker audit API must have an explicit callable surface comparable to:

```python
record_worker_audit(
    session: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    event_type: str,
    actor: str,
    source: str,
    metadata: dict | None = None,
) -> None
```

The exact name may differ, but the semantics may not: it writes a signed
`AuditEvent` into the provided session, uses deterministic payload/checksum
rules from the current audit trail service, and relies on the caller's existing
transaction to commit or roll back atomically with the worker mutation.

## 5. Acceptance Criteria

- Counterparty create/update/delete produce signed audit rows.
- Counterparty create/update/delete roll back when audit signing fails.
- SO-PO link creation produces a signed audit row.
- SO-PO link creation rolls back when audit signing fails.
- Finance pipeline manual run produces a signed audit row for the operator
  trigger and durable pipeline run identity.
- Finance pipeline manual run rolls back when audit signing fails.
- Single and bulk Westmetall ingest produce signed audit rows when rows are
  created or updated.
- Single and bulk Westmetall ingest roll back when audit signing fails.
- Westmetall no-op audit dependency is eliminated.
- RFQ worker auto-quote creates a signed audit row atomically with quote,
  durable inbound message linkage/status, and `LLMDecisionArtifact`.
- If worker audit signing fails, the auto-quote mutation is not durable.
- The repo-wide route coverage test is derived from
  `@router.(post|put|patch|delete)` inventory and cannot silently miss newly
  added mutating routes.
- `docs/governance.md` has no diff.

## 6. Required Tests

Add or update focused tests under `backend/tests/`.

Minimum test coverage:

- counterparty create/update/delete audit rows;
- counterparty create/update/delete rollback when audit signing fails;
- SO-PO link audit row;
- SO-PO link rollback when audit signing fails;
- finance pipeline trigger audit row;
- finance pipeline trigger rollback when audit signing fails;
- Westmetall single-date audit row;
- Westmetall single-date rollback when audit signing fails;
- Westmetall bulk audit row;
- Westmetall bulk rollback when audit signing fails;
- Westmetall declared dependency actually emits on success;
- repo-wide mutating route inventory coverage;
- worker auto-quote audit row with links to RFQ/quote/message/decision artifact;
- worker audit failure rolls back the quote/state mutation.

## 7. Required Verification

Run, at minimum:

```bash
python -m pytest backend/tests/test_audit_economic_mutations.py -q
python -m pytest backend/tests/test_rfq_orchestrator.py -q
python -m pytest backend/tests/test_phase5_whatsapp_llm.py -q
python -m pytest backend/tests/test_inbound_webhook_delivery.py -q
python -m pytest backend/tests/test_webhook_processor.py -q
git diff --check
```

Also run and include the inventory output or summarized classification:

```bash
rg -n "@router\.(post|put|patch|delete)" backend/app/api/routes
```

If full backend is run and `backend/tests/test_ws.py` fails locally on Python
3.14 with the known `asyncio.get_event_loop()` issue, report it separately and
do not treat it as evidence against this wave.

## 8. Out of Scope

- Transaction-boundary refactor for already-covered routes. That is PR-A5-1.
- Checksum canonicalization/reconstruction. That is PR-A5-1.
- Non-destructive migration downgrade. That is PR-A5-3.
- Auth startup validation. That is PR-A5-3.
- Broader market-data governance beyond signed evidence for Westmetall ingest.

## 9. PR Requirements

- Use branch `audit-a5/route-worker-audit-coverage`.
- Push normally; do not use `--no-verify`.
- Open a PR against `main`.
- Include in the PR body:
  - findings closed;
  - files changed;
  - tests run and results;
  - route inventory classification summary;
  - hook artifact path;
  - statement that `docs/governance.md` has no diff.
