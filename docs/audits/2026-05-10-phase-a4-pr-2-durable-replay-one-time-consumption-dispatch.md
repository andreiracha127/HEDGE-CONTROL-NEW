# Phase A4 / PR-A4-2 Dispatch - Durable Replay and One-Time Consumption

**Date:** 2026-05-10  
**Base:** `main` at `12eca46cc` after PR #52  
**Branch:** `audit-a4/durable-inbound-replay`  
**Findings closed:** `J-A4-03`

---

## 1. Mission

Close Phase A4 finding `J-A4-03` by making inbound WhatsApp message replay
protection durable and independent of process memory, queue lifetime, and quote
lifecycle state.

PR-A4-1 made inbound webhook deliveries trustworthy and reconstructible through
`InboundWebhookDelivery`. It did not close replay semantics: extracted provider
messages are still queued in process memory, duplicate suppression is still a
local deque/set in `webhook_processor.py`, and the RFQ orchestrator still has no
durable record proving a provider message was already consumed.

PR-A4-2 must ensure that a single provider message ID is processed at most once
across:

- process restart;
- multi-worker delivery;
- queue eviction;
- provider redelivery;
- quote rejection after a previous auto-created quote.

This is a replay/idempotency fix. It is not the LLM decision-artifact wave; that
remains PR-A4-3.

---

## 2. Source Evidence

Read these before coding:

- `docs/audits/2026-05-10-phase-a4-jury-verdict.md:81-110`
  - `J-A4-03` validated finding.
- `docs/audits/2026-05-10-phase-a4-jury-verdict.md:177-180`
  - PR-A4-2 remediation wave: durable provider-delivery keys, uniqueness,
    processing status, idempotent replay behavior.
- `docs/governance.md:113-115`
  - Messages are evidence, not transient artifacts.
- `docs/governance.md:119-121`
  - Inbound correlation remains only via `RFQ#<rfq_number>`.
- `backend/app/models/inbound_webhook_delivery.py:29-137`
  - Current durable delivery model from PR-A4-1.
- `backend/app/api/routes/webhooks.py:232-269`
  - Meta path persists delivery, extracts parsed messages, enqueues in memory,
    then acknowledges.
- `backend/app/api/routes/webhooks.py:340-365`
  - Twilio path persists delivery, extracts parsed messages, enqueues in memory.
- `backend/app/services/webhook_processor.py:37-65`
  - Current in-process queue and `_seen_set` duplicate suppression.
- `backend/app/services/rfq_orchestrator.py:266-274`
  - Queue drain processes parsed messages without durable consumption state.
- `backend/app/services/rfq_orchestrator.py:498-529`
  - Duplicate quote suppression runs only after LLM parsing and only considers
    active quotes.
- `backend/app/models/quotes.py:17-26`
  - Rejected quotes are preserved and excluded from active duplicate checks.
- `backend/tests/test_inbound_webhook_delivery.py`
  - Existing PR-A4-1 persistence, signature, migration, and delivery tests.
- `backend/tests/test_rfq_orchestrator.py`
  - Existing inbound processing and quote creation tests.

---

## 3. Scope IN

### 3.1 Add a durable extracted-message record

Do not rely on `InboundWebhookDelivery.provider_message_id` alone for
idempotency. A provider webhook delivery can contain more than one inbound
message, and replay prevention must apply to each extracted provider message.

Add a durable per-message model, preferred name:

```python
class InboundWebhookMessage(Base):
    __tablename__ = "inbound_webhook_messages"
```

Minimum required fields:

- `id`;
- `delivery_id` foreign key to `inbound_webhook_deliveries.id`;
- `provider` constrained to `meta` or `twilio`;
- `provider_message_id`;
- `sender_phone`;
- `sender_name`;
- `timestamp`;
- `text`;
- `processing_status`;
- `processing_started_at`;
- `processing_completed_at`;
- `processing_result`;
- `rfq_number`;
- `rfq_id`;
- `quote_id`;
- `created_at`.

Required constraints:

- unique `(provider, provider_message_id)`;
- `provider_message_id` non-null and non-empty;
- `processing_status` constrained to:
  - `received`;
  - `processing`;
  - `processed`;
  - `duplicate`;
  - `failed`.

Use JSON/JSONB-compatible column types for `processing_result` using the repo's
portable `JSON().with_variant(JSONB(), "postgresql")` pattern.

Register the new model in `backend/app/models/__init__.py` so
`Base.metadata.create_all()` sees the table in SQLite tests.

### 3.2 Create migration 041

Add Alembic migration:

```text
041_a4_inbound_webhook_messages.py
```

Before creating the file, run:

```bash
cd backend && python -m alembic heads
```

Current expected head is `040_a4_inbound_webhook_delivery`. If a newer migration
has landed first, choose the correct next prefix while keeping the revision ID
at or below Alembic's 32-character `version_num` limit.

Migration requirements:

- create `inbound_webhook_messages`;
- add unique constraint on `(provider, provider_message_id)`;
- add processing-status constraint;
- create useful indexes for `delivery_id`, `processing_status`, and
  `provider_message_id`;
- downgrade removes all introduced objects cleanly.

### 3.3 Persist extracted message rows before enqueue

Modify `backend/app/api/routes/webhooks.py` and/or a small helper so every
extracted `WhatsAppInboundMessage` is first persisted as an
`InboundWebhookMessage` row linked to the already-created
`InboundWebhookDelivery`.

Required behavior:

- For a new provider message ID:
  - insert the durable message row with `processing_status="received"`;
  - enqueue a queue item that carries the durable message row ID;
  - do not enqueue before the durable message row exists.
- For a duplicate provider message ID:
  - do not enqueue it again;
  - do not invoke LLM parsing;
  - do not create or mutate quotes;
  - record a deterministic duplicate result, either by returning the existing
    row or creating a rejected/duplicate audit trace linked to the new delivery.

The unique constraint must be the final arbiter. Application-level pre-checks
are allowed for clean logs, but they are not sufficient without the DB unique
constraint.

### 3.4 Replace process-local duplicate suppression as the authority

`webhook_processor.py` may keep a small in-memory queue, but `_seen_set` and
`_seen_message_ids` must no longer be the authoritative duplicate guard.

Acceptable options:

- remove local duplicate suppression entirely and rely on durable insertion
  before enqueue; or
- keep local suppression only as an optimization after durable insertion has
  already established one-time consumption.

In either case, provider redelivery after restart or local cache eviction must
not enqueue/process the same provider message again.

### 3.5 Carry durable message identity into the orchestrator

Modify the queue item shape so `RFQOrchestrator.process_inbound_queue()` can
recover and update the durable `InboundWebhookMessage` row.

Preferred direction:

- add an optional `delivery_message_id` field to the inbound queue payload or a
  small wrapper object;
- load the `InboundWebhookMessage` row at processing start;
- transition status:
  - `received` -> `processing`;
  - `processing` -> `processed` with `processing_result`;
  - `processing` -> `failed` with error detail on controlled failure.

The processing result must capture enough to prove what happened:

- final orchestrator status;
- canonical RFQ number if found;
- RFQ ID if found;
- quote ID if a quote was created;
- skip/failure reason otherwise.

Do not add LLM prompt/raw-response storage here. That is PR-A4-3.

### 3.6 Preserve rejected quote semantics while preventing stale replay

Keep the A2 behavior that rejected quotes do not block a fresh quote at the same
price when a new provider message arrives.

But the same provider message ID must remain consumed even if the quote it
created was later rejected.

Required test scenario:

1. Process provider message `M1` and auto-create quote `Q1`.
2. Mark `Q1` as `QuoteState.rejected`.
3. Simulate restart/cache eviction by clearing any process-local queue/dedup
   state.
4. Redeliver the same provider message ID `M1`.
5. Assert:
   - no new quote is created;
   - LLM parse is not invoked for the redelivery;
   - durable message state shows the provider message was already consumed or
     duplicate-skipped deterministically.

### 3.7 Multi-worker / race safety

The implementation must be safe when two workers receive the same provider
message ID concurrently.

Required behavior:

- one insert wins;
- the loser observes the unique constraint / conflict and does not enqueue;
- no duplicate quote can be created.

Use SQLAlchemy `IntegrityError` handling or dialect-portable upsert logic. Do
not rely on Python locks or process-local sets for correctness.

---

## 4. Scope OUT

- Do not modify `docs/governance.md`.
- Do not implement PR-A4-3 LLM decision artifact persistence.
- Do not change LLM prompts, confidence thresholds, or quote parsing semantics.
- Do not change canonical RFQ ID extraction or phone consistency rules.
- Do not make rejected quotes block future distinct provider messages.
- Do not change outbound RFQ invitation evidence.
- Do not remove `InboundWebhookDelivery`; PR-A4-2 builds on it.
- Do not introduce provider-specific behavior beyond Meta/Twilio.
- Do not relax fail-closed signature behavior from PR-A4-1.

---

## 5. Acceptance Criteria

- [ ] Every extracted provider message is durably represented before enqueue.
- [ ] `(provider, provider_message_id)` is database-unique.
- [ ] Duplicate provider redelivery does not enqueue, parse with LLM, or mutate
  RFQ/quote state.
- [ ] Redelivery after process restart/cache eviction is duplicate-skipped.
- [ ] Redelivery after the originally created quote is rejected remains consumed
  and does not create a second active quote.
- [ ] Concurrent duplicate insertion is deterministic: one row wins and the
  loser does not enqueue/process.
- [ ] Durable message status transitions are persisted:
  `received -> processing -> processed|failed`.
- [ ] `processing_result` records final orchestrator status and any RFQ/quote
  identifiers produced by processing.
- [ ] Current canonical RFQ correlation and phone consistency behavior remains
  unchanged.
- [ ] PR-A4-3 LLM decision artifact persistence remains out of scope.
- [ ] `docs/governance.md` has no diff.

---

## 6. Required Tests

Add focused tests before broad runs.

Minimum expected coverage:

- `backend/tests/test_inbound_webhook_delivery.py` or a new
  `backend/tests/test_inbound_webhook_replay.py`
  - migration creates/drops `inbound_webhook_messages`;
  - unique `(provider, provider_message_id)` is enforced;
  - duplicate redelivery does not enqueue;
  - duplicate redelivery after restart/cache clear does not enqueue;
  - duplicate redelivery after quote rejection does not create a second quote;
  - concurrent duplicate insert handles `IntegrityError` deterministically;
  - processing status/result is persisted for processed, skipped, and failed
    paths.
- `backend/tests/test_rfq_orchestrator.py`
  - queue item with durable message ID updates `processing_status`;
  - auto-created quote stores `quote_id` on the durable message result;
  - non-quote / needs-human-review statuses are recorded without mutation.
- Existing adjacent coverage:
  - PR-A4-1 delivery persistence tests continue to pass;
  - webhook signature tests continue to pass;
  - canonical ID processing remains unchanged.

Run at minimum:

```bash
python -m pytest backend/tests/test_inbound_webhook_delivery.py -q
python -m pytest backend/tests/test_webhook_processor.py -q
python -m pytest backend/tests/test_phase5_whatsapp_llm.py -q
python -m pytest backend/tests/test_rfq_orchestrator.py -q
python -m pytest backend/tests/scripts/ -v
cd backend && python -m alembic heads
git diff --check
```

If the executor adds a new focused replay test file, include it explicitly in
the focused run. If broad backend tests are run, document the known local
Python 3.14 `backend/tests/test_ws.py` baseline separately and do not conflate it
with this PR.

---

## 7. Review Gates

Before opening the PR:

1. Confirm `docs/governance.md` is unchanged.
2. Confirm no PR-A4-3 LLM decision artifact implementation leaked into this
   branch.
3. Confirm rejected quotes still do not block distinct future provider messages.
4. Confirm replay protection is enforced by database uniqueness, not only by
   process-local structures.
5. Confirm no `--no-verify` push was used unless explicitly authorized and
   documented in the PR.
6. Open a PR against `main` with title:

```text
fix(audit-a4): PR-A4-2 durable inbound replay protection
```

PR body must include:

- finding closed: `J-A4-03`;
- migration revision ID;
- focused test results;
- Alembic head result;
- hook artifact summary;
- explicit statement that `docs/governance.md` has no diff;
- explicit statement that PR-A4-3 LLM decision artifacts remain out of scope.

Do not merge. Merge requires explicit authorization after CI and Codex Connector
review.
