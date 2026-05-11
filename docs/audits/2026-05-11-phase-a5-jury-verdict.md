# Phase A5 Jury Verdict

## Executive Summary

- Total accepted findings: 6
- Tier 1: 4
- Tier 2: 2
- Tier 3: 0
- Tier 4: 0
- Rejected auditor findings: 1
- Fresh jury findings: 1

## Accepted Findings

### J-A5-01 - Make audit emission atomic with covered institutional mutations

**Source:** GPT54 J-A5-GPT54-01 | Gemini J-A5-GEMINI-01
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `backend/app/api/routes/orders.py:38` - `POST /orders/sales` calls `OrderService.create_sales_order()` before route-level audit emission.
- `backend/app/services/order_service.py:231` - order creation adds the order and then commits at `backend/app/services/order_service.py:232`.
- `backend/app/api/routes/orders.py:133` - order archive calls `OrderService.archive()` before audit emission.
- `backend/app/services/order_service.py:106` - order archive mutates `deleted_at` and commits at `backend/app/services/order_service.py:107`.
- `backend/app/api/routes/rfqs.py:111` - RFQ creation calls `RFQService.create()`, then commits at `backend/app/api/routes/rfqs.py:112`, before `request.state.audit_commit()` at `backend/app/api/routes/rfqs.py:115`.
- `backend/app/api/routes/rfqs.py:268` - quote creation calls `RFQService.submit_quote()`, then commits at `backend/app/api/routes/rfqs.py:269`, before audit emission.
- `backend/app/api/routes/rfqs.py:320` - RFQ reject mutates state, then commits at `backend/app/api/routes/rfqs.py:321`, before audit emission.
- `backend/app/api/routes/rfqs.py:376` - quote rejection mutates state, then commits at `backend/app/api/routes/rfqs.py:377`, before audit emission.
- `backend/app/api/routes/mtm.py:65` - MTM snapshot creation returns a persisted snapshot before audit emission at `backend/app/api/routes/mtm.py:83`.
- `backend/app/services/mtm_snapshot_service.py:110` - MTM snapshot insert commits at `backend/app/services/mtm_snapshot_service.py:111`.
- `backend/app/api/routes/pl.py:49` - P&L snapshot creation returns before audit emission at `backend/app/api/routes/pl.py:56`.
- `backend/app/services/pl_snapshot_service.py:105` - P&L snapshot insert commits at `backend/app/services/pl_snapshot_service.py:106`.
- `backend/app/api/routes/cashflow.py:55` - cashflow baseline snapshot creation returns before audit emission at `backend/app/api/routes/cashflow.py:58`.
- `backend/app/services/cashflow_baseline_service.py:268` - cashflow baseline snapshot insert commits at `backend/app/services/cashflow_baseline_service.py:269`.
- `backend/app/api/routes/cashflow_ledger.py:46` - hedge settlement ingestion returns before audit emission at `backend/app/api/routes/cashflow_ledger.py:49`.
- `backend/app/services/cashflow_ledger_service.py:290` - settlement mutates contract status and commits at `backend/app/services/cashflow_ledger_service.py:291`.
- `backend/app/api/dependencies/uow.py:19` - the existing safe pattern defers audit insert into the same route-level transaction and commits once at `backend/app/api/dependencies/uow.py:26`.

**Failure mode:**
A client invokes a covered economic mutation. The service or route commits the domain mutation first. If `AUDIT_SIGNING_KEY` is missing, the audit insert conflicts, the database connection drops, or the process dies before `request.state.audit_commit()`, institutional state is durable but the signed audit row is absent. A retry then sees already-mutated state with no signed success evidence for the original mutation.

**Governance impact:**
Violates the binding optimization targets of auditability and reconstructability in `docs/governance.md:51` through `docs/governance.md:56`, and the hard-fail rule "Evidence is missing" / "No mutation without evidence" in `docs/governance.md:174` through `docs/governance.md:186`.

**Remediation boundary:**
Move these routes and their called services onto `unit_of_work(session, request=request)` or an equivalent single-commit boundary. Remove intermediate commits from audit-critical service flows so the domain mutation and signed `AuditEvent` are flushed and committed atomically.

### J-A5-02 - Persist and verify a reconstructible audit checksum input

**Source:** GPT54 J-A5-GPT54-02 | Gemini J-A5-GEMINI-04
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `backend/app/api/dependencies/audit.py:35` - the audit dependency reads raw request bytes.
- `backend/app/api/dependencies/audit.py:36` - the checksum input is the decoded raw request string.
- `backend/app/api/dependencies/audit.py:37` - the persisted payload object is parsed JSON, not the exact string that was hashed.
- `backend/app/api/dependencies/audit.py:57` - `AuditTrailService.record()` receives the raw string as `payload_raw`.
- `backend/app/api/dependencies/audit.py:58` - the stored payload is `payload_obj`.
- `backend/app/services/audit_trail_service.py:89` - checksum is `sha256(payload_raw.encode("utf-8"))`.
- `backend/app/services/audit_trail_service.py:105` - only `payload_obj` is persisted on the audit row.
- `backend/app/models/audit.py:22` - the model stores `payload` as JSON only.
- `backend/app/api/routes/audit.py:79` - verify checks `HMAC(checksum)` against stored checksum and signature.
- `backend/app/services/audit_trail_service.py:156` - a deterministic `normalize_payload_raw()` helper exists but the record path does not use it.

**Failure mode:**
Two JSON bodies with the same parsed object but different whitespace or key order can produce different checksums. The row stores only the parsed JSON object, so an auditor cannot recompute the original checksum from stored row data. The verify endpoint confirms only that the signature matches the stored checksum, not that the checksum still corresponds to the stored payload.

**Governance impact:**
Makes the signed event only partially reconstructible and therefore breaks `docs/governance.md:55` through `docs/governance.md:56` and the hard-fail rule for unreconstructible contracts/evidence in `docs/governance.md:174` through `docs/governance.md:186`.

**Remediation boundary:**
Canonicalize the payload before hashing, persist the exact canonical representation or enough deterministic input to reproduce it, and make `/audit/events/{id}/verify` recompute the checksum from persisted data before checking the HMAC.

### J-A5-03 - Add signed audit coverage to uncovered and no-op-covered mutation routes

**Source:** GPT54 J-A5-GPT54-03 | Jury Fresh
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted with expanded jury evidence
**Evidence:**
- `backend/app/api/routes/counterparties.py:21` - counterparty creation has role auth but no `audit_event` dependency.
- `backend/app/services/counterparty_service.py:38` - counterparty creation adds a row and commits at `backend/app/services/counterparty_service.py:39`.
- `backend/app/api/routes/counterparties.py:81` - counterparty update has no `audit_event` dependency.
- `backend/app/services/counterparty_service.py:81` - counterparty update commits.
- `backend/app/api/routes/counterparties.py:106` - counterparty delete has no `audit_event` dependency.
- `backend/app/services/counterparty_service.py:86` - counterparty soft delete mutates flags and commits at `backend/app/services/counterparty_service.py:90`.
- `backend/app/api/routes/orders.py:89` - SO-PO link creation has no `audit_event` dependency.
- `backend/app/services/order_service.py:148` - SO-PO link insert commits at `backend/app/services/order_service.py:149`.
- `backend/app/api/routes/finance_pipeline.py:23` - manual finance pipeline execution has no `audit_event` dependency.
- `backend/app/services/finance_pipeline_service.py:77` - pipeline run steps are mutated during execution and committed at `backend/app/services/finance_pipeline_service.py:107`.
- `backend/app/api/routes/westmetall.py:115` - single-date Westmetall ingest declares `audit_event`.
- `backend/app/api/routes/westmetall.py:133` - the route deletes `request`, never calls `mark_audit_success()`, and therefore never records the declared audit event.
- `backend/app/services/cash_settlement_prices.py:50` - single-date market-data ingest inserts a `CashSettlementPrice` and commits at `backend/app/services/cash_settlement_prices.py:51`.
- `backend/app/api/routes/westmetall.py:161` - bulk Westmetall ingest declares `audit_event`.
- `backend/app/api/routes/westmetall.py:179` - the bulk route also deletes `request`, never calls `mark_audit_success()`, and therefore never records the declared audit event.
- `backend/app/services/cash_settlement_prices.py:96` - bulk ingest inserts price rows and commits at `backend/app/services/cash_settlement_prices.py:110`.
- `backend/tests/test_audit_economic_mutations.py:398` - static coverage only enumerates six routes and does not cover the current repo-wide mutating route set.

**Failure mode:**
An authorized caller can mutate counterparty master data, SO-PO topology, pipeline run state, or market-data price rows without a signed `AuditEvent`. In Westmetall routes the dependency is present but inert because success is never marked, so a superficial dependency scan would still miss the missing audit row.

**Governance impact:**
Creates durable institutional mutations without signed actor-bound evidence, violating `docs/governance.md:55` through `docs/governance.md:56` and `docs/governance.md:174` through `docs/governance.md:186`.

**Remediation boundary:**
Add route-level signed audit coverage and single-transaction commit wiring for counterparty create/update/delete, SO-PO link creation, finance pipeline trigger, and both Westmetall ingest routes. Expand static and behavioral tests from the six-route whitelist to the actual in-scope mutating route set derived by `rg -n "@router\.(post|put|patch|delete)" backend/app/api/routes`.

### J-A5-04 - Preserve audit history across downgrade paths

**Source:** Gemini J-A5-GEMINI-03
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `backend/alembic/versions/015_phase7_audit_events_table.py:19` - upgrade creates `audit_events`.
- `backend/alembic/versions/015_phase7_audit_events_table.py:34` - SQLite append-only triggers are installed.
- `backend/alembic/versions/015_phase7_audit_events_table.py:53` - PostgreSQL append-only trigger/function path is installed.
- `backend/alembic/versions/015_phase7_audit_events_table.py:73` - downgrade removes enforcement artifacts.
- `backend/alembic/versions/015_phase7_audit_events_table.py:82` - downgrade drops the `audit_events` table.

**Failure mode:**
An operator running the migration downgrade can delete the entire signed audit-event history. That makes previously signed events unavailable and unverifiable even though runtime DML triggers correctly reject direct update/delete attempts.

**Governance impact:**
Breaks append-only history and reconstruction guarantees under `docs/governance.md:55` through `docs/governance.md:56`, and directly conflicts with the Tier 1 boundary for deleting audit history.

**Remediation boundary:**
Remove destructive audit-table downgrade behavior. If downgrade compatibility is needed, downgrade should preserve `audit_events` data and only alter non-destructive schema/runtime objects with explicit operator documentation.

### J-A5-05 - Give background RFQ auto-quote mutations the same signed audit envelope

**Source:** Gemini J-A5-GEMINI-02
**Severity:** Tier 2 / High
**Status:** Open
**Disposition:** Accepted with severity change
**Evidence:**
- `backend/app/services/rfq_orchestrator.py:717` - the worker claims an inbound durable message.
- `backend/app/services/rfq_orchestrator.py:743` - the claim is committed.
- `backend/app/services/rfq_orchestrator.py:785` - `_finalize_durable_message()` mutates durable message processing status.
- `backend/app/services/rfq_orchestrator.py:815` - durable message finalization commits.
- `backend/app/services/rfq_orchestrator.py:1410` - `_auto_create_quote()` can create an RFQ quote from an inbound message parse.
- `backend/app/services/rfq_orchestrator.py:1551` - auto-quote calls `RFQService.submit_quote()`, which inserts the quote and may transition RFQ state.
- `backend/app/services/rfq_orchestrator.py:1564` - an `LLMDecisionArtifact` is added for the auto-quote decision.
- `backend/app/services/rfq_orchestrator.py:1585` - quote and decision artifact are committed together.
- `backend/app/models/llm_decision_artifact.py:20` - `auto_quote_created` is a first-class decision status.

**Failure mode:**
The worker can create an RFQ quote and transition RFQ state without the generic signed `AuditEvent` envelope used for HTTP mutations. The durable inbound message and `LLMDecisionArtifact` materially reduce reconstruction risk, so the failure is not a total absence of evidence, but the signed audit trail remains incomplete and inconsistent for a closed A2/A5-relevant state transition.

**Governance impact:**
Impairs auditability and evidence linkage for background institutional mutations, especially under the A5 question requiring background processes to follow the same evidence discipline as request paths.

**Remediation boundary:**
Introduce a worker-safe audit emission API that records a signed `AuditEvent` in the same transaction as the quote, RFQ state event, inbound message linkage, and `LLMDecisionArtifact`. Do not fabricate a synthetic HTTP request; use an explicit service boundary for non-HTTP actor/source metadata.

### J-A5-06 - Align auth startup fail-closed behavior with canonical settings

**Source:** GPT54 J-A5-GPT54-04
**Severity:** Tier 2 / High
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `backend/app/core/config.py:20` - canonical app environment is `app_env`.
- `backend/app/core/config.py:127` - settings-level auth enablement depends on `jwt_issuer`.
- `backend/app/core/auth.py:27` - auth module separately reads `JWT_ISSUER` directly from environment.
- `backend/app/core/auth.py:31` - startup validation is implemented in `validate_auth_config()`.
- `backend/app/core/auth.py:38` - startup validation checks `ENVIRONMENT`, not `APP_ENV`.
- `backend/app/core/auth.py:117` - anonymous fallback user includes `auditor`.
- `backend/app/core/auth.py:124` - `get_current_user()` returns the anonymous fallback when auth is disabled.
- `backend/app/core/auth.py:162` - `require_any_role()` returns without role checks when auth is disabled.
- `backend/app/api/routes/audit.py:37` - audit event list relies on `require_role("auditor")`.
- `backend/app/api/routes/audit.py:59` - audit event verify relies on `require_role("auditor")`.

**Failure mode:**
A deployment can set `APP_ENV=production` while leaving `ENVIRONMENT` unset and `JWT_ISSUER` empty. Startup validation does not fail closed because it consults the wrong environment marker. The app then runs with auth disabled, anonymous users carry the `auditor` role, and audit read/verify endpoints become reachable without real authentication.

**Governance impact:**
Weakens the audit read surface and role boundary for institutional evidence. This is not itself a state mutation, so Tier 2 is correct.

**Remediation boundary:**
Unify auth startup validation on the same settings object and environment marker used by `Settings`. Production/staging must fail closed when JWT auth is absent unless an explicit and narrowly scoped local/test override is active.

## Rejected Findings

### J-A5-GEMINI-05 - Production audit validation can be bypassed via environment variable

**Disposition:** Rejected as an independent Tier 1 finding
**Reason:** The cited code is real: `backend/app/core/config.py:67` through `backend/app/core/config.py:92` exempts development/local/test from startup `AUDIT_SIGNING_KEY` validation. But that does not independently disable runtime audit signing: `backend/app/services/audit_trail_service.py:91` through `backend/app/services/audit_trail_service.py:96` still fail closed when audit emission is attempted without a signing key. The actual Tier 1 failure emerges only where routes commit before audit emission, which is already accepted as J-A5-01. Treating an operator-set `APP_ENV=development` in production as a standalone code bypass overstates severity and duplicates the transaction-boundary finding.

## Subsumed Findings

- `J-A5-GEMINI-01` is subsumed by canonical finding `J-A5-01`.
- `J-A5-GEMINI-04` is subsumed by canonical finding `J-A5-02`.
- The portions of `J-A5-GEMINI-05` that depend on mutations surviving a missing signing key are subsumed by `J-A5-01`.

## Cross-Phase Deferrals

- Broader IAM design outside the concrete `APP_ENV` / `ENVIRONMENT` startup mismatch should be deferred to a later security/governance pass.
- Frontend audit visibility, dashboards, and operator UX are out of A5 scope.
- General market-data governance beyond signed evidence for the Westmetall ingest mutation should be handled in a later data-ingestion hardening wave.

## Recommended Remediation Waves

### PR-A5-1 - Transaction boundary and checksum reconstruction
- Findings: J-A5-01, J-A5-02
- Scope boundary: covered HTTP mutations that already declare `audit_event`; remove intermediate commits and canonicalize/persist/verifiably recompute audit checksum input.
- Required verification: focused route tests proving missing signing key rolls back each covered mutation; signature tests proving payload tamper and checksum/payload mismatch fail verification; `rg -n "session\.commit\(|db\.commit\("` review for touched services.

### PR-A5-2 - Missing route coverage and worker audit envelope
- Findings: J-A5-03, J-A5-05
- Scope boundary: add signed audit coverage for uncovered/no-op-covered mutating routes and add a non-HTTP signed audit API for RFQ worker auto-quote mutations.
- Required verification: repo-wide route coverage test from `@router.(post|put|patch|delete)` inventory; behavioral tests for counterparty/SO-PO/finance/Westmetall audit rows; worker test proving quote, LLM artifact, durable message linkage, and signed audit row commit atomically.

### PR-A5-3 - Audit history and authorization guardrails
- Findings: J-A5-04, J-A5-06
- Scope boundary: make audit migration downgrade non-destructive and unify auth startup validation on canonical settings.
- Required verification: migration downgrade test or static assertion preventing `op.drop_table("audit_events")`; startup tests for `APP_ENV=production|staging` with missing JWT config; audit route tests proving anonymous access is rejected when production/staging auth is expected.

## Anti-Findings Confirmed

- Append-only DML protection exists for the runtime audit table: SQLite update/delete triggers are installed at `backend/alembic/versions/015_phase7_audit_events_table.py:34` and PostgreSQL trigger/function enforcement at `backend/alembic/versions/015_phase7_audit_events_table.py:53`.
- The `unit_of_work` pattern itself is sound where used: it defers audit insertion at `backend/app/api/dependencies/uow.py:19` through `backend/app/api/dependencies/uow.py:25` and commits once at `backend/app/api/dependencies/uow.py:26`; contract creation applies it at `backend/app/api/routes/contracts.py:45` through `backend/app/api/routes/contracts.py:47`.
- Scenario what-if execution is not a mutation despite being a `POST`: `backend/app/api/routes/scenario.py:29` calls `run_what_if()`, and the service search found queries/response assembly but no commit/add path in `backend/app/services/scenario_whatif_service.py`.
- Inbound webhook ingestion has specialized durable evidence tables before downstream processing: initial delivery is committed at `backend/app/api/routes/webhooks.py:72` through `backend/app/api/routes/webhooks.py:78`, and inbound messages are committed at `backend/app/api/routes/webhooks.py:131` through `backend/app/api/routes/webhooks.py:145`.
- Audit pagination is ordered deterministically by timestamp and id at `backend/app/core/pagination.py:62`.
- Trivial inbound WhatsApp messages do not mutate RFQ state; the pre-filter returns a skip response at `backend/app/services/rfq_orchestrator.py:932` through `backend/app/services/rfq_orchestrator.py:944`.
