# Phase A4 - Stage 1 Audit Dispatch - Auditor A

**Phase:** A4 - Integrations, RFQ outbound LLM, raw inbound durability, and LLM confidence calibration  
**Stage:** 1 of 3  
**Target auditor:** GPT 5.4  
**Authoring date:** 2026-05-10  
**Repository:** `D:/Projetos/Hedge-Control-New`  
**Branch:** `main`  
**Expected output:** `docs/audits/2026-05-10-phase-a4-findings-gpt54.md`

## 1. Operating Instructions

You are performing a read-only institutional audit. Do not edit code, migrations,
tests, generated schemas, or governance documents. Your job is to inspect the
current codebase and produce an evidence-backed findings report.

This stage replaces the usual Opus auditor because Opus 4.7 is temporarily
unavailable. Treat this as an independent first-pass audit. Do not assume the
Gemini auditor will see the same issues. The final adjudication will be done by
GPT 5.5 in Stage 3.

Use direct code evidence. Every accepted finding must include file and line
references, a concrete failure mode, and the institutional rule it violates. Do
not report style issues, naming preferences, hypothetical rewrites, or refactors
without a demonstrated correctness/auditability impact.

## 2. Institutional Context

Closed phases:

- A1 is closed: economic primitives and lifecycle foundations.
- A2 is closed: RFQ canonical identity, ranking, award, and outbound evidence.
- A3 is closed: valuation, MTM, cashflow baseline, ledger reconciliation, and P&L lifecycle.

Phase A4 starts at the integration boundary. Its scope is not to reopen A1-A3
unless integration code breaks a closed invariant.

Binding governance is `docs/governance.md`. For this audit, the most relevant
clauses are:

- `docs/governance.md:107` - exactly one canonical Award action.
- `docs/governance.md:113` - all RFQ invitations are persisted.
- `docs/governance.md:114` - terms sent equal terms stored.
- `docs/governance.md:115` - messages are evidence, not UI artifacts.
- `docs/governance.md:119` - canonical identifier is `RFQ#<rfq_number>`.
- `docs/governance.md:120` - canonical identifier is mandatory in all outbound messages.
- `docs/governance.md:121` - inbound messages are correlated only via this identifier.
- `docs/governance.md:125-128` - ranking is deterministic, spread-based, tie-free, and incomplete quotes hard-fail.

Hard-fail remains the default. Silent fallback, lossy parsing, hidden provider
failure, non-reconstructible LLM decisions, and "best effort" state transitions
are audit findings when they affect institutional behavior.

## 3. Primary Scope

Start with these files and expand only as needed:

- `backend/app/services/rfq_service.py`
- `backend/app/services/rfq_orchestrator.py`
- `backend/app/services/rfq_message_builder.py`
- `backend/app/services/webhook_processor.py`
- `backend/app/services/whatsapp_service.py`
- `backend/app/services/whatsapp_providers.py`
- `backend/app/services/llm_agent.py`
- `backend/app/api/routes/rfqs.py`
- `backend/app/api/routes/webhooks.py`
- `backend/app/models/rfqs.py`
- `backend/app/models/quotes.py`
- `backend/app/models/counterparty.py`
- `backend/app/schemas/llm.py`
- `backend/app/schemas/whatsapp.py`
- `backend/app/tasks/rfq_timeout_task.py`
- Alembic migrations related to RFQ invitations, webhook/inbound persistence, and quote lifecycle.
- Tests under `backend/tests/test_rfq*`, `backend/tests/test_webhook_processor.py`, and `backend/tests/test_whatsapp_service.py`.

Do not ignore tests, but do not accept test presence as proof if production code
does not enforce the invariant.

## 4. Audit Questions

Answer these questions explicitly. A negative answer is not automatically a
finding; it becomes a finding only if it creates a concrete correctness,
auditability, determinism, or reconstruction failure.

### Q1 - Outbound RFQ Evidence

Can every outbound RFQ message be reconstructed exactly as sent, including RFQ
number, counterparty, recipient phone, purpose, body, provider result, send
status, failure reason, and timestamps?

Check that durable evidence exists before external send attempts where required.
Verify that queued, sent, and failed states are represented without inventing
provider message IDs or timestamps.

### Q2 - Terms Sent Equal Terms Stored

Does the system guarantee that the message body passed to WhatsApp is identical
to the message body persisted as evidence?

Look for any post-persistence mutation, prefixing, localization, templating,
provider formatting, or retry path that could send content different from the
stored `RFQInvitation.message_body`.

### Q3 - Canonical RFQ Identifier Boundary

Is `RFQ#<rfq_number>` mandatory in all outbound RFQ lifecycle messages, including
initial invite, refresh, quote rejection, award notification, and rejection
notification?

Inbound correlation must be based only on this identifier. Phone number may be a
consistency check, but cannot be the primary correlation key or fallback for
missing canonical ID.

### Q4 - Raw Inbound Durability

Are inbound provider payloads durable enough to reconstruct what was received
before parsing, classification, queueing, or LLM processing?

Inspect Meta and Twilio webhook paths. Determine whether raw request body or raw
form parameters, provider headers, provider message ID, sender, timestamp,
normalized text, and signature-verification context are persisted. An in-memory
queue alone is not durable evidence.

### Q5 - Webhook Authenticity and Replay

Are Meta HMAC and Twilio signature checks performed against the exact raw inputs
required by each provider? Are missing secrets, missing signatures, invalid
signatures, duplicate provider message IDs, replay, and out-of-order delivery
handled deterministically?

Do not report a secret-absent development mode as a production finding unless the
code can enter that mode in production without a hard-fail or explicit
configuration barrier.

### Q6 - Inbound Parser and LLM Boundaries

Can the inbound parser lose economic meaning before the LLM sees the message?

Inspect canonical ID stripping, dash handling, signs, units, price conventions,
premium/discount signs, and multi-ID messages. Prior A2/A3 fixes must not be
regressed by integration code.

### Q7 - LLM Confidence Calibration

Does the system treat LLM confidence as an enforceable gate rather than a log
decoration?

Check classification and quote parsing. Low confidence, missing price/unit/
convention, non-canonical units, hallucinated price, unsupported intent, or LLM
unavailability must not auto-create institutional quotes.

### Q8 - LLM Audit Evidence

For any LLM-driven decision that affects RFQ state or quote creation, can an
auditor reconstruct the model, prompt/input, raw response, parsed output,
confidence, and decision path?

If such evidence is not persisted, classify severity based on whether the LLM
decision changes database state or merely generates advisory text.

### Q9 - Provider Failure Semantics

Do WhatsApp provider failures preserve a durable failed state with enough
diagnostic evidence? Are retries idempotent, and can they avoid duplicate sends
or duplicate invitation rows?

Check Meta, Twilio, and fake provider paths. Provider abstractions must not
convert unknown failures into apparent success.

### Q10 - RFQ State Machine Under Integration Load

Are RFQ state transitions deterministic when inbound messages arrive late,
duplicated, concurrently, for archived RFQs, or after terminal states?

Check whether terminal RFQs, archived RFQs, timeout/close tasks, award paths, and
inbound quote creation can race into inconsistent state.

## 5. Severity Taxonomy

Use this taxonomy:

- **Tier 1 / Blocking:** A concrete path can create, mutate, award, rank, or
  persist institutional state incorrectly; loses required evidence; violates a
  hard governance invariant; silently accepts unverifiable LLM/provider output;
  or cannot be reconstructed after the fact.
- **Tier 2 / High:** A real edge case can impair auditability, retry semantics,
  operator diagnosis, or deterministic processing, but does not by itself create
  incorrect economic state under normal flow.
- **Tier 3 / Medium:** A localized robustness or coverage gap with plausible
  operational impact but no immediate institutional invariant breach.
- **Tier 4 / Low:** Documentation, test, or observability improvement only. Do
  not include Tier 4 unless it protects a concrete A4 boundary.

When uncertain between two severities, choose the lower severity and explain the
missing evidence that would make it higher.

## 6. Finding Format

Write findings in this format:

```markdown
## Finding J-A4-GPT54-XX - Short imperative title

**Severity:** Tier N / Blocking|High|Medium|Low
**Status:** Open
**Evidence:**
- `path/to/file.py:123` - what the code does
- `path/to/test.py:456` - relevant test gap or assertion, if any

**Failure mode:**
Describe the concrete sequence that breaks correctness, auditability,
determinism, or reconstruction.

**Governance impact:**
Name the exact governance clause or institutional invariant.

**Recommended remediation boundary:**
State the smallest acceptable fix boundary. Do not prescribe broad refactors.
```

After findings, include:

- `Anti-findings considered` - issues you inspected and rejected, with evidence.
- `Cross-phase deferrals` - items that belong to A5/A6 or prior phases.
- `Recommended remediation waves` - group accepted findings into coherent PR
  waves, preserving small blast radius.

## 7. Anti-Finding Rules

Do not report:

- Merely missing comments.
- Pure naming or formatting concerns.
- A refactor preference with no concrete failure mode.
- Test gaps when production code already hard-fails correctly and the gap does
  not protect an institutional boundary.
- A1/A2/A3 issues unless current A4 integration code reintroduces them.
- "LLM could be wrong" as a generic finding. Tie every LLM finding to a missing
  gate, missing persisted evidence, or reachable incorrect state transition.

## 8. Required Workflow

1. Read `docs/governance.md`.
2. Inspect the primary scope files.
3. Inspect migrations and tests relevant to any suspected finding.
4. Validate each finding against current code, not memory or prior PR summaries.
5. Write the report to `docs/audits/2026-05-10-phase-a4-findings-gpt54.md`.
6. Do not edit anything else.
