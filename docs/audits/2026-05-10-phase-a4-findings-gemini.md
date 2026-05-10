# Phase A4 - Stage 2 Audit Findings (Gemini 3.1 Pro)

## Finding J-A4-GEMINI-01 - Raw Inbound Webhook Payloads Lack Durable Storage

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/services/webhook_processor.py:27` - `_message_queue` is an in-memory `collections.deque`.
- `backend/app/api/routes/webhooks.py:128` - `extract_messages` are dumped into the in-memory queue and the endpoint returns 200 immediately.

**Failure mode:**
Raw webhook payloads from Meta and Twilio are extracted and queued entirely in memory. If the application process crashes, restarts, or scales down during webhook processing, all unprocessed inbound quotes and messages are permanently lost.

**Governance impact:**
Violates `docs/governance.md:115` (messages are evidence) and the hard requirement that evidence cannot be missing or non-reconstructible.

**Recommended remediation boundary:**
Persist the raw incoming HTTP payload (JSON or form data) with its provider message ID to a durable `inbound_webhooks` database table before acknowledging the webhook with HTTP 200.

## Finding J-A4-GEMINI-02 - In-Memory Webhook Deduplication Vulnerable to Restart Replays

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/services/webhook_processor.py:30-31` - `_seen_set` and `_seen_message_ids` are module-level global variables.

**Failure mode:**
The deduplication of incoming provider messages relies on an in-memory Python `set`. A process restart or multi-worker scale-out completely circumvents this guard. If Meta or Twilio redelivers a webhook (e.g., due to a temporary network timeout between the provider and the application), the system will re-process the exact same message, leading to duplicate quotes and potential state-machine race conditions.

**Governance impact:**
Violates `docs/governance.md` execution determinism and reconstruction rules.

**Recommended remediation boundary:**
Move message deduplication to a database constraint (e.g., a unique constraint on `provider_message_id` in the inbound messages table) or a durable cache.

## Finding J-A4-GEMINI-03 - Regex Stripping Can Alter Economic Sign for Negative Spreads

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/services/rfq_orchestrator.py:91` - `_CANONICAL_ID_RE` uses `(?:\s+[—–]\s+)?` at the end of the regex to strip trailing dashes.
- `backend/app/services/rfq_orchestrator.py:100` - `_strip_canonical_id` strips the matched pattern before passing the text to the LLM.

**Failure mode:**
When quoting a discount, counterparties often use a dash or minus sign. If a counterparty replies with `RFQ#RFQ-2026-000001 — 10 USD/MT` (intending a discount of -10), the `_CANONICAL_ID_RE` regex will eagerly consume and strip the em-dash or en-dash. The LLM will then receive `10 USD/MT` instead of `-10 USD/MT`, fundamentally inverting the economic meaning from a discount to a premium.

**Governance impact:**
Violates `docs/governance.md` economic correctness. Mutation occurs without evidence before quote extraction.

**Recommended remediation boundary:**
Remove the trailing dash stripping `(?:\s+[—–]\s+)?` from `_CANONICAL_ID_RE`. The LLM should receive the exact punctuation the counterparty typed.

## Finding J-A4-GEMINI-04 - LLM Decision Evidence Is Not Persisted

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- `backend/app/services/llm_agent.py:180` - `_call_openai` drops the prompt structure and raw model JSON response.
- `backend/app/services/rfq_orchestrator.py:347` - `LLMAgent.parse_quote_message` is called, and the quote is created, but the LLM inputs/outputs are never durably stored.

**Failure mode:**
The system uses the LLM as a non-deterministic black box to mutate the financial state (creating a quote). Because the exact prompt, the raw JSON response from the LLM, the model version used, and the confidence score are not stored alongside the quote in the database, it is impossible for an auditor to reconstruct *why* the quote was parsed a certain way if a dispute arises.

**Governance impact:**
Violates `docs/governance.md` reconstruction and auditability rules. Evidence of the decision-making process is missing.

**Recommended remediation boundary:**
Persist the LLM execution trace (model version, raw input prompt, raw output JSON, and confidence score) either as JSON metadata on the `rfq_quotes` table or in a dedicated `llm_audit_logs` table.

---

### Anti-findings considered

- **Provider retry logic in Twilio sandbox mutating phone numbers:** `TwilioWhatsAppProvider._sandbox_normalize_brazilian` alters 9-digit Brazilian mobiles to 8-digit. This was analyzed and rejected as a finding. It is a necessary and safe transport-layer normalization for the Twilio sandbox environment, and it does not affect the actual financial terms or counterparty identity matching.
- **LLM price hallucination risk:** The LLM's capability to hallucinate a completely fake price was analyzed. It is effectively mitigated by `RFQOrchestrator._price_appears_in_text` which strictly enforces that the numeric value output by the LLM must exist in the raw counterparty text.

### Cross-phase deferrals

None.

### Recommended remediation waves

- **Wave 1 (Durability):** Address J-A4-GEMINI-01 and J-A4-GEMINI-02 by introducing a durable inbound webhook table and shifting deduplication logic to the database.
- **Wave 2 (Integrity & Evidence):** Address J-A4-GEMINI-03 by fixing the canonical ID regex, and J-A4-GEMINI-04 by adding LLM audit logging to the database.