# Phase A4 Jury Verdict

## Executive Summary

- Total accepted findings: 4
- Tier 1: 4
- Tier 2: 0
- Tier 3: 0
- Tier 4: 0
- Rejected auditor findings: 1
- Fresh jury findings: 0

## Accepted Findings

### J-A4-01 - Fail closed when inbound webhook secrets are absent

**Source:** GPT54 J-A4-GPT54-01
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `backend/app/api/routes/webhooks.py:115` - Meta authenticity is gated by a runtime `WHATSAPP_APP_SECRET` environment lookup.
- `backend/app/api/routes/webhooks.py:117` - Meta signature validation only runs when that secret is configured.
- `backend/app/api/routes/webhooks.py:130` - a present Meta signature with no configured secret only logs a warning.
- `backend/app/api/routes/webhooks.py:133` - a missing Meta signature with no configured secret also only logs a warning.
- `backend/app/api/routes/webhooks.py:143` - after the warning path, the Meta payload is still extracted.
- `backend/app/api/routes/webhooks.py:145` - the extracted Meta message is enqueued for downstream processing.
- `backend/app/api/routes/webhooks.py:161` - Twilio authenticity is gated by a runtime `TWILIO_AUTH_TOKEN` environment lookup.
- `backend/app/api/routes/webhooks.py:163` - Twilio signature validation only runs when that token is configured.
- `backend/app/api/routes/webhooks.py:178` - absent Twilio token only logs `webhook_twilio_no_signature_verification`.
- `backend/app/api/routes/webhooks.py:183` - the Twilio message is still enqueued after that warning path.
- `backend/app/core/config.py:110` - WhatsApp integration settings are plain optional fields.
- `backend/app/core/config.py:118` - Twilio integration settings are plain optional fields.
- `backend/app/core/config.py:67` - the existing production/staging fail-closed startup barrier is scoped to `AUDIT_SIGNING_KEY`, not webhook authenticity secrets.
- `backend/tests/test_phase5_whatsapp_llm.py:390` - the suite explicitly patches `WHATSAPP_APP_SECRET` to an empty string.
- `backend/tests/test_phase5_whatsapp_llm.py:400` - the no-secret Meta webhook request is posted through the public route.
- `backend/tests/test_phase5_whatsapp_llm.py:402` - the expected response is still HTTP 200.

**Failure mode:**
In a production-like deployment that boots without the Meta app secret or Twilio auth token, an unauthenticated caller can send a payload containing a known recipient phone and `RFQ#<rfq_number>`. The route logs the missing verification condition, extracts the message, enqueues it, and the background RFQ orchestrator can continue into canonical correlation and high-confidence quote creation.

**Governance impact:**
This violates `docs/governance.md:115` because inbound provider messages cease to be trustworthy evidence, and `docs/governance.md:121` because canonical correlation is exposed to spoofed traffic rather than authenticated provider deliveries.

**Remediation boundary:**
Add a production/staging startup barrier for the configured inbound provider and reject inbound webhook traffic when the active provider lacks its required authenticity secret. Preserve test/local explicit bypasses only under non-production environment markers.

### J-A4-02 - Persist raw inbound webhook envelopes before acknowledgement

**Source:** GPT54 J-A4-GPT54-02 | Gemini J-A4-GEMINI-01
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `backend/app/api/routes/webhooks.py:112` - Meta reads the raw body only into local memory.
- `backend/app/api/routes/webhooks.py:136` - Meta parses that body directly into transient JSON.
- `backend/app/api/routes/webhooks.py:143` - Meta reduces the payload to extracted messages.
- `backend/app/api/routes/webhooks.py:145` - Meta enqueues simplified `WhatsAppInboundMessage` objects.
- `backend/app/api/routes/webhooks.py:151` - Meta returns `{"status": "ok"}` without a durable inbound-envelope write.
- `backend/app/api/routes/webhooks.py:156` - Twilio reads form data only into local memory.
- `backend/app/api/routes/webhooks.py:157` - Twilio reduces the request to stringified form params.
- `backend/app/api/routes/webhooks.py:181` - Twilio extracts simplified messages from those params.
- `backend/app/api/routes/webhooks.py:183` - Twilio enqueues those simplified messages.
- `backend/app/api/routes/webhooks.py:189` - Twilio returns `{"status": "ok"}` without a durable inbound-envelope write.
- `backend/app/services/webhook_processor.py:13` - the module documents the queue as an in-process deque.
- `backend/app/services/webhook_processor.py:37` - `_message_queue` is a process-local `deque`.
- `backend/app/schemas/whatsapp.py:51` - `WhatsAppInboundMessage` contains only parsed message fields.
- `backend/app/schemas/whatsapp.py:54` - the schema keeps provider message id.
- `backend/app/schemas/whatsapp.py:55` - the schema keeps normalized sender phone.
- `backend/app/schemas/whatsapp.py:57` - the schema keeps text, not raw body, headers, signature context, or provider envelope.

**Failure mode:**
After a provider receives HTTP 200 from this route, the system has no durable copy of the exact Meta JSON body, Twilio form payload, request headers, signature inputs, signature decision, or full provider envelope. A crash, restart, worker recycle, queue eviction, or later dispute leaves auditors with neither the raw evidence nor the inputs needed to reconstruct how authenticity and parsing were evaluated.

**Governance impact:**
This directly violates `docs/governance.md:115`: messages are evidence, not transient UI or queue artifacts. It also undermines A4 raw inbound durability and reconstruction.

**Remediation boundary:**
Introduce a durable inbound webhook table or equivalent append-only store. Write one record per provider delivery before queueing or parsing, including provider, raw payload/body or form params, relevant headers/signature metadata, provider message id, sender, received timestamp, parse status, and later processing outcome.

### J-A4-03 - Make inbound replay protection durable and state-independent

**Source:** GPT54 J-A4-GPT54-03 | Gemini J-A4-GEMINI-02
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `backend/app/services/webhook_processor.py:39` - the duplicate message id retention limit is an in-process cap of 5,000 ids.
- `backend/app/services/webhook_processor.py:40` - `_seen_message_ids` is a process-local `deque`.
- `backend/app/services/webhook_processor.py:41` - `_seen_set` is a process-local `set`.
- `backend/app/services/webhook_processor.py:49` - duplicate suppression checks only the process-local set.
- `backend/app/services/webhook_processor.py:53` - ids are evicted once the local cap is reached.
- `backend/app/services/webhook_processor.py:57` - accepted ids are added only to local memory.
- `backend/app/models/quotes.py:17` - `QuoteState` explicitly supports preserved quote lifecycle state.
- `backend/app/models/quotes.py:25` - `active` is one quote state.
- `backend/app/models/quotes.py:26` - `rejected` is another preserved quote state.
- `backend/app/services/rfq_orchestrator.py:499` - duplicate quote suppression checks existing quotes only after LLM parsing.
- `backend/app/services/rfq_orchestrator.py:508` - that suppression only counts `QuoteState.active` rows.
- `backend/app/services/rfq_orchestrator.py:527` - when no active duplicate is found, the flow proceeds to auto-create a quote.
- `backend/app/services/rfq_orchestrator.py:662` - auto-creation calls `RFQService.submit_quote`.
- `backend/app/services/rfq_orchestrator.py:675` - the auto-created quote is committed.

**Failure mode:**
A provider message can create quote `Q`; the desk can later reject `Q`, preserving it as `QuoteState.rejected`. If the same provider message is redelivered after a restart, multi-worker handoff, or local seen-id eviction, the in-memory dedup guard no longer knows it was consumed. The active-only duplicate quote check then ignores the preserved rejected quote and permits a new active quote from the same stale provider evidence.

**Governance impact:**
This violates deterministic processing and A4 replay semantics. A single provider delivery can be consumed more than once across process lifetimes and can recreate institutional quote state after the desk already rejected the first quote.

**Remediation boundary:**
Persist immutable inbound delivery keys and enforce one-time consumption independently of process memory and quote lifecycle state. The durable inbound record from J-A4-02 can host a unique provider-delivery constraint and processing status, but the replay invariant must be explicit.

### J-A4-04 - Persist LLM decision artifacts for auto-created quotes

**Source:** GPT54 J-A4-GPT54-04 | Gemini J-A4-GEMINI-04
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `backend/app/services/llm_agent.py:160` - the OpenAI completion call is made in memory.
- `backend/app/services/llm_agent.py:167` - only the response message content is extracted.
- `backend/app/services/llm_agent.py:170` - the raw content is immediately parsed to JSON and returned.
- `backend/app/services/llm_agent.py:190` - the prompt messages are built as local variables.
- `backend/app/services/llm_agent.py:196` - `_call_openai` returns only the parsed JSON result.
- `backend/app/services/llm_agent.py:263` - quote parsing builds the user prompt in memory.
- `backend/app/services/llm_agent.py:268` - quote parsing calls the LLM and receives only parsed JSON.
- `backend/app/services/llm_agent.py:295` - `ParsedQuote` is returned without raw model response or prompt persistence.
- `backend/app/services/rfq_orchestrator.py:450` - the orchestrator invokes `LLMAgent.parse_quote_message`.
- `backend/app/services/rfq_orchestrator.py:475` - the confidence gate can authorize automatic quote creation.
- `backend/app/services/rfq_orchestrator.py:662` - the quote is created through `RFQService.submit_quote`.
- `backend/app/services/rfq_orchestrator.py:675` - the quote is committed by the background worker.
- `backend/app/models/quotes.py:29` - `RFQQuote` is the durable quote model.
- `backend/app/models/quotes.py:41` - the quote model stores price value.
- `backend/app/models/quotes.py:46` - the quote model stores price unit.
- `backend/app/models/quotes.py:47` - the quote model stores pricing convention.
- `backend/app/models/quotes.py:48` - the quote model stores received timestamp.
- `backend/app/models/quotes.py:50` - the quote model stores lifecycle state, but no model id, prompt/input, raw response, parsed response, confidence, or decision reason.
- `backend/app/api/routes/rfqs.py:260` - manual quote creation is covered by a route-level audit dependency.
- `backend/app/api/routes/rfqs.py:268` - manual quote creation calls the same `RFQService.submit_quote` service.
- `backend/app/api/routes/rfqs.py:271` - manual quote creation marks an audit success before committing the audit row.

**Failure mode:**
A high-confidence inbound message can create and commit an `RFQQuote` in the background worker. After commit, the database contains the economic quote fields but not the model id, prompt, stripped inbound text, RFQ context, raw response, parsed JSON, confidence, price-in-text decision, or allow/deny rationale. If the quote is disputed, the institution cannot reconstruct why a nondeterministic LLM decision was allowed to mutate RFQ state.

**Governance impact:**
This violates `docs/governance.md:115` and the A4 reconstruction boundary for LLM-assisted state mutation. The quote row is durable, but the decision artifact that caused it is not.

**Remediation boundary:**
Persist an immutable LLM decision artifact linked to the inbound delivery and, when applicable, the created quote. It must be written before or atomically with quote commit and include model id, prompt/input, raw response, parsed output, confidence, guard outcomes, and final decision.

## Rejected Findings

### J-A4-GEMINI-03 - Regex stripping can alter economic sign for negative spreads

**Disposition:** Rejected
**Reason:** The concrete example is not a validated failure mode in current code. `_CANONICAL_ID_RE` intentionally strips `RFQ#<rfq_number>` plus a spaced outbound separator pattern (`space + em/en dash + space`) at `backend/app/services/rfq_orchestrator.py:116`. `_strip_canonical_id` then applies that regex at `backend/app/services/rfq_orchestrator.py:132`. The tested A2 boundary preserves explicit economic signs: `backend/tests/test_inbound_canonical_id.py:208` verifies `RFQ#... — -5 USD/MT` becomes `-5 USD/MT`, and `backend/tests/test_inbound_canonical_id.py:212` verifies compact em/en dash signs like `RFQ#... —5 USD/MT` and `RFQ#... –5 USD/MT` are preserved. The jury also ran those focused tests and got `3 passed`. A spaced em dash after the canonical id is the system's outbound separator convention, not concrete evidence of a negative price sign.

## Subsumed Findings

- Gemini J-A4-GEMINI-01 is subsumed into J-A4-02.
- GPT54 J-A4-GPT54-02 is subsumed into J-A4-02.
- Gemini J-A4-GEMINI-02 is subsumed into J-A4-03.
- GPT54 J-A4-GPT54-03 is subsumed into J-A4-03.
- Gemini J-A4-GEMINI-04 is subsumed into J-A4-04.
- GPT54 J-A4-GPT54-04 is subsumed into J-A4-04.

## Cross-Phase Deferrals

None. The accepted items are Phase A4 integration, raw inbound durability, replay, and LLM decision reconstruction issues. Outbound provider-response granularity is not promoted as a separate deferral because `RFQInvitation` already preserves queued/sent/failed status, provider message id, failure reason, body, recipient, purpose, and timestamps for the primary outbound evidence boundary.

## Recommended Remediation Waves

### PR-A4-1 - Inbound webhook trust and durability
- Findings: J-A4-01, J-A4-02
- Scope boundary: Add production/staging fail-closed config validation for the active inbound provider's authenticity secret and persist raw inbound delivery records before extraction, queueing, or acknowledgement.
- Required verification: Meta/Twilio no-secret production requests reject; invalid/missing signatures reject; valid signed requests create durable inbound records before queueing; local/test bypasses remain explicit and covered.

### PR-A4-2 - Durable replay and one-time consumption
- Findings: J-A4-03
- Scope boundary: Add durable provider-delivery keys, uniqueness, processing status, and idempotent replay behavior. Do not couple replay suppression to active quote state.
- Required verification: provider redelivery after restart or cache eviction does not create a second quote; redelivery after quote rejection remains consumed; multi-worker duplicate insertion is rejected deterministically.

### PR-A4-3 - LLM decision reconstruction for quote mutations
- Findings: J-A4-04
- Scope boundary: Persist immutable LLM decision artifacts for classification/parsing paths that can create quotes, linked to inbound delivery and quote id. Keep the current confidence and price-in-text gates, but record their decisions.
- Required verification: auto-created quotes have model, prompt/input, raw output, parsed output, confidence, guard outcomes, and final allow/deny record; low-confidence and LLM-unavailable paths remain non-mutating but record diagnosis where an inbound delivery exists.

## Anti-Findings Confirmed

- Outbound initial invitation body equality is safe on the inspected path: `backend/app/services/rfq_service.py:619` prefixes the canonical id before persistence, `backend/app/services/rfq_service.py:631` stores the exact `message_body`, and `backend/app/services/rfq_service.py:652` sends `row.message_body`.
- Outbound refresh/reject lifecycle rows preserve the same boundary: `backend/app/services/rfq_service.py:1026` builds a prefixed refresh body, `backend/app/services/rfq_service.py:1040` stores it, and `backend/app/services/rfq_service.py:1054` sends the same body; quote rejection builds/stores before send at `backend/app/services/rfq_service.py:1151` and `backend/app/services/rfq_service.py:1168`.
- Canonical inbound correlation remains RFQ-id-first: `backend/app/services/rfq_orchestrator.py:284` extracts canonical ids, `backend/app/services/rfq_orchestrator.py:286` rejects missing ids, `backend/app/services/rfq_orchestrator.py:298` parks multiple distinct ids, `backend/app/services/rfq_orchestrator.py:312` looks up by `rfq_number`, and the phone lookup at `backend/app/services/rfq_orchestrator.py:358` occurs only after canonical RFQ resolution.
- LLM confidence is an enforcement gate, not only a log decoration: `backend/app/services/llm_agent.py:360` defines `should_auto_create_quote`, `backend/app/services/llm_agent.py:367` requires quote intent, `backend/app/services/llm_agent.py:368` requires confidence above threshold, and `backend/app/services/rfq_orchestrator.py:475` only enters auto-create after that gate.
- Hallucinated prices are blocked before quote creation: `backend/app/services/rfq_orchestrator.py:481` checks that the parsed price appears in the downstream text, and `backend/app/services/rfq_orchestrator.py:490` returns `hallucinated_price_blocked` instead of mutating state.
