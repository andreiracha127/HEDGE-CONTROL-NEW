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
- Narrow service return-shape changes are allowed when they are required to
  expose durable identities for audit emission. This is not permission for a
  broad refactor.
  Specifically:
  `ingest_westmetall_cash_settlement_daily_for_date()` and
  `ingest_westmetall_cash_settlement_bulk()` may change return shape only;
  `FinancePipelineService.run_daily_pipeline()` already returns
  `FinancePipelineRun` and needs no return-shape change; and
  `AuditTrailService.record_worker_event()` is a new method returning
  `AuditEvent`.

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
- `backend/app/services/finance_pipeline_service.py:58`
- `backend/app/services/finance_pipeline_service.py:68`
- `backend/app/services/finance_pipeline_service.py:77`
- `backend/app/services/finance_pipeline_service.py:91`
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

The intended integration point is inside `_auto_create_quote()` after
`RFQService.submit_quote()` and `_add_llm_decision_artifact()` have both
succeeded, but before the existing worker `session.commit()`. The executor must
wire the worker audit method into that same transaction, for example:

```python
quote = RFQService.submit_quote(session, rfq.id, quote_payload)
_add_llm_decision_artifact(..., quote_id=quote.id)
AuditTrailService.record_worker_event(
    session,
    entity_type="rfq_quote",
    entity_id=quote.id,
    event_type="rfq.auto_quote_created",
    actor="rfq_orchestrator",
    source="inbound_webhook_worker",
    metadata={
        "rfq_id": str(rfq.id),
        "message_id": msg.message_id,
        "llm_decision_status": "auto_quote_created",
    },
)
session.commit()
```

The call site must be before commit so audit failure rolls back the quote, RFQ
state changes, durable message linkage/status, and LLM decision artifact
together.

## 4. Required Implementation Boundary

### Route Coverage

Add signed audit coverage for:

- counterparty create/update/delete;
- SO-PO link creation;
- manual finance pipeline run trigger;
- single-date Westmetall ingest;
- bulk Westmetall ingest.

Uniform HTTP route pattern for the newly covered routes:

- declare the route-level `audit_event()` dependency with the correct
  `entity_type` and `event_type`;
- retain `request` in the route signature/body;
- perform the mutation under the same fail-closed transaction boundary used for
  audit emission;
- call `mark_audit_success(request, entity_id)` after the mutation returns the
  durable identity and before route-level audit commit;
- use `Counterparty.id` for counterparty create/update/delete, `SoPoLink.id`
  for SO-PO link creation, and `FinancePipelineRun.id` returned by
  `FinancePipelineService.run_daily_pipeline()` for manual finance pipeline
  trigger;
- prove rollback on audit signing failure for each newly covered route family.

Westmetall routes already declare `audit_event` but delete `request` and never
call `mark_audit_success()`. Fix the no-op audit coverage; do not leave a
dependency that never emits an event.

For Westmetall, "fix the no-op audit coverage" has a specific meaning:

- remove the existing `del request` statement and retain the `request` object;
- first extend both Westmetall ingest service return contracts narrowly:
  - single-date ingest must return the inserted `CashSettlementPrice.id` when a
    row is created;
  - bulk ingest must return the inserted `CashSettlementPrice.id` values and a
    deterministic batch UUID derived from immutable ingest evidence (`source`,
    date range, `html_sha256`, and inserted settlement dates);
- required daily return contract:
  `tuple[uuid.UUID | None, int, int, WestmetallFetchEvidence]`, ordered as
  `(inserted_id, ingested_count, skipped_count, evidence)`, with `inserted_id`
  set to `None` when no row is created;
- required bulk return contract:
  `tuple[list[uuid.UUID], uuid.UUID, int, int, WestmetallFetchEvidence]`,
  ordered as
  `(inserted_ids, batch_uuid, ingested_count, skipped_count, evidence)`;
- compute `batch_uuid` deterministically with a canonical function such as
  `uuid.uuid5(uuid.NAMESPACE_URL, canonical_batch_key)`, where
  `canonical_batch_key` includes source, requested date range, `html_sha256`,
  and the sorted inserted settlement dates;
- after the service returns durable identities, the HTTP route must call
  `mark_audit_success(request, entity_id)` after a successful ingest operation;
- for single-date ingest, use the inserted `CashSettlementPrice.id` as
  `entity_id`;
- for bulk ingest, use the deterministic batch UUID as `entity_id` and include
  the inserted `CashSettlementPrice.id` list in the audit payload/metadata;
- when Westmetall ingest skips all rows and creates no mutation, do not mark a
  successful mutation audit event; tests must distinguish skip/no-op from
  mutation success;
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

Create this non-HTTP API in `backend/app/services/audit_trail_service.py` as a
new `AuditTrailService.record_worker_event()` method in this wave. This method
must be a small wrapper around the existing `AuditTrailService.record()` path,
not a parallel signing implementation. Required signature:

```python
@staticmethod
def record_worker_event(
    session: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    event_type: str,
    actor: str,
    source: str,
    metadata: dict | None = None,
) -> AuditEvent
```

The implementation must add this concrete method unless the executor finds an
existing non-HTTP audit helper with the same semantics. It must write a signed
`AuditEvent` into the provided session, use deterministic payload/checksum
rules from the current audit trail service, and rely on the caller's existing
transaction to commit or roll back atomically with the worker mutation.
It must be generic: callers provide `actor` and `source`; the method must not
invent them. In this wave, the required call site is RFQ auto-quote only.
Future background workers may reuse the method only if they pass explicit,
caller-owned actor/source metadata.
Do not expose a `commit` parameter on `record_worker_event()` in this wave; the
method must always call `AuditTrailService.record(..., commit=False)` so the
worker's existing transaction remains the only commit boundary.

Minimum skeleton:

```python
payload = {
    "actor": actor,
    "source": source,
    "metadata": metadata or {},
}
payload_raw, payload_obj = normalize_payload_raw(payload)
return AuditTrailService.record(
    session,
    event_id=uuid.uuid4(),
    event_type=event_type,
    entity_type=entity_type,
    entity_id=entity_id,
    payload_raw=payload_raw,
    payload_obj=payload_obj,
    commit=False,
)
```

The skeleton is illustrative. The final implementation must align with the
post-PR-A5-1 checksum canonicalization path if PR-A5-1 has already landed. Call
`normalize_payload_raw()` as the module-level helper in
`audit_trail_service.py` before invoking `AuditTrailService.record()`.

## 5. Acceptance Criteria

- Counterparty create/update/delete produce signed audit rows.
- Counterparty create/update/delete roll back when audit signing fails.
- SO-PO link creation produces a signed audit row.
- SO-PO link creation rolls back when audit signing fails.
- Finance pipeline manual run produces a signed audit row for the operator
  trigger and durable pipeline run identity.
- Finance pipeline manual run rolls back when audit signing fails.
- Single and bulk Westmetall ingest produce signed audit rows when rows are
  created or updated, explicitly re-wiring the existing-but-inert dependency.
- Single and bulk Westmetall ingest roll back when audit signing fails.
- Westmetall no-op audit dependency is eliminated: the `request` object is
  retained and `mark_audit_success()` is called with the durable entity id.
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
- worker `MissingAuditSigningKey` from `record_worker_event()` prevents the
  enclosing worker `session.commit()` and rolls back quote, RFQ state changes,
  durable message linkage/status, and LLM decision artifact.

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
