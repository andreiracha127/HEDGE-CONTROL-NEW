# Phase A4 - PR-A4-3 Dispatch

## 1. Mission

Implement PR-A4-3 and close `J-A4-04`: persist immutable LLM decision artifacts
for inbound paths where a nondeterministic LLM decision can mutate RFQ/quote
state.

This is an auditability and reconstruction wave. It is not a prompt-tuning,
confidence-threshold, quote-parsing, or RFQ lifecycle behavior change.

The institutional invariant is:

> If an LLM-assisted decision can create a quote or decide that no quote should
> be created, the exact decision path must be reconstructible after commit.

The implementation must preserve the current enforcement gates:

- canonical RFQ correlation;
- non-trivial message filter;
- intent classification;
- quote parsing;
- confidence threshold;
- price-in-text guard;
- duplicate active quote guard;
- payload validation;
- durable inbound replay behavior from PR-A4-2.

## 2. Source Evidence

Authoritative finding:

- `docs/audits/2026-05-10-phase-a4-jury-verdict.md`
  - `J-A4-04 - Persist LLM decision artifacts for auto-created quotes`;
  - remediation boundary: persist an immutable LLM decision artifact linked to
    the inbound delivery and, when applicable, the created quote;
  - required fields include model id, prompt/input, raw response, parsed output,
    confidence, guard outcomes, and final decision.

Original auditor evidence:

- `docs/audits/2026-05-10-phase-a4-findings-gpt54.md`
  - `J-A4-GPT54-04`;
  - the LLM can mutate state by creating an `RFQQuote`;
  - current durable quote rows do not preserve model, prompt/input, raw
    response, parsed response, or confidence.
- `docs/audits/2026-05-10-phase-a4-findings-gemini.md`
  - `J-A4-GEMINI-04`;
  - the system uses the LLM as a nondeterministic black box to create a quote;
  - the exact prompt, raw JSON response, model version, and confidence are not
    stored with the database mutation.

Current code anchors at authoring time:

- `backend/app/services/llm_agent.py:40`
  - `CONFIDENCE_THRESHOLD = 0.85`.
- `backend/app/services/llm_agent.py:42-76`
  - classification and quote-parse system prompts.
- `backend/app/services/llm_agent.py:154-170`
  - `_call_openai_with_retry()` currently returns parsed JSON and discards the
    raw response content after `json.loads`.
- `backend/app/services/llm_agent.py:173-202`
  - `_call_openai()` determines the model and collapses the result into a
    parsed dictionary.
- `backend/app/services/llm_agent.py:223-244`
  - `classify_intent()` returns only normalized intent, confidence, and
    reasoning.
- `backend/app/services/llm_agent.py:247-304`
  - `parse_quote_message()` builds the RFQ context prompt, calls the LLM, and
    returns only `ParsedQuote`.
- `backend/app/services/llm_agent.py:360-373`
  - `should_auto_create_quote()` gates auto-quote creation.
- `backend/app/services/rfq_orchestrator.py`, `_process_single_message()`
  classification block
  - classification can return non-mutating statuses without durable LLM
    evidence.
- `backend/app/services/rfq_orchestrator.py`, `_process_single_message()`
  quote-parse block
  - quote parsing calls `LLMAgent.parse_quote_message()` and returns
    `llm_unavailable` without durable LLM evidence.
- `backend/app/services/rfq_orchestrator.py`, `_process_single_message()`
  auto-create guard block
  - confidence, price-in-text, duplicate quote, and auto-create gates decide
    whether an RFQ quote mutation occurs.
- `backend/app/services/rfq_orchestrator.py`, `_auto_create_quote()`
  - `_auto_create_quote()` validates and commits the quote.
- `backend/app/services/rfq_orchestrator.py`
  - `_claim_durable_message()` currently logs
    `orchestrator_legacy_inbound_without_delivery_message_id` and returns
    `None` for `delivery_message_id=None`;
  - because `process_inbound_queue()` treats `None` as "no claim/skip result",
    the current legacy branch falls through to `_process_single_message()`.
- `backend/app/models/inbound_webhook_message.py:22-102`
  - PR-A4-2 durable inbound message row exists and carries `processing_result`,
    `rfq_id`, and `quote_id`.
- `backend/app/models/quotes.py:29-59`
  - `RFQQuote` stores economic quote fields and lifecycle state, not the LLM
    decision artifact.

Current migration head at authoring time:

```bash
Push-Location backend; python -m alembic heads; Pop-Location
# 041_a4_inbound_webhook_messages (head)
```

## 3. Scope IN

### 3.1 Add immutable LLM decision artifact storage

Add a new SQLAlchemy model, registered in `backend/app/models/__init__.py`, for
immutable inbound LLM decision evidence.

Recommended file:

```text
backend/app/models/llm_decision_artifact.py
```

Recommended table:

```text
llm_decision_artifacts
```

Register the model explicitly in `backend/app/models/__init__.py`, mirroring the
existing inbound models:

```python
from app.models.llm_decision_artifact import LLMDecisionArtifact
```

and add `"LLMDecisionArtifact"` to `__all__`. At authoring time `__all__` is
not strictly alphabetical; keep the new entry near `InboundWebhookDelivery` and
`InboundWebhookMessage` to preserve the inbound evidence grouping.

The table must be durable, queryable, and linked to the inbound evidence chain.
At minimum it must include:

- `id` UUID primary key;
- `inbound_message_id` UUID, non-null FK to `inbound_webhook_messages.id`;
- `delivery_id` UUID, non-null FK to `inbound_webhook_deliveries.id`;
- `provider` and `provider_message_id` copied from the durable inbound message;
- `rfq_id` nullable FK to `rfqs.id`;
- `quote_id` nullable FK to `rfq_quotes.id`;
- `counterparty_id` nullable UUID FK to `counterparties.id`; it is nullable
  because some diagnostic paths may not have a resolved counterparty, but when
  an invitation is present it must be copied from `RFQInvitation.counterparty_id`;
- `schema_version` integer, default `1`;
- `llm_provider`, e.g. `openai`;
- `classification_model` nullable;
- `parse_model` nullable;
- `classification_prompt` nullable text or JSON message array;
- `classification_raw_response` nullable text;
- `classification_parsed` nullable JSON;
- `classification_error` nullable text;
- `parse_prompt` nullable text or JSON message array;
- `parse_raw_response` nullable text;
- `parse_parsed` nullable JSON;
- `parse_error` nullable text;
- `input_snapshot` JSON;
- `guard_outcomes` JSON;
- `final_decision`;
- `final_status` as `String(64)` or wider, because the longest required status
  at authoring time is `auto_quote_skipped_invalid_payload`;
- `created_at` timezone-aware timestamp.

`final_decision` domain:

- `allow_mutation`;
- `deny_no_mutation`.

`final_status` is the granular orchestrator outcome code. It must mirror the
status string returned in `processing_result`, for example:

- `auto_quote_created`;
- `counterparty_declined`;
- `counterparty_question`;
- `needs_human_review`;
- `llm_unavailable`;
- `hallucinated_price_blocked`;
- `duplicate_quote_skipped`;
- `auto_quote_skipped_incomplete`;
- `auto_quote_skipped_invalid_payload`;
- `auto_quote_failed`.

Enforce both domains in code and, where portable, in DDL:

- add SQLAlchemy `@validates("final_decision")`;
- add SQLAlchemy `@validates("final_status")`;
- add `CheckConstraint` for `final_decision`;
- add `CheckConstraint` for `final_status`;
- if a CHECK shape is not portable in Alembic for SQLite, guard it by dialect
  and keep the model validators as the SQLite/test enforcement layer.

Use `json_payload_type` from `backend/app/models/inbound_webhook_delivery.py`
for JSON columns, matching PR-A4-1/2.
The SQLAlchemy model class must import and use that shared type directly for
all JSON columns. The inline `with_variant` fallback below applies only to the
Alembic migration, where application imports may be less reliable.

`counterparty_id` is intentionally stored both as a relational FK and inside
`input_snapshot`: the FK supports joins, while the JSON snapshot preserves the
point-in-time audit input independently of later relational changes.

Artifact rows are immutable after insert. Do not implement bulk update paths for
`LLMDecisionArtifact`; SQLAlchemy `@validates` guards are an insert-time safety
layer and do not replace database constraints on engines that support them.

Do not add these fields to `RFQQuote` as nullable metadata columns. A dedicated
artifact table is required so non-mutating LLM decisions are also reconstructible
and so quote economic rows remain clean.

### 3.2 Create migration 042

Create:

```text
backend/alembic/versions/042_a4_llm_decision_artifacts.py
```

The revision ID must be at or below Alembic's 32-character version table limit.
`042_a4_llm_decision_artifacts` is 29 characters and is the expected revision
ID if no newer migration lands first.

Migration requirements:

- create `llm_decision_artifacts`;
- add FK to `inbound_webhook_messages.id`;
- add FK to `inbound_webhook_deliveries.id`;
- add nullable FK to `rfqs.id`;
- add nullable FK to `rfq_quotes.id`;
- add useful indexes for:
  - `inbound_message_id`;
  - `delivery_id`;
  - `rfq_id`;
  - `quote_id`;
  - `(provider, provider_message_id)`;
  - `final_status`;
- enforce one artifact per `inbound_message_id` unless the implementation
  explicitly models multiple LLM attempts. If multiple attempts are modeled,
  add an `attempt_number` and a uniqueness constraint on
  `(inbound_message_id, attempt_number)`;
- downgrade removes all introduced objects cleanly.

Column sizing requirement:

- `final_decision`: `String(32)` or wider;
- `final_status`: `String(64)` or wider.

JSON columns in the migration `op.create_table()` must use the same portable
type shape as PR-A4-1/2:

```python
JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")
```

Do not use raw `JSONB()` directly in the migration, because that breaks the
SQLite test dialect. Import the shared `json_payload_type` only if the migration
environment can resolve application imports reliably; otherwise replicate the
`with_variant` expression inline in the migration.

SQLite tests must exercise the same uniqueness invariant. If PostgreSQL-only
CHECK constraints are added, guard them by dialect and enforce the same status
domain in the SQLAlchemy model with `@validates`.
Follow the concrete 041 migration pattern:

```python
check_constraints = [
    sa.CheckConstraint(
        "final_decision IN ('allow_mutation', 'deny_no_mutation')",
        name="ck_llm_decision_artifacts_final_decision",
    ),
]
if dialect_name == "postgresql":
    check_constraints.append(
        sa.CheckConstraint(
            "final_status IN ('auto_quote_created', 'counterparty_declined', "
            "'counterparty_question', 'needs_human_review', 'llm_unavailable', "
            "'hallucinated_price_blocked', 'duplicate_quote_skipped', "
            "'auto_quote_skipped_incomplete', "
            "'auto_quote_skipped_invalid_payload', 'auto_quote_failed')",
            name="ck_llm_decision_artifacts_final_status",
        )
    )
```

Then pass `*check_constraints` to `op.create_table(...)`, matching the style in
`backend/alembic/versions/041_a4_inbound_webhook_messages.py`. If the final
status CHECK is made portable and passes SQLite migration tests, a dialect guard
is not required; the model validators remain mandatory either way.

### 3.3 Preserve raw LLM response and prompt/input

Refactor `backend/app/services/llm_agent.py` so classification and quote parsing
can return both the current semantic result and an evidence trace.

The trace must include:

- configured model id actually sent to OpenAI;
- provider name;
- system prompt;
- user prompt;
- outbound messages array or equivalent prompt structure;
- raw `completion.choices[0].message.content` string before JSON parsing;
- parsed JSON dictionary after `json.loads`;
- normalized Pydantic result returned to the orchestrator;
- error type/message for LLM unavailability or JSON parse failure;
- request parameters that affect output, including `temperature`,
  `max_tokens`, and `response_format`.

Do not store API keys, Authorization headers, environment variables, or client
transport internals.

Maintain the existing public behavior of:

- `LLMAgent.classify_intent()`;
- `LLMAgent.parse_quote_message()`;
- `LLMAgent.should_auto_create_quote()`.

Preferred approach:

- add new trace-returning helpers or result wrappers used by the orchestrator;
- keep legacy public methods as compatibility wrappers for existing tests.

Do not change prompt text, confidence threshold, retry count, timeout, or parsing
semantics unless a test proves the change is mechanically required to preserve
existing behavior.

### 3.4 Persist an artifact for every LLM-assisted inbound decision

In `backend/app/services/rfq_orchestrator.py`, persist one decision artifact for
every inbound durable message that reaches LLM-assisted decisioning.

Required cases:

- classification returns non-quote:
  - `counterparty_declined`;
  - `counterparty_question`;
  - `needs_human_review`;
- classification unavailable and quote parsing is attempted;
- quote parsing unavailable:
  - `llm_unavailable`;
- parsed result below auto-create threshold:
  - `needs_human_review`;
- post-parse intent returns non-quote:
  - `counterparty_declined`;
  - `counterparty_question`;
- hallucinated price blocked;
- duplicate active quote skipped;
- incomplete auto-quote payload skipped (`auto_quote_skipped_incomplete`);
- invalid auto-quote payload skipped (`auto_quote_skipped_invalid_payload`);
- auto-quote creation failed;
- auto-quote created.

Messages that do not reach the LLM do not need an LLM artifact:

- no canonical RFQ;
- ambiguous canonical RFQ;
- missing RFQ;
- sender/phone mismatch;
- RFQ state not eligible;
- trivial message skipped before classification.

For each artifact, `input_snapshot` must include:

- inbound message id;
- delivery id sourced from `InboundWebhookMessage.delivery_id`, not from
  `WhatsAppInboundMessage.delivery_message_id`:

  ```python
  delivery_id = durable.delivery_id
  ```

- provider;
- provider message id;
- original text;
- downstream stripped text used for LLM;
- sender phone;
- sender name;
- RFQ number;
- RFQ context string passed to the quote parser;
- invitation id if available;
- counterparty id if available.

For each artifact, `guard_outcomes` must include boolean or structured entries
for:

- classification attempted;
- classification intent;
- classification confidence;
- parse attempted;
- parse intent;
- parse confidence;
- `CONFIDENCE_THRESHOLD`;
- `should_auto_create_quote`;
- price-in-text check result;
- duplicate active quote check result;
- payload completeness;
- payload validation;
- final allow/deny decision;
- failure/skip reason when no mutation occurs.

Use JSON-serializable primitives only. Convert `Decimal`, UUID, datetime, and
enum values to strings before insertion. For `Decimal`, use `str(value)` unless
the existing code already canonicalizes a more specific representation.

### 3.5 Make quote creation and artifact persistence atomic

For the `auto_quote_created` path, the artifact must be inserted before or
atomically with the quote commit.

Required behavior:

- if quote creation succeeds, the artifact row must link to `quote_id`;
- if artifact insertion fails, the quote and RFQ state transition must not
  commit;
- if quote creation fails before commit, the artifact may record
  `auto_quote_failed` only if doing so does not falsely imply a committed quote;
- do not commit a quote and then attempt artifact persistence in a separate
  best-effort transaction.

`RFQService.submit_quote()` currently flushes the quote before the orchestrator
commits. Use that boundary to link the artifact to `quote.id` inside the same
transaction.

Concrete placement requirement:

- call `RFQService.submit_quote(session, rfq.id, quote_payload)`;
- after it returns, `quote.id` is available because `submit_quote()` flushes;
- insert the `LLMDecisionArtifact` row into the same `session` after that flush
  and before `session.commit()`;
- call the single existing `session.commit()` only after both quote and artifact
  are staged;
- the existing `session.commit()` call inside `_auto_create_quote()` must be
  relocated to after `session.add(artifact)`. This is a relocation of the single
  commit, not an added second commit;
- retain the existing pre-commit scalar snapshot pattern before constructing the
  artifact. The current code snapshots attributes before commit to avoid
  expire-on-commit refresh races; do not remove that protection.
- merged shape:
  - call `RFQService.submit_quote(...)`;
  - snapshot `quote_id_str = str(quote.id)`, `counterparty_id_str`,
    `quote_price_str`, and any other scalar values needed after commit;
  - build artifact payload from those snapshots and from already-available LLM
    trace data;
  - `session.add(artifact)`;
  - relocated single `session.commit()`;
- if artifact construction or insertion raises, do not call `session.commit()`;
  the transaction path must `session.rollback()` so the flushed quote and
  artifact are both rolled back;
- widen rollback coverage with a clear exception shape:
  - wrap artifact payload construction separately and catch only
    `(TypeError, ValueError)` there;
  - for the submit/insert/commit DB block, replace the current
    `(HTTPException, IntegrityError, OperationalError)` tuple with
    `(HTTPException, SQLAlchemyError)`;
  - do not list `IntegrityError` or `OperationalError` separately next to
    `SQLAlchemyError`, because they are subclasses;
- do not add a second post-commit artifact write. The current `_auto_create_quote`
  shape must be restructured only enough to stage the artifact and move the
  existing commit after `session.add(artifact)`.

Expected exception shape:

```python
try:
    quote = RFQService.submit_quote(session, rfq.id, quote_payload)
    quote_id_str = str(quote.id)
    counterparty_id_str = str(invitation.counterparty_id)
    quote_price_str = str(quote.fixed_price_value)
    try:
        artifact_payload = build_artifact_payload(
            quote_id=quote.id,
            quote_id_str=quote_id_str,
            counterparty_id=counterparty_id_str,
            quote_price=quote_price_str,
            classification_intent=classification.intent.value if classification else None,
            classification_confidence=classification.confidence if classification else None,
            ...
        )
    except (TypeError, ValueError) as exc:
        raise ArtifactPayloadError(str(exc)) from exc
    artifact = LLMDecisionArtifact(quote_id=quote.id, **artifact_payload)
    session.add(artifact)
    session.commit()
except (HTTPException, SQLAlchemyError, ArtifactPayloadError) as exc:
    session.rollback()
    return {"status": "auto_quote_failed", "error": str(exc), ...}
```

### 3.6 Remove PR-A4-2 legacy inbound path

PR-A4-2 intentionally left a deployment-window path for
`delivery_message_id=None`. PR-A4-2's dispatch made PR-A4-3 responsible for
removing that legacy path.

In PR-A4-3:

- `RFQOrchestrator.process_inbound_queue()` must not process inbound messages
  without `delivery_message_id`;
- legacy messages without durable inbound identity must not invoke LLM parsing;
- no legacy message may create or mutate quotes;
- fix the current fall-through explicitly:
  - `_claim_durable_message()` must return a non-`None` result dictionary for
    `delivery_message_id=None`, for example:

    ```python
    {
        "message_id": msg.message_id,
        "status": "legacy_missing_delivery_message_id",
        "from_phone": msg.from_phone,
    }
    ```

  - do not leave the current `return None` behavior for the legacy case, because
    `None` means "continue into processing" in the caller;
  - the caller already has `if claim is not None: results.append(claim); continue`;
    once the legacy branch returns a dictionary, that existing caller branch will
    append the skip result and bypass `_process_single_message()`;
  - while the legacy branch returns `None`, the caller proceeds into
    `_process_single_message()`; that is the bug PR-A4-3 must close;
  - `_finalize_durable_message()` already has an early-return guard for missing
    `delivery_message_id`; do not add a finalize call for the legacy case;
  - the required code change is specifically to make the legacy branch in
    `_claim_durable_message()` return the structured result instead of `None`;
  - `mark_message_finished(msg)` must still run via the existing `finally`;
- tests that still enqueue bare `WhatsAppInboundMessage` objects must be updated
  to create durable inbound message rows and set `delivery_message_id`;
- keep a structured error/skip result if needed for defensive programming, but
  do not continue into `_process_single_message()` for legacy messages.

This is not a behavior relaxation. It closes the deployment boundary created by
PR-A4-2.

### 3.7 Keep manual quote creation out of scope

Manual quote creation through API routes is not LLM-assisted and is outside
`J-A4-04`. Do not force manual quotes to have LLM artifacts.

The invariant is narrower:

> Any LLM-assisted inbound decision that can create or block an auto-created
> quote must be reconstructible.

## 4. Scope OUT

- Do not modify `docs/governance.md`.
- Do not change LLM prompt wording except to expose the exact existing prompt as
  persisted evidence.
- Do not change `CONFIDENCE_THRESHOLD`.
- Do not change `LLMAgent.should_auto_create_quote()` semantics.
- Do not change price-in-text behavior.
- Do not change canonical RFQ correlation or phone consistency rules.
- Do not change duplicate quote semantics.
- Do not make rejected quotes block future distinct provider messages.
- Do not implement outbound provider-response evidence.
- Do not alter manual quote creation behavior.
- Do not add a best-effort fallback that creates quotes without artifacts.

## 5. Acceptance Criteria

- [ ] `llm_decision_artifacts` exists with durable links to inbound delivery,
  inbound message, RFQ, and quote when applicable.
- [ ] Auto-created quote path commits quote and artifact atomically.
- [ ] If artifact persistence fails, no auto-created quote is committed.
- [ ] Artifact captures model id, provider, prompts/input, raw output, parsed
  output, confidence, guard outcomes, and final decision.
- [ ] Low-confidence / needs-human-review LLM paths persist a non-mutating
  artifact when a durable inbound message exists.
- [ ] `llm_unavailable` after RFQ correlation persists a diagnostic artifact
  when a durable inbound message exists.
- [ ] Hallucinated-price and duplicate-quote blocked paths persist deny
  artifacts and do not mutate quote state.
- [ ] Legacy `delivery_message_id=None` inbound messages do not reach LLM
  parsing and cannot create quotes.
- [ ] Existing confidence threshold, prompt semantics, price-in-text guard, and
  duplicate quote guard are unchanged.
- [ ] PR-A4-1 inbound delivery evidence and PR-A4-2 durable replay semantics
  remain intact.
- [ ] `docs/governance.md` has no diff.

## 6. Required Tests

Add focused tests before broad runs.

Minimum expected coverage:

- New model/migration tests:
  - migration 042 upgrades and downgrades cleanly;
  - uniqueness invariant for `inbound_message_id` or
    `(inbound_message_id, attempt_number)` is enforced;
  - JSON fields accept dictionaries and reject non-serializable raw values via
    service-level conversion.
- `backend/tests/test_rfq_orchestrator.py`
  - auto-created quote persists one artifact linked to `inbound_message_id`,
    `delivery_id`, `rfq_id`, and `quote_id`;
  - artifact includes parse model, prompt/input, raw output, parsed output,
    confidence, guard outcomes, and `final_decision="allow_mutation"`;
  - low-confidence parsed quote records `final_decision="deny_no_mutation"` and
    no quote is created;
  - `LLMUnavailableError` after RFQ correlation records diagnostic artifact and
    no quote is created;
  - hallucinated price blocked records deny artifact and no quote is created;
  - duplicate active quote skipped records deny artifact with existing quote id;
  - artifact persistence failure rolls back quote creation;
  - `delivery_message_id=None` message does not invoke LLM and does not create a
    quote.
- Existing adjacent tests:
  - PR-A4-1 inbound webhook delivery tests continue to pass;
  - PR-A4-2 durable replay tests continue to pass;
  - LLM agent tests continue to pass without requiring live OpenAI access.

Run at minimum:

```bash
python -m pytest backend/tests/test_rfq_orchestrator.py -q
python -m pytest backend/tests/test_webhook_processor.py -q
python -m pytest backend/tests/test_inbound_webhook_delivery.py -q
python -m pytest backend/tests/test_phase5_whatsapp_llm.py -q
python -m pytest backend/tests/scripts/ -v
Push-Location backend; python -m alembic heads; Pop-Location
git diff --check
```

If schema/OpenAPI files change unexpectedly, stop and explain why. This wave
should not normally require frontend API regeneration unless an API surface is
deliberately added, which is not part of this dispatch.

## 7. Review Gates

Before push:

1. Confirm `docs/governance.md` is unchanged.
2. Confirm `CONFIDENCE_THRESHOLD` is unchanged.
3. Confirm prompt text is unchanged unless the diff is purely mechanical evidence
   plumbing.
4. Confirm no manual quote route now requires LLM artifact.
5. Confirm no auto-created quote can commit without an artifact.
6. Confirm no `delivery_message_id=None` message reaches LLM parsing.
7. Push normally so hook v2 reviews the implementation. Do not use
   `--no-verify` unless explicitly authorized and documented.

Open a PR against `main` with title:

```text
fix(audit-a4): PR-A4-3 llm decision reconstruction
```

PR body must include:

- finding closed: `J-A4-04`;
- migration revision ID;
- artifact table name;
- focused test results;
- Alembic head result;
- hook artifact summary;
- explicit statement that `docs/governance.md` has no diff;
- explicit statement that LLM prompts and confidence threshold are unchanged;
- explicit statement that manual quote creation remains out of scope.

Do not merge. Merge requires explicit authorization after CI and Codex Connector
review.
