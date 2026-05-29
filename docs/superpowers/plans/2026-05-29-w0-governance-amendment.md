# W0 — Governance Amendment (Commercial Partners ↔ Hedge Separation + Commercial KYC) — Execution Record

> **STATUS: EXECUTED.** The authoritative result of this wave is the merged
> **`docs/governance.md`** (AUTHORIZATION MATRIX + the hedge sanctions gate /
> commercial KYC + order gate / sanctions screening / LEI / credit-and-terms
> subsections) plus the design **spec**. This file is the *execution record*:
> it intentionally **does NOT reproduce the governance prose** — that prose was
> refined across multiple Codex absorption rounds and any inline copy here would
> drift. For the canonical amendment text, read `docs/governance.md`; for the
> design rationale, read the spec. This doc keeps the task structure, the
> verification approach, and the absorption changelog.

**Goal:** Amend the constitutional source of truth (`docs/governance.md`, with a consistency check on `docs/systemconstitucion.md`) to encode the commercial-partner / hedge-counterparty separation and the re-targeted KYC model, so downstream waves W1–W6 have an authoritative contract.

**Architecture:** Docs-only constitutional amendment. The AUTHORIZATION MATRIX gains a second counterparty domain (`commercial_partners`); the former "Counterparty KYC gate (Pilot Hard Blocker 1)" is split into a **hedge sanctions gate** (RFQ admission gated on effective `sanctions_status`, not `kyc_status`) and a **commercial partner KYC + order gate** (new fail-closed hard block on order creation), plus new subsections governing sanctions screening, LEI validation, and credit/terms. No code in this wave; verification is internal-consistency sweeps + the repo's Codex PR review.

**Tech Stack:** Markdown (`docs/governance.md`, `docs/systemconstitucion.md`); `git`; `Grep` for consistency sweeps.

**Spec:** [`docs/superpowers/specs/2026-05-29-commercial-partners-kyc-separation-design.md`](../specs/2026-05-29-commercial-partners-kyc-separation-design.md) — decisions D1–D6.

**Scope note:** First of seven waves (W0–W6). Amendment-only PR (no code), per the amendment→dispatch→implementation protocol. Implementation waves carry the code + tests that conform to this contract.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `docs/governance.md` | RBAC matrix + binding gates (constitutional) — **authoritative output** | Modified |
| `docs/systemconstitucion.md` | Higher-level principles — verify no contradiction | Verified (no edit needed; it already separates commercial ops from financial hedging) |

---

## Tasks (all executed; each edit landed in `docs/governance.md` — see that file for canonical text)

| # | What it changed (pointer to the governance section it produced) | Verification |
|---|-----------------------------------------------------------------|--------------|
| T1 | AUTHORIZATION MATRIX → split the `trader`/`risk_manager` role bullets into the **hedge `counterparties`** vs **`commercial_partners`** domains | `grep "commercial_partners"` present; no "all 4 types" |
| T2 | Rewrote the **Authorization invariants**: hedge rows invisible to trader (empty list / 404); commercial CRUD minus the risk_manager-only `kyc_status` + credit/terms fields (incl. the identity-edit fail-closed reset) | sweep: no stale per-type branch |
| T3 | Re-targeted the RFQ admission gate from `kyc_status` to **effective `sanctions_status`** (header + gate rule + quote + award + fail-closed + status-transitions block); RFQ refusal events `rfq_*_rejected_sanctions_not_cleared` | sweep: no `*_rejected_kyc_not_approved`; event-name parity |
| T4 | Added the **Commercial partner KYC + order gate** (fail-closed: kyc approved + sanctions ≠ blocked + kind coherence; dual-session audit; `order_rejected_{kyc_not_approved,sanctions_blocked,kind_mismatch}`) | subsection-order grep |
| T5 | Added **Sanctions screening governance** (universal; hosted OpenSanctions `EntityMatchQuery`; decoupled; immutable `sanctions_screenings`; no silent fallback; `unscreened` default; **Adjudication** path) | — |
| T6 | Added **LEI validation governance** (GLEIF + offline ISO 7064 checksum; warn-not-block) | — |
| T7 | Added **Credit and terms governance** (asymmetric by kind; `Decimal`; risk_manager-approved; utilization gate deferred) | — |
| T8 | Re-mapped **Pilot scope** (4 hedge / 4 commercial) + corrected the migration note (commercial_partners + sanctions_screenings + sanctions_adjudications; UUID reuse; fail-closed reset; pre-FK + hedge-ref validations) | subsection grep |
| T9 | `systemconstitucion.md` consistency check — **no contradiction, no edit** | grep + read |
| T10 | Final consistency sweeps (stale-vocab, event-name parity, cross-reference) + end-to-end read + amendment PR | grep sweeps; Codex PR review |

> The exact before/after prose for each task is captured in `docs/governance.md` at the named subsections (the canonical, Codex-reviewed text). Do NOT re-derive it from this table — read the governance file.

---

## Absorption changelog (Codex review rounds on PR #111)

The amendment was hardened across several Codex Connector review rounds. Binding refinements that supersede the original draft (all merged into `docs/governance.md` / spec):

1. **Hedge RFQ gate admits ONLY an effective `clear`** (a clear screening OR a risk_manager adjudication of a `flagged`); denies `blocked`, unadjudicated `flagged`, and unscreened. The COMMERCIAL order gate stays `sanctions_status != blocked` (locked decision D3). RFQ events `rfq_*_rejected_sanctions_not_cleared`.
2. **`sanctions_screenings.result` is NULL when `status=error`**; `sanctions_status` updates only from the latest SUCCESSFUL screening.
3. **Generic PATCH excludes `kyc_status` + credit/terms for ALL actors** (incl. risk_manager); they change only via the dedicated audited flows.
4. **`service:sanctions_screening`** added to the internal-issued JWT/`actor_sub` invariant; the scheduled re-screen is attributed to it.
5. **Migration resets fail-closed** (commercial `kyc_status`→`pending`, `sanctions_status`→`unscreened` both domains) — no carried `approved`/default-`clear` without screening evidence.
6. **`SanctionsStatus` gains an explicit `unscreened` member** (default, NOT `clear`).
7. **Adjudication path** — risk_manager overrides a **`flagged`** (only) via `POST {id}/adjudicate-sanctions`, writing an immutable `sanctions_adjudications` row that supersedes the screening without mutating it; valid only against the **latest still-`flagged`** screening (cannot override a newer `blocked`); a `blocked` must be remediated + re-screened.
8. **Wave order** — screening = **W2**; commercial order gate + RFQ re-target + HB-3 `risk_flags` re-align = **W3** (depend on W2). Screening score thresholds bound to **W2**.
9. **Migration validations** — pre-FK (orders → broker/bank rows) AND symmetric hedge-ref (RFQ/quote/contract/llm → customer/supplier rows) both HALT with remediation (no silent orphaning / FK breakage).
10. **Identity-edit reset** — editing a screening-relevant identity field (`name`/`country`/`tax_id`/`lei`) on a partner carrying ANY prior screening evidence (incl. `pending`+`flagged`) resets it fail-closed + re-screen; applies to **both** commercial partners and hedge counterparties.
11. **Audit completeness** — kind-mismatch refusals emit `order_rejected_kind_mismatch`; inbound/LLM quote refusals record `service:webhook_inbound` (not null).
12. **Effective-clear phrasing** normalized at every gate site (header, rule, quote, award, fail-closed) — "effective `clear` (screening OR adjudication)", not "recorded clear screening".

---

## Self-Review

- **Spec coverage:** every spec decision D1–D6 + RBAC + gates + screening/LEI/credit + pilot re-map maps to a task above and a governance subsection.
- **No placeholders:** the only deferral is the sanctions score *threshold values*, bound to the **W2** dispatch by constitutional decision (ranges given: clear / flagged / blocked).
- **Verification is the grep sweeps + end-to-end read + Codex PR review.** No `pytest`/`npm` — docs-only wave. W1 carries the model + migration + tests that conform.

## Execution Handoff

W0 executed and merged via PR #111. Downstream: **W1** (data model + migration + `commercial_partner_service` + RBAC), then W2 (screening) → W3 (gates + risk_flags re-align) → W4 (LEI) → W5 (frontend) → W6 (credit/terms), each its own spec → dispatch → implementation cycle.
