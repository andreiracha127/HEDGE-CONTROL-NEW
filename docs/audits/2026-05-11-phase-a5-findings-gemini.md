# Phase A5 - Stage 2 Audit Dispatch - Auditor B

**Phase:** A5 - Audit trail, governance enforcement, and cross-cutting reconstruction
**Stage:** 2 of 3
**Target auditor:** Gemini 3.1 Pro
**Authoring date:** 2026-05-11
**Repository:** `D:/Projetos/Hedge-Control-New`
**Branch:** `main`

## Finding J-A5-GEMINI-01 - Early commit in domain logic bypasses fail-closed audit emission

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/api/routes/rfqs.py:112-115` - `RFQService.create()` is followed by `session.commit()` and only then `request.state.audit_commit()`.
- `backend/app/api/routes/orders.py:38-40` - `session.commit()` occurs implicitly inside `OrderService.create_sales_order()` (or explicitly in the route before `audit_commit`).
- `backend/app/services/rfq_service.py:734` - `session.commit()` is called internally by `RFQService.create()`.
- `backend/app/services/rfq_service.py:1008` - `session.commit()` is called internally by `RFQService.reject_quote()`.

**Failure mode:**
The domain mutation is committed to the database *before* the audit trail is written or signed. If the audit trail fails to write (e.g., database connection drops exactly between the two commits, or `MissingAuditSigningKey` is raised), the domain mutation is fully persisted but no audit evidence exists. The application fails to fail-closed, violating the transaction boundary.

**Governance impact:**
Violates "no mutation without evidence" and "audit failure prevents mutation rather than becoming a best-effort side effect."

**Recommended remediation boundary:**
Remove explicit `session.commit()` calls from HTTP routes and internal service methods like `create` or `reject_quote`. Wrap these routes entirely in the `unit_of_work` dependency block (as done in `contracts.py`) which ensures that `audit_commit()` executes within the same atomic transaction before the final domain commit.

---

## Finding J-A5-GEMINI-02 - Background mutations in orchestrator bypass audit evidence discipline

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/services/rfq_orchestrator.py:369` - `process_inbound_queue()` drains messages and triggers domain mutations (such as `_auto_create_quote` and `_finalize_durable_message`).
- `backend/app/services/rfq_orchestrator.py:840` - `_auto_create_quote()` calls `RFQService.submit_quote()` and `session.commit()` natively.

**Failure mode:**
Background queue workers execute institutional state mutations (such as automatically submitting an RFQ quote on behalf of a counterparty based on an LLM parse) completely bypassing the `audit_event` HTTP dependency. While an `LLMDecisionArtifact` is created, no generic `AuditEvent` is emitted for the actual domain state change (the new quote). 

**Governance impact:**
Violates "Do scheduled/background processes mutate institutional state without the same evidence discipline as HTTP routes?" by using disparate auditing models and committing without a generic `AuditEvent`.

**Recommended remediation boundary:**
Refactor the background task loop to instantiate a synthetic `Request` or utilize a dedicated `AuditTrailService.record()` call coupled inside the same transaction boundary before committing background mutations.

---

## Finding J-A5-GEMINI-03 - Migration downgrade destroys the append-only audit trail

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/alembic/versions/015_phase7_audit_events_table.py:53-61` - The `downgrade()` function executes `op.drop_table("audit_events")`.

**Failure mode:**
If an operator rolls back the database schema via `alembic downgrade`, the entire `audit_events` table is permanently dropped. The downgrade path treats the institutional audit evidence as disposable, allowing a single CLI command to erase all historical compliance data.

**Governance impact:**
Violates "make a signed event unverifiable; or mutate/delete audit history" and "migrations preserve audit history and verification over time."

**Recommended remediation boundary:**
Remove `op.drop_table("audit_events")` from the downgrade migration. The `audit_events` table and its data must remain immutable and persist across downgrades to preserve the historical audit trail.

---

## Finding J-A5-GEMINI-04 - Signature reconstruction impossible due to lost raw payload

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/api/dependencies/audit.py:32-34` - `payload_text = payload_bytes.decode("utf-8")` is parsed into `payload_obj`.
- `backend/app/services/audit_trail_service.py:83` - `checksum = hashlib.sha256(payload_raw.encode("utf-8")).hexdigest()` hashes the raw incoming string.
- `backend/app/models/audit.py:20` - `payload: Mapped[object] = mapped_column(JSON, nullable=False)` only stores the parsed JSON structure.

**Failure mode:**
The system computes the SHA-256 checksum and HMAC signature against the raw HTTP body string (`payload_text`), which includes arbitrary whitespace and key ordering from the client. However, it only stores the parsed JSON representation. Since the JSON serialization is not canonicalized upon ingestion, an auditor reading the JSON from the database cannot reliably reconstruct the original `payload_raw` string. The signature check (`/verify` endpoint) only works using the stored `checksum` column, but a third-party auditor cannot verify the `checksum` itself against the `payload`.

**Governance impact:**
Violates "Can an auditor recompute the checksum and HMAC from stored row data alone?" and "Contracts cannot be unreconstructible."

**Recommended remediation boundary:**
Canonicalize the payload using `normalize_payload_raw(payload_obj)` before computing the checksum and signature, rather than hashing the raw `payload_text`. Both the database and the auditor will then hash the exact same strictly ordered, minified representation.

---

## Finding J-A5-GEMINI-05 - Production audit validation can be bypassed via environment variable

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/core/config.py:73-83` - `model_post_init()` skips validating `AUDIT_SIGNING_KEY` if `app_env` is set to 'development' or 'local'.

**Failure mode:**
An operator can silently disable the startup-time mandatory validation of the `AUDIT_SIGNING_KEY` simply by setting `APP_ENV=development` in their production environment. The application will boot normally, and (due to Finding 01) process mutations without a valid signing key. 

**Governance impact:**
Violates "A database URL or test fixture must not be a production authorization policy" and "Are required governance secrets and safety settings validated before the app can serve mutation routes?"

**Recommended remediation boundary:**
Remove the `app_env` bypass from `Settings.model_post_init`. The configuration must require the key unconditionally unless the SQLite in-memory test database detection triggers.

---

### Anti-findings considered

- **Lack of pagination ordering in `audit.py`**: I initially suspected `list_audit_events` lacked an `order_by` clause, which would break cursor stability. However, evidence shows `app/core/pagination.py:53` automatically forces an `order_by(created_at_col.asc(), id_col.asc())` before slicing, preserving cursor stability. Rejected.
- **Trivial-message bypass in Orchestrator**: The `RFQOrchestrator._is_trivial_message` function ignores small or trivial WhatsApp messages ("ok", "thanks"). I investigated whether this suppresses evidence of inbound intent. It does not; it prevents wasting LLM tokens and does not mutate domain state. Rejected.

### Cross-phase deferrals

None.

### Recommended remediation waves

- **Wave 1 - Transaction & Signature Integrity**: Fix Finding 01 (Wrap routes in `unit_of_work`), Finding 04 (Canonicalize payload before hashing), and Finding 05 (Remove `app_env` bypass).
- **Wave 2 - Worker Audit & Migration Immutability**: Fix Finding 02 (Integrate generic `AuditEvent` in Orchestrator mutations) and Finding 03 (Remove `drop_table` from downgrade).
