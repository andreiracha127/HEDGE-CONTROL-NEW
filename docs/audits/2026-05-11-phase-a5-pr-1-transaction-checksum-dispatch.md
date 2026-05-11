# Phase A5 Remediation Dispatch - PR-A5-1 Transaction Boundary and Checksum Reconstruction

**Phase:** A5 - Audit trail, governance enforcement, and cross-cutting reconstruction  
**Wave:** PR-A5-1  
**Authoring date:** 2026-05-11  
**Repository:** `D:/Projetos/Hedge-Control-New`  
**Base branch:** `main`  
**Required branch:** `audit-a5/transaction-checksum-reconstruction`  
**Source verdict:** `docs/audits/2026-05-11-phase-a5-jury-verdict.md`

## 1. Objective

Close:

- `J-A5-01` - Make audit emission atomic with covered institutional mutations.
- `J-A5-02` - Persist and verify a reconstructible audit checksum input.

This wave hardens the routes that already declare audit coverage and the audit
checksum/signature model. It must make covered institutional mutations fail
closed when audit evidence cannot be written, and it must make audit signatures
independently reconstructible from persisted audit data.

## 2. Non-Negotiable Constraints

- Do not edit `docs/governance.md`.
- Do not implement PR-A5-2 or PR-A5-3 findings in this wave.
- Do not add best-effort audit logging.
- Do not suppress audit failures.
- Do not fabricate audit payloads after the mutation commits.
- Do not make `/audit/events/{id}/verify` validate only checksum/signature
  self-consistency; it must validate payload-to-checksum-to-signature.
- Preserve existing economic behavior except where commit boundaries must move
  to satisfy atomicity.

Hard-fail is the institutional rule: if required audit evidence cannot be
signed and persisted, the domain mutation must not become durable.

## 3. Findings and Evidence

### J-A5-01 - Atomic audit emission

The jury accepted that covered routes commit mutations before signed audit rows
are persisted. Evidence includes:

- `backend/app/api/routes/orders.py:38`
- `backend/app/services/order_service.py:231`
- `backend/app/api/routes/orders.py:133`
- `backend/app/services/order_service.py:106`
- `backend/app/api/routes/rfqs.py:111`
- `backend/app/api/routes/rfqs.py:268`
- `backend/app/api/routes/rfqs.py:320`
- `backend/app/api/routes/rfqs.py:376`
- `backend/app/api/routes/rfqs.py:344`
- `backend/app/api/routes/rfqs.py:402`
- `backend/app/api/routes/rfqs.py:424`
- `backend/app/api/routes/rfqs.py:446`
- `backend/app/api/routes/rfqs.py:468`
- `backend/app/api/routes/mtm.py:65`
- `backend/app/services/mtm_snapshot_service.py:110`
- `backend/app/api/routes/pl.py:49`
- `backend/app/services/pl_snapshot_service.py:105`
- `backend/app/api/routes/cashflow.py:55`
- `backend/app/services/cashflow_baseline_service.py:268`
- `backend/app/api/routes/cashflow_ledger.py:46`
- `backend/app/services/cashflow_ledger_service.py:290`
- Safe local pattern: `backend/app/api/dependencies/uow.py:19` through
  `backend/app/api/dependencies/uow.py:26`.

### J-A5-02 - Reconstructible checksum input

The jury accepted that the audit checksum is derived from raw request text while
only parsed JSON is persisted, preventing independent recomputation from stored
data. Evidence includes:

- `backend/app/api/dependencies/audit.py:35`
- `backend/app/api/dependencies/audit.py:36`
- `backend/app/api/dependencies/audit.py:37`
- `backend/app/api/dependencies/audit.py:57`
- `backend/app/api/dependencies/audit.py:58`
- `backend/app/services/audit_trail_service.py:89`
- `backend/app/services/audit_trail_service.py:105`
- `backend/app/models/audit.py:22`
- `backend/app/api/routes/audit.py:79`
- Existing helper: `backend/app/services/audit_trail_service.py:156`.

## 4. Required Implementation Boundary

### Transaction Boundary

Bring these already-covered mutation paths under a single atomic boundary:

- order create/archive paths that already declare audit coverage;
- all RFQ routes that already declare `audit_event` and currently commit before
  `request.state.audit_commit()`, including create, quote submit, RFQ reject,
  cancel, quote reject, refresh-counterparty, refresh, award, and archive;
- MTM snapshot creation;
- P&L snapshot creation;
- cashflow baseline snapshot creation;
- cashflow ledger settlement ingestion.

Acceptable patterns:

- use `unit_of_work(session, request=request)` where route structure supports it;
- or introduce an equivalent explicit single-commit pattern that flushes domain
  rows, records the signed `AuditEvent`, and commits once.

The implementation must remove or neutralize intermediate commits in the touched
audit-critical service flows. A route must not call a service that commits the
domain mutation and only then attempts to emit audit evidence.

### Checksum Reconstruction

Make the audit checksum input reconstructible from persisted audit data.

Minimum acceptable behavior:

- canonicalize payload before hashing;
- persist the exact canonical representation or a deterministic equivalent
  sufficient to recompute the checksum;
- compute checksum from that canonical representation;
- compute HMAC from the checksum;
- make `/audit/events/{id}/verify` recompute checksum from persisted payload
  data before validating the HMAC;
- make payload tampering, checksum tampering, and signature tampering fail
  verification.

If schema changes are required, add an Alembic migration with a revision id no
longer than 32 characters.

## 5. Acceptance Criteria

- Missing or invalid `AUDIT_SIGNING_KEY` rolls back each covered mutation in
  this wave.
- A process failure or exception during audit emission cannot leave a covered
  mutation committed without its signed audit event.
- Services touched by this wave no longer commit before required route-level
  audit emission.
- `/audit/events/{id}/verify` fails when persisted payload and stored checksum
  diverge.
- `/audit/events/{id}/verify` fails when checksum and signature diverge.
- Existing valid audit rows verify successfully after the new canonicalization
  path.
- Tests prove that semantically identical JSON with different whitespace/key
  ordering produces deterministic canonical checksum behavior.
- `docs/governance.md` has no diff.

## 6. Required Tests

Add or update focused tests under `backend/tests/`.

Minimum test coverage:

- order create/archive rollback when audit signing fails;
- RFQ create, quote submit, RFQ reject, cancel, quote reject,
  refresh-counterparty, refresh, award, and archive rollback when audit signing
  fails;
- MTM/P&L/cashflow baseline/settlement rollback when audit signing fails;
- checksum recomputation from persisted data succeeds for valid rows;
- payload tamper fails verification;
- checksum tamper fails verification;
- signature tamper fails verification;
- canonical JSON behavior is deterministic across key order/whitespace variants.

Do not rely only on static tests. At least one behavioral test per mutation
family must prove database state is not durable when audit emission fails.

## 7. Required Verification

Run, at minimum:

```bash
python -m pytest backend/tests/test_audit_signature.py -q
python -m pytest backend/tests/test_audit_economic_mutations.py -q
python -m pytest backend/tests/test_audit_query_filters.py -q
python -m pytest backend/tests/test_rfq_orchestrator.py -q
python -m pytest backend/tests/test_cashflow_ledger_service.py -q
python -m alembic heads
git diff --check
```

Also run this review command and report the remaining matches with adjudication:

```bash
rg -n "session\.commit\(|db\.commit\(" backend/app/api backend/app/services
```

If full backend is run and `backend/tests/test_ws.py` fails locally on Python
3.14 with the known `asyncio.get_event_loop()` issue, report it separately and
do not treat it as evidence against this wave.

## 8. Out of Scope

- Adding audit coverage to routes that currently lack audit dependencies
  entirely. That is PR-A5-2.
- Worker/non-HTTP audit API. That is PR-A5-2.
- Migration downgrade guardrails. That is PR-A5-3.
- Auth startup validation. That is PR-A5-3.
- Frontend audit UX. Deferred outside A5 remediation.

## 9. PR Requirements

- Use branch `audit-a5/transaction-checksum-reconstruction`.
- Push normally; do not use `--no-verify`.
- Open a PR against `main`.
- Include in the PR body:
  - findings closed;
  - files changed;
  - tests run and results;
  - Alembic head if migration is added;
  - `rg` commit-boundary review result;
  - hook artifact path;
  - statement that `docs/governance.md` has no diff.
