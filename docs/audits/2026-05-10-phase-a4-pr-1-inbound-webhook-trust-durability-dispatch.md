# Phase A4 / PR-A4-1 Dispatch - Inbound Webhook Trust and Durability

**Date:** 2026-05-10  
**Base:** `main` at `514adfc2a` after Phase A4 auditor findings and jury verdict  
**Branch:** `audit-a4/inbound-webhook-trust-durability`  
**Findings closed:** `J-A4-01`, `J-A4-02`

---

## 1. Mission

Close the first Phase A4 remediation wave by making inbound WhatsApp webhook
traffic trustworthy and reconstructible.

Current behavior accepts Meta and Twilio inbound webhook requests without a
configured authenticity secret in production-like environments. The route only
logs a warning, extracts messages, enqueues simplified parsed objects, starts a
background worker, and returns HTTP 200. The raw provider envelope is not
durably stored before parsing, queueing, or acknowledgement.

PR-A4-1 must:

- fail closed in production/staging when the active inbound provider lacks the
  required webhook authenticity secret;
- reject missing or invalid signatures for configured providers;
- persist raw inbound webhook delivery evidence before extraction, queueing, or
  provider acknowledgement;
- keep local/test bypasses explicit and bounded;
- preserve existing canonical RFQ correlation behavior and LLM quote handling.

This is an inbound trust and evidence fix. It is not the durable replay /
one-time-consumption wave; that remains PR-A4-2.

---

## 2. Source Evidence

Read these before coding:

- `docs/audits/2026-05-10-phase-a4-jury-verdict.md:15-46`
  - `J-A4-01` validated finding: webhook secrets are optional and missing
    secrets only warn before processing.
- `docs/audits/2026-05-10-phase-a4-jury-verdict.md:48-79`
  - `J-A4-02` validated finding: raw inbound envelopes are not persisted before
    acknowledgement.
- `docs/audits/2026-05-10-phase-a4-jury-verdict.md:172-175`
  - PR-A4-1 recommended remediation boundary and verification.
- `docs/governance.md:113-115`
  - RFQ invitations/messages are evidence, not transient artifacts.
- `docs/governance.md:119-121`
  - Canonical RFQ identifier discipline; inbound correlation remains only via
    `RFQ#<rfq_number>`.
- `backend/app/api/routes/webhooks.py:110-151`
  - Meta path: raw body is local, missing secret only warns, payload is parsed
    and messages are enqueued.
- `backend/app/api/routes/webhooks.py:154-189`
  - Twilio path: form params are local, missing token only warns, messages are
    extracted and enqueued.
- `backend/app/services/webhook_processor.py:37-65`
  - Current process-local queue and dedup storage.
- `backend/app/schemas/whatsapp.py:51-58`
  - Current parsed inbound message shape lacks raw body, headers, signature
    context, provider envelope, and parse status.
- `backend/app/core/config.py:67-96`
  - Existing production/staging fail-closed pattern for `AUDIT_SIGNING_KEY`.
- `backend/app/core/config.py:110-122`
  - WhatsApp/Twilio integration settings are currently plain optional fields.
- `backend/tests/test_phase5_whatsapp_llm.py`
  - Existing `TestWebhookRoute.test_post_webhook_enqueues_messages` documents
    the no-secret Meta webhook path returning HTTP 200.
- `backend/tests/test_webhook_processor.py`
  - Existing signature verification and extraction coverage.

---

## 3. Scope IN

### 3.1 Add fail-closed provider secret validation

Modify `backend/app/core/config.py` and/or a small helper used by the webhook
route so production/staging cannot accept inbound webhook traffic without the
active provider's authenticity secret.

Required matrix:

- active provider `meta`:
  - production/staging must require non-empty `WHATSAPP_APP_SECRET`;
  - missing `X-Hub-Signature-256` must return HTTP 403;
  - invalid `X-Hub-Signature-256` must return HTTP 403.
- active provider `twilio`:
  - production/staging must require non-empty `TWILIO_AUTH_TOKEN`;
  - missing `X-Twilio-Signature` must return HTTP 403;
  - invalid `X-Twilio-Signature` must return HTTP 403.
- local/test/development bypass is allowed only through the existing explicit
  environment markers and/or sqlite in-memory test path. The bypass must be
  visible in code and tests; do not make "secret absent means accept" the default
  production behavior.

If implemented at startup, follow the `AUDIT_SIGNING_KEY` style in
`Settings.model_post_init()`. If implemented at route entry, the route must
still fail closed in production/staging before extraction and queueing.

### 3.2 Persist raw inbound delivery evidence

Introduce a durable inbound webhook delivery record before extraction,
queueing, or HTTP 200 acknowledgement.

Preferred model name:

```python
class InboundWebhookDelivery(Base):
    __tablename__ = "inbound_webhook_deliveries"
```

Minimum required fields:

- `id`;
- `provider` (`meta` or `twilio`);
- `provider_message_id` when extractable, nullable before parse;
- `sender_phone` when extractable, nullable before parse;
- `raw_body` for Meta JSON bytes/text or equivalent exact body representation;
- `raw_form` for Twilio form params or equivalent exact form representation;
- `headers` containing the relevant webhook signature headers and delivery
  metadata needed for reconstruction;
- `signature_present`;
- `signature_verified`;
- `signature_status` constrained to `missing`, `verified`, `invalid`, or
  `bypassed`;
- `parse_status` constrained to `received`, `parsed`, or `parse_failed`;
- `messages_extracted` count, nullable only for `parse_failed` rows;
- `received_at`;
- `acknowledged_at`, proving acknowledgement happened after persistence.

Use JSON/JSONB-compatible column types consistent with existing repo patterns.
The migration must be portable across PostgreSQL and SQLite tests.
Use the existing `JSON().with_variant(JSONB(), "postgresql")` style for JSON
payload columns in the SQLAlchemy model and Alembic migration rather than a
PostgreSQL-only `JSONB` type.
Concrete expected model/migration type mapping:

- `id`: UUID primary key.
- `provider`: constrained string/enum with values `meta`, `twilio`.
- `provider_message_id`: nullable `String(128)`.
- `sender_phone`: nullable `String(50)`.
- `raw_body`: nullable `Text`, populated for Meta exact raw JSON body text.
- `raw_form`: nullable `JSON().with_variant(JSONB(), "postgresql")`,
  populated for Twilio exact form parameters.
- `headers`: non-null `JSON().with_variant(JSONB(), "postgresql")`.
- `signature_present`: non-null `Boolean`.
- `signature_verified`: non-null `Boolean`.
- `signature_status`: constrained string/enum with values `missing`,
  `verified`, `invalid`, `bypassed`.
- `parse_status`: constrained string/enum with values `received`, `parsed`,
  `parse_failed`.
- `messages_extracted`: nullable `Integer`; `NULL` means parsing failed before
  extraction reached a meaningful message count.
- `received_at`: non-null timezone-aware `DateTime`.
- `acknowledged_at`: nullable timezone-aware `DateTime`, populated before
  returning provider acknowledgement.

Both `raw_body` and `raw_form` must be present on every row; the
non-applicable field is `NULL` (`raw_form` is `NULL` for Meta, `raw_body` is
`NULL` for Twilio). The two status fields must be enforced by an Enum, CHECK
constraint, or equivalent database-backed validation that is covered on both
PostgreSQL and SQLite paths.
The migration must also enforce the provider-exclusive raw capture invariant
with a database-level CHECK constraint. The strongest acceptable form is:

```sql
CHECK (
  provider IN ('meta', 'twilio')
  AND
  (
    (provider = 'meta' AND raw_body IS NOT NULL AND raw_form IS NULL)
    OR
    (provider = 'twilio' AND raw_body IS NULL AND raw_form IS NOT NULL)
  )
)
```

Add a SQLAlchemy `@validates("provider", "raw_body", "raw_form")` guard, or an
equivalent model-level validation hook, enforcing the same provider-exclusive
raw capture invariant independently of the database CHECK. This is required so
SQLite and test metadata paths do not rely only on Alembic's dialect-specific
CHECK rendering.
The model-level guard must raise `ValueError` with a descriptive message on
constraint violation. Cover it by constructing an `InboundWebhookDelivery`
object outside a session and asserting the `ValueError` is raised before any DB
flush.

Add a CHECK or equivalent database-backed validation for message count semantics:

```sql
CHECK (
  (parse_status = 'parse_failed' AND messages_extracted IS NULL)
  OR
  (parse_status IN ('received', 'parsed') AND messages_extracted IS NOT NULL)
)
```

For invalid JSON/form extraction failures, preserve the inbound delivery record
with a failed parse status before returning the controlled HTTP error.

In the local/test bypass path where the provider secret is not configured and
the environment marker explicitly allows bypass, persist the delivery record
with `signature_status="bypassed"` before extraction and queueing.

For invalid/missing signatures, prefer preserving a rejected delivery record with
signature metadata. If you choose not to persist rejected unauthenticated
requests, document why in code/tests and ensure valid signed requests are still
persisted before queueing or acknowledgement. The accepted finding requires
durability for provider deliveries that the system acknowledges or processes.

### 3.3 Rewire webhook route ordering

Modify `backend/app/api/routes/webhooks.py` so both provider paths follow this
order:

1. Read raw request input required for signature validation.
2. Determine provider and signature metadata.
3. Enforce fail-closed secret/signature policy for the active environment.
4. Persist inbound delivery evidence before extraction and queueing.
5. Extract parsed `WhatsAppInboundMessage` values.
6. Update delivery parse/extraction status.
7. Enqueue messages.
8. Return provider acknowledgement.

The exact transactional boundary is executor-defined, but an acknowledged
provider request must not be reconstructible only from process memory.

### 3.4 Keep current RFQ processing semantics intact

Do not change:

- `_parse_canonical_ids()`;
- `_strip_canonical_id()`;
- phone consistency checks after canonical RFQ resolution;
- LLM confidence gates;
- quote auto-creation behavior;
- outbound RFQ invitation evidence;
- existing queue drain behavior except for passing through or linking durable
  delivery metadata if needed.

### 3.5 Migration and model registration

Add the Alembic migration for the new durable inbound delivery table.

Expected revision:

- `040_a4_inbound_webhook_delivery.py`

Keep the revision id at or below Alembic's 32-character `version_num` limit.
`040_a4_inbound_webhook_delivery` is 31 characters and acceptable.
Before creating the migration file, run `cd backend && alembic heads` to confirm
the current head and that `040` is still the correct next sequential prefix. If
another migration has landed first, choose the correct next prefix while keeping
the revision id at or below 32 characters.

Ensure the model is imported/registered wherever this repo requires model
registration for metadata creation in tests.
Specifically, add
`from app.models.inbound_webhook_delivery import InboundWebhookDelivery` to
`backend/app/models/__init__.py` and add `InboundWebhookDelivery` to `__all__`,
because `backend/tests/conftest.py` imports `app.models` before
`Base.metadata.create_all()`.

Concrete registration template:

```python
# backend/app/models/__init__.py
from app.models.inbound_webhook_delivery import InboundWebhookDelivery

__all__ = [
    # keep the existing list stable and add:
    "InboundWebhookDelivery",
]
```

The module-body import is required. Adding only the `__all__` entry is not
sufficient to register the table with `Base.metadata`.

---

## 4. Scope OUT

- Do not modify `docs/governance.md`.
- Do not implement PR-A4-2 durable replay / one-time-consumption semantics.
- Do not make `provider_message_id` a final replay-consumption gate in this PR.
  Indexing it for diagnostics is fine; uniqueness/consumption belongs to
  PR-A4-2 unless required for table integrity.
- Do not change RFQ canonical correlation logic.
- Do not change LLM parsing, confidence threshold, or quote creation semantics.
- Do not implement LLM decision artifact persistence; that is PR-A4-3.
- Do not rewrite `webhook_processor.py` into a database queue unless narrowly
  required for raw delivery linkage. Process-local queue replacement is PR-A4-2
  territory.
- Do not change outbound WhatsApp provider behavior except where tests need
  setup updates.
- Do not relax hard-fail behavior for invalid signatures or malformed payloads.
- Do not rewrite existing HMAC helper call sites unless the executor environment
  surfaces a concrete runtime failure in focused tests. If a compatibility fix
  is required, limit it to the failing helper call and use
  `hmac.HMAC(key=secret.encode(), msg=body, digestmod=hashlib.sha256)` or an
  equivalent form without changing signature test logic.

---

## 5. Acceptance Criteria

- [ ] Production/staging with provider `meta` and empty `WHATSAPP_APP_SECRET`
  refuses inbound Meta webhook processing before extraction/queueing.
- [ ] Production/staging with provider `twilio` and empty `TWILIO_AUTH_TOKEN`
  refuses inbound Twilio webhook processing before extraction/queueing.
- [ ] Local/test bypass is gated on an explicit environment marker such as
  `app_env in {"test", "local", "development", "dev"}`, emits a warning log,
  and is covered by a test proving the bypass does not activate for
  `app_env=production`.
- [ ] Meta requests with configured secret and missing signature return HTTP
  403 and do not enqueue messages.
- [ ] Meta requests with configured secret and invalid signature return HTTP
  403 and do not enqueue messages.
- [ ] Twilio requests with configured token and missing signature return HTTP
  403 and do not enqueue messages.
- [ ] Twilio requests with configured token and invalid signature return HTTP
  403 and do not enqueue messages.
- [ ] Valid signed Meta webhook requests create an inbound delivery record
  before messages are enqueued.
- [ ] Valid signed Twilio webhook requests create an inbound delivery record
  before messages are enqueued.
- [ ] Durable delivery records include enough raw input and signature metadata
  to reconstruct what was received and how authenticity was evaluated.
- [ ] `signature_status` and `parse_status` are constrained to the exact values
  listed in §3.2.
- [ ] Meta rows populate `raw_body` and leave `raw_form` null; Twilio rows
  populate `raw_form` and leave `raw_body` null.
- [ ] A database CHECK constraint enforces that the provider value matches the
  applicable raw evidence column and rejects both-null/both-populated rows for
  constrained provider values `meta` and `twilio`.
- [ ] A model-level validation hook enforces the same provider/raw evidence
  invariant independent of Alembic CHECK rendering.
- [ ] `messages_extracted` is NULL only for `parse_failed` rows and non-NULL for
  `received`/`parsed` rows.
- [ ] Malformed Meta JSON preserves a failed inbound delivery record before
  returning HTTP 400.
- [ ] The existing canonical RFQ ID processing tests keep passing.
- [ ] `docs/governance.md` has no diff.

---

## 6. Required Tests

Add or update focused tests before broad runs.

Minimum expected coverage:

- `backend/tests/test_webhook_processor.py`
  - keep existing signature helper/extraction tests passing;
  - add model/service-level tests if you place delivery persistence helpers
    outside the route.
- `backend/tests/test_phase5_whatsapp_llm.py` or a new focused route test module
  - production/staging Meta no-secret request hard-fails;
  - local/test Meta no-secret request remains allowed only when explicit bypass
    conditions are present;
  - production/staging Twilio no-token request hard-fails;
  - valid signed Meta request persists delivery before enqueue;
  - valid signed Twilio request persists delivery before enqueue;
  - malformed Meta JSON creates a failed delivery record.
- Migration test:
  - upgrade creates the inbound delivery table with expected columns;
  - downgrade removes it cleanly;
  - SQLite-compatible table creation path is covered.

Run at minimum:

```bash
python -m pytest backend/tests/test_webhook_processor.py -q
python -m pytest backend/tests/test_phase5_whatsapp_llm.py -q
python -m pytest backend/tests/test_rfq_orchestrator.py -q
python -m pytest backend/tests/scripts/ -v
cd backend && alembic heads
git diff --check
```

If the executor adds a dedicated migration test file, include it in the focused
test run explicitly. If broad backend tests are run, document the known local
Python 3.14 `backend/tests/test_ws.py` baseline separately and do not conflate it
with this PR.

---

## 7. Review Gates

Before opening the PR:

1. Confirm `docs/governance.md` is unchanged.
2. Confirm no implementation for J-A4-03 or J-A4-04 leaked into this branch.
3. Confirm no `--no-verify` push was used unless explicitly authorized and
   documented in the PR.
4. Confirm the pre-push hook artifact reports no P1 blockers. If the hook raises
   real catches, fix them locally before invoking Codex Connector.
5. Open a PR against `main` with title:

```text
fix(audit-a4): PR-A4-1 inbound webhook trust and durability
```

PR body must include:

- findings closed: `J-A4-01`, `J-A4-02`;
- migration revision id;
- focused test results;
- Alembic head result;
- hook artifact summary;
- explicit statement that `docs/governance.md` has no diff;
- explicit statement that PR-A4-2 replay semantics and PR-A4-3 LLM decision
  artifact persistence remain out of scope.

Do not merge. Merge requires explicit authorization after CI and Codex Connector
review.
