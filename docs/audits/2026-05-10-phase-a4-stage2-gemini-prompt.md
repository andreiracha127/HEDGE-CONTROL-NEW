# Phase A4 - Stage 2 Audit Dispatch - Auditor B

**Phase:** A4 - Integrations, RFQ outbound LLM, raw inbound durability, and LLM confidence calibration  
**Stage:** 2 of 3  
**Target auditor:** Gemini 3.1 Pro  
**Authoring date:** 2026-05-10  
**Repository:** `D:/Projetos/Hedge-Control-New`  
**Branch:** `main`  
**Expected output:** `docs/audits/2026-05-10-phase-a4-findings-gemini.md`

## 1. Operating Instructions

You are performing an independent read-only institutional audit. Do not edit
code, migrations, tests, generated schemas, or governance documents. Your output
must be an evidence-backed findings report, not an implementation plan.

This is the second auditor pass. The first auditor is GPT 5.4; the final jury is
GPT 5.5. Do not rely on either of them. Your value is independent verification,
especially catches that a same-family GPT auditor might miss.

Every accepted finding must include file and line references, a concrete failure
mode, and the institutional rule it violates. Avoid broad "best practice"
claims. This repo is an institutional financial system, so correctness,
auditability, determinism, and reconstruction outrank convenience.

## 2. Institutional Context

Closed phases:

- A1 is closed: economic primitives and lifecycle foundations.
- A2 is closed: RFQ canonical identity, ranking, award, and outbound evidence.
- A3 is closed: valuation, MTM, cashflow baseline, ledger reconciliation, and P&L lifecycle.

Phase A4 starts at the integration boundary. It focuses on external messaging,
webhooks, LLM-assisted RFQ interpretation, and provider failure semantics. Do
not reopen A1-A3 unless current integration code breaks a closed invariant.

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

Treat silent fallback, lossy parsing, hidden provider failure, non-durable
webhook data, and non-reconstructible LLM decisions as serious audit risks.

## 3. Primary Scope

Start with these files and expand only when a suspected finding requires it:

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

## 4. Audit Questions

Answer these questions directly. Use code evidence, not assumptions.

### Q1 - Outbound Evidence and Reconstruction

Can an auditor reconstruct every outbound RFQ lifecycle message exactly as sent:
RFQ number, counterparty, phone, purpose, body, send status, provider message ID,
failure reason, timestamps, and retry lineage?

If evidence is created only after a provider call succeeds, assess whether a
failed send loses the body or terms that were attempted.

### Q2 - Stored Terms Versus Sent Terms

Does the code prove that stored message text and sent message text are identical?

Look for mutation between persistence and provider send, including canonical ID
prefixing, language selection, template rendering, retry construction, and
provider-specific formatting.

### Q3 - Canonical Identifier Discipline

Does every outbound message include `RFQ#<rfq_number>`? Does every inbound path
refuse correlation without that identifier?

Reject phone-number correlation as a primary or fallback match. Phone may only
support consistency checks after the canonical RFQ ID is extracted.

### Q4 - Raw Inbound Durability

Are raw inbound webhook payloads persisted before parsing and queueing?

Inspect both Meta JSON and Twilio form paths. Check whether raw body/form,
headers/signature context, provider message ID, sender, timestamp, text, and
parse status survive process restart and can be replayed.

### Q5 - Signature, Replay, and Deduplication

Are signatures verified against exact provider-required inputs? Does the system
hard-fail invalid signatures and handle duplicate provider message IDs,
re-delivery, and out-of-order messages deterministically?

Pay attention to in-memory dedup structures, process restarts, multi-worker
deployment, and queue boundaries.

### Q6 - Economic Text Integrity Before LLM

Can canonical ID stripping, Unicode dash handling, whitespace normalization,
trivial-message filtering, or regex guards change economic meaning before quote
classification/parsing?

Verify signs, premium/discount direction, fixed-price units, pricing convention,
multi-ID messages, and archived/terminal RFQ behavior.

### Q7 - Confidence as an Enforcement Gate

Does low confidence block automatic quote creation? Do missing fields,
non-canonical units, hallucinated values, unsupported intent, or LLM outage stop
state mutation deterministically?

Assess both classifier and quote parser paths.

### Q8 - LLM Decision Evidence

Can the system reconstruct LLM prompt/input, model, parameters, raw response,
parsed output, confidence, and downstream decision for every LLM-assisted state
change?

If not, determine whether the missing evidence affects quote creation, RFQ
state, outbound message generation, or only operator diagnostics.

### Q9 - Provider Failure and Retry Semantics

Do Meta, Twilio, and fake provider paths preserve failure evidence without
inventing success? Are retries idempotent enough to avoid duplicate sends or
duplicate rows?

Check timeout, HTTP error, malformed response, absent provider ID, and partial
success boundaries.

### Q10 - RFQ Lifecycle Integration Races

Can late, duplicate, concurrent, or terminal-state inbound messages create
quotes, change state, or affect award/ranking after the RFQ should be closed,
archived, awarded, or no longer quotable?

Inspect timeout tasks, archive handling, award notification, rejection
notification, and quote submission paths.

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

When uncertain, use the lower severity and state what proof would raise it.

## 6. Finding Format

Write findings in this format:

```markdown
## Finding J-A4-GEMINI-XX - Short imperative title

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

- `Anti-findings considered` - inspected issues you rejected, with evidence.
- `Cross-phase deferrals` - items that belong to A5/A6 or prior phases.
- `Recommended remediation waves` - group accepted findings into coherent PR
  waves, preserving small blast radius.

## 7. Anti-Finding Rules

Do not report:

- Pure naming, style, or organization preferences.
- Generic "LLM may be wrong" concerns without a reachable state mutation or
  missing evidence boundary.
- Provider abstraction preferences without a concrete failure path.
- Test-only concerns unless the test gap leaves an institutional invariant
  unprotected.
- A1/A2/A3 issues unless current A4 code reintroduces them.

## 8. Required Workflow

1. Read `docs/governance.md`.
2. Inspect the primary scope files.
3. Inspect migrations and tests relevant to any suspected finding.
4. Validate each finding against current code, not memory or prior summaries.
5. Write the report to `docs/audits/2026-05-10-phase-a4-findings-gemini.md`.
6. Do not edit anything else.
