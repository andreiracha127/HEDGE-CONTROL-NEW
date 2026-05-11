# Phase A5 - Stage 1 Findings - Auditor A (GPT 5.4)

## Posture
FAIL-WITH-BLOCKERS

## Structured Answers

### Q1 - Mutation Coverage
No. Counterparty create/update/delete, SO-PO link creation, and the finance pipeline trigger mutate durable institutional state without a signed `AuditEvent`. Several other mutation routes do declare `audit_event`, but then commit the mutation before the signed audit row is attempted.

### Q2 - Audit/Mutation Atomicity
No. The atomic `unit_of_work` pattern exists, but it is not applied consistently. Orders, RFQs, MTM snapshots, P&L snapshots, and cashflow baseline snapshots all have reachable paths where the domain mutation commits before `request.state.audit_commit()` runs.

### Q3 - Signature and Key Fail-Closed Behavior
Partially. `AuditTrailService.record()` does fail closed when `AUDIT_SIGNING_KEY` is absent, but that protection is undermined on routes that already committed the mutation before audit emission. Auth fail-closed is also inconsistent because startup gating uses `ENVIRONMENT` while the settings model uses `APP_ENV`.

### Q4 - Checksum Determinism and Verifiability
No. The checksum is derived from the raw request body string, while only the parsed JSON object is stored. `/audit/events/{id}/verify` validates only `HMAC(checksum)` and never recomputes the checksum from persisted row data.

### Q5 - Append-Only Enforcement
Yes at the database layer. Migration `015_phase7_audit_events_table` installs `UPDATE` and `DELETE` rejection triggers for both SQLite and PostgreSQL.

### Q6 - Reconstruction Sufficiency
No. For the uncovered mutation routes there is no signed actor-bound audit row at all. For covered routes, the stored audit payload is not enough to independently re-derive the persisted checksum, which leaves the signed record only partially reconstructible.

### Q7 - Idempotency and Duplicate Audit Events
Partially. `AuditTrailService.record()` rejects duplicate `event_id`s, but several mutation paths commit before audit emission; a caller that retries after a 5xx can face already-persisted state with no signed success trail from the first attempt.

### Q8 - Authorization and Audit Read Surface
No. The audit routes depend on `require_role("auditor")`, but when JWT auth is disabled that dependency becomes a no-op. Because startup validation checks `ENVIRONMENT` while the app settings use `APP_ENV`, production-like deployments can boot with auth disabled and expose audit reads to anonymous callers.

### Q9 - Cross-Artifact Consistency
Partially. Specialized evidence tables for inbound webhooks do preserve durable provider evidence, and RFQ invitation artifacts remain persisted. The cross-artifact picture breaks where signed audit rows are missing altogether or where the signature only proves the stored checksum, not the stored payload.

### Q10 - Migration and Dialect Portability
Mostly yes for append-only enforcement. The A5 portability gap is not in trigger reachability; it is in route/service coverage and verification semantics that sit above the migration layer.

## Findings

## Finding J-A5-GPT54-01 - Collapse pre-audit commits into one transaction

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/api/routes/orders.py:38` - `POST /orders/sales` creates the order before calling `request.state.audit_commit()`.
- `backend/app/services/order_service.py:231` - `_create_order()` commits the order row inside the service.
- `backend/app/api/routes/rfqs.py:111` - `POST /rfqs` commits the RFQ before `mark_audit_success()` and audit emission.
- `backend/app/services/rfq_service.py:645` - RFQ creation checkpoint-commits before the route-level signed audit row exists.
- `backend/app/services/rfq_service.py:1049` - refresh flow commits the queued invitation before the route-level audit row exists.
- `backend/app/services/rfq_service.py:1219` - reject-quote flow commits the quote/RFQ state transition before the route-level audit row exists.
- `backend/app/services/rfq_service.py:1324` - refresh-counterparty commits the new invitation row before the route-level audit row exists.
- `backend/app/api/routes/mtm.py:65` - MTM snapshot route emits audit only after snapshot creation returns.
- `backend/app/services/mtm_snapshot_service.py:110` - MTM snapshot creation commits inside the service.
- `backend/app/api/routes/pl.py:49` - P&L snapshot route emits audit only after snapshot creation returns.
- `backend/app/services/pl_snapshot_service.py:105` - P&L snapshot creation commits inside the service.
- `backend/app/api/routes/cashflow.py:55` - cashflow baseline route emits audit only after snapshot creation returns.
- `backend/app/services/cashflow_baseline_service.py:268` - baseline snapshot creation commits inside the service.
- `backend/tests/test_audit_economic_mutations.py:398` - the static audit coverage test only guards six A1 routes, not these A5-relevant mutation surfaces.

**Failure mode:**
These routes/services persist the business mutation first and only then attempt the signed audit row. If audit signing fails, the audit insert conflicts, or the request dies after the service commit but before `request.state.audit_commit()`, the caller receives a 5xx while the underlying institutional state is already changed. The result is a committed mutation with missing signed evidence, exactly the failure A5 is supposed to prevent.

**Governance impact:**
Violates `docs/governance.md:174-186`, especially "Evidence is missing" and "No mutation without evidence", and breaches the primary optimization targets `docs/governance.md:55-56`.

**Recommended remediation boundary:**
Move these mutation paths onto the existing `unit_of_work` pattern or an equivalent deferred-audit transaction boundary. The minimum acceptable fix is to remove intermediate commits from audit-critical route/service flows and make the signed `AuditEvent` part of the same final database commit as the mutation it describes.

## Finding J-A5-GPT54-02 - Persist a verifiable checksum input and recompute it on verify

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/api/dependencies/audit.py:35` - the dependency captures the raw request body bytes as `payload_text`.
- `backend/app/api/dependencies/audit.py:57` - `AuditTrailService.record()` receives that raw string as `payload_raw`.
- `backend/app/services/audit_trail_service.py:89` - the checksum is `sha256(payload_raw.encode("utf-8"))`.
- `backend/app/services/audit_trail_service.py:105` - only the parsed `payload_obj` is persisted in the row.
- `backend/app/api/routes/audit.py:79` - `/audit/events/{id}/verify` validates only `verify_signature(event.checksum, event.signature, key)`.
- `backend/tests/test_audit_signature.py:7` - the test contract says the verify endpoint checks signatures and tampered checksums only.
- `backend/tests/test_audit_signature.py:60` - the negative helper test mutates only the checksum input, not the stored payload.

**Failure mode:**
The system signs a hash of the original wire-format JSON string, but it stores only the parsed JSON object. Whitespace, key ordering, and other lexical details of the original payload are discarded. An auditor who reads the row cannot recompute the checksum from persisted row data alone, and the `/verify` endpoint never tries. It proves only that the stored signature matches the stored checksum, not that the stored checksum still corresponds to the stored payload.

**Governance impact:**
This creates an unverifiable audit checksum, violating `docs/governance.md:55-56` and the hard-fail expectation in `docs/governance.md:174-181` when evidence cannot be independently reconstructed.

**Recommended remediation boundary:**
Persist the exact canonicalized bytestring that is hashed, or canonicalize the stored payload into a deterministic serialization and use that same serialization both for signing and for verification. `/audit/events/{id}/verify` must recompute the checksum from stored row data before validating the HMAC.

## Finding J-A5-GPT54-03 - Add signed audit coverage to uncovered mutation routes

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/api/routes/counterparties.py:21` - counterparty creation route has no `audit_event` dependency.
- `backend/app/api/routes/counterparties.py:81` - counterparty update route has no `audit_event` dependency.
- `backend/app/api/routes/counterparties.py:106` - counterparty delete route has no `audit_event` dependency.
- `backend/app/services/counterparty_service.py:38` - creation commits immediately.
- `backend/app/services/counterparty_service.py:81` - update commits immediately.
- `backend/app/services/counterparty_service.py:90` - soft delete commits immediately.
- `backend/app/api/routes/orders.py:89` - `POST /orders/links` has no `audit_event` dependency.
- `backend/app/services/order_service.py:148` - SO-PO link creation commits immediately.
- `backend/app/api/routes/finance_pipeline.py:23` - `POST /finance/pipeline/run` has no `audit_event` dependency.
- `backend/app/services/finance_pipeline_service.py:107` - pipeline execution commits the run and step mutations.
- `backend/tests/test_audit_economic_mutations.py:398` - the route coverage assertion does not enumerate counterparties, SO-PO links, or finance pipeline routes.

**Failure mode:**
These endpoints mutate durable institutional state without a signed `AuditEvent` tying the change to an actor, route invocation, and request payload. Counterparty lifecycle changes, order-link topology changes, and manual pipeline executions therefore leave no signed success trail that an auditor can verify later. In the pipeline case, the operator-triggered run can also fan out into downstream snapshot mutations without any signed envelope for the initiating request.

**Governance impact:**
Violates `docs/governance.md:55-56` and `docs/governance.md:174-186`, especially "Evidence is missing" and "No mutation without evidence."

**Recommended remediation boundary:**
Wrap each uncovered mutation route in the same signed audit pattern already used on the covered economic routes. At minimum, add route-level `audit_event` plus atomic commit wiring for counterparty create/update/delete, SO-PO link creation, and manual finance pipeline execution.

## Finding J-A5-GPT54-04 - Align auth fail-closed behavior with APP_ENV before exposing audit routes

**Severity:** Tier 2 / High
**Status:** Open
**Evidence:**
- `backend/app/core/config.py:20` - the application settings model treats `app_env` as the canonical environment marker.
- `backend/app/core/auth.py:38` - auth startup validation checks `ENVIRONMENT`, not `APP_ENV`.
- `backend/app/main.py:43` - the application relies on `validate_auth_config()` at startup.
- `backend/app/core/auth.py:117` - when auth is disabled, the fallback user carries `auditor` role membership.
- `backend/app/core/auth.py:128` - `get_current_user()` returns the anonymous fallback whenever JWT auth is disabled.
- `backend/app/core/auth.py:164` - `require_any_role()` returns immediately when auth is disabled.
- `backend/app/api/routes/audit.py:29` - audit listing relies only on `require_role("auditor")`.
- `backend/app/api/routes/audit.py:56` - audit verify relies only on `require_role("auditor")`.
- `backend/tests/test_auth_role_isolation.py:16` - current auth tests use dependency overrides and never exercise the real startup/env gating path.

**Failure mode:**
In a deployment that sets `APP_ENV=production` or `APP_ENV=staging` but does not also set `ENVIRONMENT`, startup does not fail closed when `JWT_ISSUER` is empty. The application then runs with auth disabled, `require_role()` becomes a no-op, and anonymous callers can read audit evidence and hit mutation routes protected only by role dependencies.

**Governance impact:**
Breaks the intended authorization boundary for the audit read surface and weakens governance enforcement around mutation routes. This undermines auditability and reconstructability by allowing untrusted callers to observe or trigger institutional flows outside the intended role gate.

**Recommended remediation boundary:**
Make auth startup validation consume the same environment source as the settings model and fail closed for production/staging whenever JWT auth is absent unless there is an explicit, audited override. The minimum acceptable fix is to unify on `APP_ENV` and keep audit endpoints unreachable when auth is disabled outside approved local/test modes.

## Anti-findings considered

- Append-only immutability is enforced at the database layer, not just in the ORM. `backend/alembic/versions/015_phase7_audit_events_table.py:34` installs SQLite `BEFORE UPDATE` and `BEFORE DELETE` rejection triggers, and `backend/alembic/versions/015_phase7_audit_events_table.py:53` installs the PostgreSQL trigger/function pair.
- The atomic audit pattern already exists and works where it is actually used. `backend/app/api/dependencies/uow.py:10` defers `request.state.audit_commit()` into the same final `session.commit()`, and routes such as `backend/app/api/routes/contracts.py:45` and `backend/app/api/routes/exposures.py:69` apply that pattern correctly.
- Inbound webhook ingestion does persist domain-specific durable evidence before downstream processing. `backend/app/api/routes/webhooks.py:72` persists `InboundWebhookDelivery` rows, and `backend/app/api/routes/webhooks.py:113` persists `InboundWebhookMessage` rows with duplicate-handling before queue handoff. I did not treat the absence of a signed `AuditEvent` on that path as an A5 finding because those specialized evidence tables are themselves the primary institutional artifact for inbound-provider proof.

## Cross-phase deferrals

- I did not escalate general route authorization design outside the concrete `APP_ENV`/`ENVIRONMENT` fail-closed mismatch. Broader IAM hardening belongs to a later cross-phase security pass unless it directly affects the A5 audit surface.
- I did not reopen Phase A3 domain math inside MTM/P&L/cashflow services. The findings above are strictly about audit atomicity and evidence binding on those existing mutation paths.
