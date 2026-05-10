# Phase A4 - Stage 3 Jury Dispatch

**Phase:** A4 - Integrations, RFQ outbound LLM, raw inbound durability, and LLM confidence calibration  
**Stage:** 3 of 3  
**Target jury:** GPT 5.5  
**Authoring date:** 2026-05-10  
**Repository:** `D:/Projetos/Hedge-Control-New`  
**Branch:** `main`  
**Expected output:** `docs/audits/2026-05-10-phase-a4-jury-verdict.md`

## 1. Operating Instructions

You are the institutional jury for Phase A4. This is a read-only adjudication.
Do not edit implementation code, tests, migrations, generated schemas, or
governance documents.

Your job is to adjudicate two independent auditor reports:

- Auditor A: `docs/audits/2026-05-10-phase-a4-findings-gpt54.md`
- Auditor B: `docs/audits/2026-05-10-phase-a4-findings-gemini.md`

You must validate every accepted finding by reading the current code directly.
Do not rubber-stamp either auditor. Do not reject a finding only because the
other auditor missed it. Do not accept a finding unless it has a concrete
failure mode supported by current code.

## 2. Inputs

Read these files first:

- `docs/governance.md`
- `docs/audits/2026-05-10-phase-a4-stage1-gpt54-prompt.md`
- `docs/audits/2026-05-10-phase-a4-stage2-gemini-prompt.md`
- `docs/audits/2026-05-10-phase-a4-findings-gpt54.md`
- `docs/audits/2026-05-10-phase-a4-findings-gemini.md`

Then inspect implementation evidence in the Phase A4 scope:

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
- relevant migrations and tests.

## 3. Binding Governance

Binding governance is `docs/governance.md`. For Phase A4, these clauses are
central:

- `docs/governance.md:107` - exactly one canonical Award action.
- `docs/governance.md:113` - all RFQ invitations are persisted.
- `docs/governance.md:114` - terms sent equal terms stored.
- `docs/governance.md:115` - messages are evidence, not UI artifacts.
- `docs/governance.md:119` - canonical identifier is `RFQ#<rfq_number>`.
- `docs/governance.md:120` - canonical identifier is mandatory in all outbound messages.
- `docs/governance.md:121` - inbound messages are correlated only via this identifier.
- `docs/governance.md:125-128` - ranking is deterministic, spread-based, tie-free, and incomplete quotes hard-fail.

Hard-fail, determinism, auditability, and reconstruction remain mandatory.

## 4. Jury Questions

For each auditor finding, answer:

1. Is the cited code path reachable?
2. Is the failure mode concrete, or speculative?
3. Does it break a Phase A4 boundary: integration evidence, raw inbound
   durability, canonical correlation, provider failure semantics, LLM confidence
   gating, or LLM decision reconstruction?
4. Does the finding belong in A4, or should it be deferred to A5/A6/cross-phase?
5. Is the severity correct under the taxonomy below?
6. Is the remediation boundary small enough for a controlled PR wave?

You may add fresh findings only if both auditors missed a concrete, evidence
backed issue discovered during adjudication. Fresh findings must meet the same
standard as accepted auditor findings.

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
  not carry Tier 4 unless it protects a concrete A4 boundary.

If an auditor overstates severity, downgrade it. If an auditor understates a
governance breach, upgrade it. Explain every severity change.

## 6. Verdict Format

Write the verdict to:

`docs/audits/2026-05-10-phase-a4-jury-verdict.md`

Use this structure:

```markdown
# Phase A4 Jury Verdict

## Executive Summary

- Total accepted findings: N
- Tier 1: N
- Tier 2: N
- Tier 3: N
- Tier 4: N
- Rejected auditor findings: N
- Fresh jury findings: N

## Accepted Findings

### J-A4-XX - Canonical title

**Source:** GPT54 J-A4-GPT54-XX | Gemini J-A4-GEMINI-XX | Jury Fresh
**Severity:** Tier N / Blocking|High|Medium|Low
**Status:** Open
**Disposition:** Accepted | Accepted with severity change | Accepted as subsumed
**Evidence:**
- `path/to/file.py:123` - code evidence

**Failure mode:**
Concrete sequence.

**Governance impact:**
Exact invariant.

**Remediation boundary:**
Smallest acceptable PR boundary.
```

Then include:

```markdown
## Rejected Findings

### Auditor finding ID - short title

**Disposition:** Rejected
**Reason:** Evidence-based reason, with file/line references where relevant.

## Subsumed Findings

Map duplicate auditor findings to the canonical accepted finding.

## Cross-Phase Deferrals

Items that are real but belong to A5, A6, or a later cross-phase cleanup.

## Recommended Remediation Waves

### PR-A4-1 - Short wave title
- Findings: J-A4-...
- Scope boundary:
- Required verification:

### PR-A4-2 - Short wave title
- Findings: J-A4-...
- Scope boundary:
- Required verification:

## Anti-Findings Confirmed

Important suspected issues that were checked and found safe.
```

## 7. Adjudication Rules

- Convergent findings are not automatically correct. Verify them.
- Single-auditor findings are not automatically weak. Verify them.
- Reject findings that are merely style, preference, or generic LLM distrust.
- Do not create giant remediation waves. Preserve narrow PR boundaries.
- Do not alter `docs/governance.md`.
- Do not recommend merge. This stage only produces the jury artifact and
  remediation sequencing.
- If the reports are missing, stop and report that Stage 1 or Stage 2 is not
  complete rather than fabricating a verdict.
