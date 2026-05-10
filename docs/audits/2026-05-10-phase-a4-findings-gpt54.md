# Phase A4 - Stage 1 Findings - GPT 5.4

## Finding J-A4-GPT54-01 - Fail closed when webhook secrets are absent

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/api/routes/webhooks.py:117-133` - Meta inbound accepts the request when `WHATSAPP_APP_SECRET` is absent; it only logs `webhook_no_hmac_verification` / `webhook_signature_present_but_secret_not_configured` and continues.
- `backend/app/api/routes/webhooks.py:163-179` - Twilio inbound accepts the request when `TWILIO_AUTH_TOKEN` is absent; it only logs `webhook_twilio_no_signature_verification` and continues.
- `backend/app/core/config.py:106-122` - webhook secrets and callback auth settings are plain optional fields; there is no production/staging fail-closed validator comparable to the audit-signing guard.
- `backend/tests/test_phase5_whatsapp_llm.py:390-408` - the current test suite explicitly expects `POST /webhooks/whatsapp` to return `200` and enqueue a message with `WHATSAPP_APP_SECRET=""`.

**Failure mode:**
In a production or staging deployment that boots without the Meta app secret or Twilio auth token, any caller that knows an active recipient phone and `RFQ#<rfq_number>` can forge an inbound payload. The forged message then enters the normal orchestrator path, can pass canonical-id correlation, and can auto-create an institutional quote if the LLM returns a high-confidence parse. This is not a degraded observability mode; it is an unauthenticated economic mutation path.

**Governance impact:**
Violates `docs/governance.md:115` and `docs/governance.md:121`. Messages stop being trustworthy evidence, and inbound correlation becomes vulnerable to unauthenticated spoofed payloads.

**Recommended remediation boundary:**
Add an environment-scoped startup barrier for inbound webhook secrets/tokens and reject webhook traffic whenever the configured provider lacks its required authenticity secret in production-like environments.

## Finding J-A4-GPT54-02 - Persist the raw inbound envelope before queueing

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/api/routes/webhooks.py:112-150` - Meta inbound reads the raw body, verifies it in memory, extracts text messages, enqueues simplified `WhatsAppInboundMessage` objects, and returns `200`; there is no durable write of the raw request body, headers, signature status, or provider envelope.
- `backend/app/api/routes/webhooks.py:156-188` - Twilio inbound reduces the form body to `form_params`, extracts simplified messages, enqueues them, and returns `200`; again there is no durable raw-envelope persistence.
- `backend/app/services/webhook_processor.py:13-15` - the module doc states the inbound queue is an in-process deque "for now".
- `backend/app/services/webhook_processor.py:37-65` - both the queue and duplicate-message tracking live only in process memory.

**Failure mode:**
After the endpoint returns `200`, the system has no durable copy of the exact Meta JSON body, Twilio form payload, provider headers, signature-verification inputs, or full provider message envelope. A crash, restart, queue eviction, or later dispute leaves only the reduced `WhatsAppInboundMessage` projection in memory, so auditors cannot reconstruct what was actually received or how authenticity was evaluated before parsing/classification.

**Governance impact:**
Violates `docs/governance.md:115`. Inbound provider messages are operational evidence, but the implementation discards the raw evidence surface before making LLM and RFQ-state decisions.

**Recommended remediation boundary:**
Persist one durable inbound-envelope record per webhook delivery before queueing or parsing, including provider, raw body/form payload, relevant headers, provider message id, normalized sender, signature-verification result, and receipt timestamp.

## Finding J-A4-GPT54-03 - Make replay protection durable across process lifetime

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/services/webhook_processor.py:37-57` - duplicate suppression is a process-local deque/set capped at 5,000 message ids.
- `backend/app/models/quotes.py:17-26` - rejected quotes are intentionally preserved instead of deleted.
- `backend/app/services/rfq_orchestrator.py:498-509` - duplicate quote suppression only considers `RFQQuote.state == QuoteState.active`; rejected rows are explicitly excluded from the duplicate check.
- `backend/app/services/rfq_orchestrator.py:527-529` and `backend/app/services/rfq_orchestrator.py:662-675` - once no active duplicate is found, the auto-quote path creates and commits a new quote.

**Failure mode:**
Suppose inbound message `M` creates quote `Q`, and an operator later rejects `Q`. If the provider redelivers `M` after an app restart or after `_seen_message_ids` evicts it, `enqueue_message()` will accept the old provider message again. The orchestrator then ignores the earlier rejected quote during duplicate detection and auto-creates a fresh active quote from the replayed message. A stale replay can therefore recreate economic state that the desk already rejected.

**Governance impact:**
Violates the institutional invariant that webhook replay/out-of-order delivery must be processed deterministically and must not recreate stale institutional quotes from already-consumed evidence.

**Recommended remediation boundary:**
Persist provider message ids (or an equivalent immutable inbound-delivery key) in durable storage and enforce one-time consumption independently of quote state, process restarts, or in-memory cache eviction.

## Finding J-A4-GPT54-04 - Persist the LLM decision artifact for auto-created quotes

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/services/llm_agent.py:154-170` and `backend/app/services/llm_agent.py:173-202` - OpenAI calls are executed and parsed entirely in memory; the returned JSON object is not durably recorded.
- `backend/app/services/rfq_orchestrator.py:440-455` - the orchestrator builds RFQ context and sends the stripped inbound text to `LLMAgent.parse_quote_message`.
- `backend/app/services/rfq_orchestrator.py:561-568` and `backend/app/services/rfq_orchestrator.py:704-709` - the parsed output and confidence only survive in transient result dictionaries returned to the background worker.
- `backend/app/services/rfq_orchestrator.py:637-675` - a high-confidence parse directly creates and commits an `RFQQuote`.
- `backend/app/models/quotes.py:29-59` - `RFQQuote` stores the economic fields only; it has no columns for model, prompt/input, raw response, parsed response, or LLM confidence.
- `backend/app/api/routes/rfqs.py:255-272` - manual quote creation goes through an audited route dependency, but the LLM auto-quote path bypasses that audit surface entirely.

**Failure mode:**
A webhook message can mutate database state by auto-creating a quote and transitioning an RFQ to `QUOTED`, yet after commit there is no durable record of which model ran, what prompt/input it saw, what raw response it returned, what parsed fields/confidence were used, or why the gate allowed the mutation. If the quote is later challenged, the desk can inspect only the final economic row, not the LLM decision path that created it.

**Governance impact:**
Violates `docs/governance.md:115` and the A4 institutional rule against non-reconstructible LLM decisions that affect RFQ state or quote creation.

**Recommended remediation boundary:**
Persist an immutable LLM decision artifact linked to the inbound delivery and created quote before committing the auto-quote mutation. The artifact must include model id, prompt/input, raw response, parsed output, confidence, and the final allow/deny decision.

## Anti-findings considered

- `backend/app/services/rfq_service.py:619-654` - I did not accept a "terms sent != terms stored" finding for initial invites. The service prefixes the canonical id before persistence and sends `row.message_body` directly, so the stored body and wire body match on that path.
- `backend/app/services/rfq_orchestrator.py:116-132` and `backend/app/services/rfq_orchestrator.py:311-382` - I did not accept an A2 regression on canonical-id correlation. Inbound routing is driven by `RFQ#<rfq_number>` first, with phone used only as a consistency check after the RFQ lookup.
- `backend/app/services/llm_agent.py:360-373` and `backend/tests/test_phase5_whatsapp_llm.py:776-815` - I did not accept a finding on the confidence gate itself. Low-confidence parses are routed to human review instead of auto-quote creation.

## Cross-phase deferrals

- Outbound provider-result granularity remains thin: `RFQInvitation` captures send status, failure reason, and provider message id, but not the full provider response envelope. I did not elevate that separately because the inbound authenticity/evidence gaps and the missing LLM audit artifact already block A4 on stronger grounds.

## Recommended remediation waves

1. **Wave 1 - Webhook trust boundary**
   Add production/staging fail-closed config validation for Meta/Twilio webhook secrets, persist raw inbound envelopes before parsing, and replace process-local replay suppression with a durable consumed-message registry.

2. **Wave 2 - LLM mutation auditability**
   Introduce a durable inbound/LLM decision artifact linked to auto-created quotes so every LLM-driven quote mutation is fully reconstructible after commit.
