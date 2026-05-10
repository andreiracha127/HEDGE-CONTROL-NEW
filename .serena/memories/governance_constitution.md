# Governance Constitution — Hedge Control Platform

> Source of truth: `docs/governance.md`. **Read it whenever in doubt** — these rules override convenience, UX polish, or "what usually works".

## Supreme rule
The System Constitution is the highest authority. If a requested action would violate it, **stop and respond exactly with**:
> `BLOCKED — requires governance decision`
No fallback behavior is allowed.

## Optimization targets (in order)
1. Economic correctness
2. Determinism
3. Auditability
4. Reconstructability

NOT optimized for: UX, speed, convenience, elegance, "best effort".

## Canonical economic model (binding)
**Orders**
- Sales Orders (SO) → Commercial Active Exposure
- Purchase Orders (PO) → Commercial Passive Exposure
- Only **variable-price** orders generate exposure
- Fixed-price orders generate **cashflow only**

**Exposure**
- Exposure is **state**, never event
- Always in **metric tons (MT)**
- Commercial Net = Active − Passive

**Hedge Contracts**
- Always exactly two legs: one fixed, one variable
- Quantity always in MT
- Classification is deterministic and absolute:
  - Fixed Buy leg → **Hedge Long**
  - Fixed Sell leg → **Hedge Short**

**Linkage**
- Linked hedge contracts reduce commercial AND global exposure
- Unlinked hedge contracts affect global exposure only

**Global Exposure (primary risk KPI)**
- Global Active = Commercial Active + Hedge Short (unlinked)
- Global Passive = Commercial Passive + Hedge Long (unlinked)
- Global Net = Active − Passive

## RFQ system (canonical)
Lifecycle: `RFQ → Quotes → Deterministic Ranking → Award → Contract`

- Exactly one canonical Award action
- No award without contract creation; no contract without RFQ
- All RFQ invitations are **persisted**; terms sent = terms stored. Messages are evidence, not UI artifacts.
- Canonical correlation identifier: `RFQ#<rfq_number>` — mandatory in all outbound messages; inbound messages correlate **only** via this identifier.
- Ranking is fully deterministic, spread-based, **no ties allowed**, incomplete quotes hard-fail.

## Valuation, MTM & cashflow
- CashFlow is always **derived**, never manually input.
- Four views: Analytic (non-persistent), Baseline (persistent), Ledger (accounting), What-if (simulation only).
- MTM uses **D-1 settlement**.
- One methodology per endpoint. **No fallback pricing regimes.** Premium pricing is excluded.

## Scenario / what-if rules
- In-memory only
- No persistence, no timeline, no cache reuse
- Explicit deltas only

## Hard fails (must hard-fail, no silent fallback)
- Evidence missing
- Non-deterministic ranking
- Over-allocated exposure
- Price reference cannot be proven
- Ambiguous dates
- Contracts cannot be reconstructed

## Execution discipline
- Work strictly in explicit phases (Phase 0, Phase 1, …). One phase at a time. Never preempt future phases.
- If unsure whether something belongs to the current step, **assume it does NOT**.
- At the end of each phase/step, produce an Execution Report stating what was implemented AND what was intentionally NOT implemented. **Without that evidence, the phase does not exist.**

## Output contract
All outputs must be: precise, structured, verifiable, audit-friendly, free of speculation.
