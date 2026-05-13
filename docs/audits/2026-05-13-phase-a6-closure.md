# Phase A6 — Frontend Institutional Surface — Closure

**Closure date:** 2026-05-13
**Final main HEAD post-A6:** `aa255e2be8c1502b711de131caf4b4d057a5751c` (Merge PR #67 — PR-A6-4 reconstructability surfaces)
**Branch:** `main` (origin/main in sync)
**Verdict:** CLOSED institutionally. 12/12 accepted jury findings remediated. 0 outstanding A6 work.

---

## 1. Scope and jury baseline

Phase A6 audited the Svelte institutional control surface (`frontend-svelte/`) under the standard 3-stage adversarial → jury protocol. Reference artifacts on main:

| Artifact | Path |
|---|---|
| Stage 1 prompt (Opus 4.7) | `docs/audits/2026-05-12-phase-a6-stage1-opus47-prompt.md` |
| Stage 2 prompt (Gemini) | `docs/audits/2026-05-12-phase-a6-stage2-gemini-prompt.md` |
| Stage 3 prompt (GPT-5.5 jury) | `docs/audits/2026-05-12-phase-a6-stage3-gpt55-prompt.md` |
| Stage 1 findings | `docs/audits/2026-05-12-phase-a6-findings-opus47.md` |
| Stage 2 findings | `docs/audits/2026-05-12-phase-a6-findings-gemini.md` |
| Jury verdict | `docs/audits/2026-05-12-phase-a6-jury-verdict.md` |

The jury accepted **12 findings** (T1=2, T2=7, T3=3, T4=0), rejected 1 (sessionStorage XSS, scope-out), and recorded 4 cross-phase deferrals tied to backend / platform decisions (RFQ actor derivation server-side, production IdP selection, token-storage hardening, backend status endpoint semantics).

Anti-findings explicitly confirmed by the jury: raw `fetch` bypass absent in routed pages, WS auth handshake correct, client-side role gating is not the security boundary, orders are an institutional source record (Gemini's "optional navigation" anti-finding rejected).

---

## 2. PRs merged in the A6 cycle (2026-05-12 → 2026-05-13)

| PR | Title | Findings closed | Merge commit | CI rollup | Merged at (UTC) |
|---|---|---|---|---|---|
| #62 | `docs(audit-a6)`: add frontend audit prompts and verdict | — (audit-trail) | `ff51e46c2` | 6/6 SUCCESS | 2026-05-12 20:30 |
| #63 | `docs(audit-a6)`: add frontend remediation dispatches | — (audit-trail) | `7dc3825ed` | 6/6 SUCCESS | 2026-05-12 23:15 |
| #64 | **PR-A6-1** — contract path + load-failure discipline | **J-A6-01 (T2) + J-A6-05 (T2) + J-A6-07 (T3)** + guard slice of J-A6-02 | `b851283fa` | 6/6 SUCCESS | 2026-05-13 00:29 |
| #65 | **PR-A6-2** — settlement + RFQ evidence integrity | **J-A6-02 (T1) + J-A6-04 (T1) + J-A6-12 (T2)** | `a356795ef` | 6/6 SUCCESS | 2026-05-13 01:31 |
| #66 | **PR-A6-3** — financial display + numeric precision | **J-A6-03 (T2) + J-A6-06 (T2) + J-A6-11 (T3)** | `6487faf50` | 6/6 SUCCESS | 2026-05-13 02:57 |
| #67 | **PR-A6-4** — reconstructability surfaces | **J-A6-08 (T2) + J-A6-09 (T2) + J-A6-10 (T3)** | `aa255e2be` | 6/6 SUCCESS | 2026-05-13 03:45 |

All four implementation PRs were green on every CI check (`Backend: pytest`, `openapi_diff`, `Frontend: svelte-check + TypeScript`, `Frontend: Vitest`, `Frontend: Static Build`, `E2E: Playwright (docker-compose)`).

---

## 3. Finding-by-finding closure tally

| Finding | Tier | Title (short) | Closed by |
|---|---|---|---|
| J-A6-01 | T2 | Stale frontend API paths → align with OpenAPI contract | PR #64 |
| J-A6-02 | T1 | Settlement-via-generic-status exposure | PR #64 (guard slice) — confirmed unchanged in PR #65 |
| J-A6-03 | T2 | Zero-default fallbacks on P&L / MTM display | PR #66 |
| J-A6-04 | T1 | Fabricated RFQ actor identity in mutation bodies | PR #65 (frontend slice via JWT `sub`) |
| J-A6-05 | T2 | Silent non-2xx clears on RFQ + market-data mutations | PR #64 |
| J-A6-06 | T2 | Westmetall 6-decimal price precision loss on display | PR #66 |
| J-A6-07 | T3 | Typed contract paths + static drift guard | PR #64 |
| J-A6-08 | T2 | Orders not visible as reconstructible source records | PR #67 |
| J-A6-09 | T2 | Signed audit events + verification surface | PR #67 |
| J-A6-10 | T3 | Dev-only manual JWT login gating | PR #67 |
| J-A6-11 | T3 | RFQ quantity precision (MT 3-decimal) | PR #66 |
| J-A6-12 | T2 | Single-parse RFQ quotes / state-event responses | PR #65 |
| **Total** | — | **12/12** | — |

By tier: **T1 = 2/2 closed**, **T2 = 7/7 closed**, **T3 = 3/3 closed**.

---

## 4. Cross-phase deferrals (out of A6 scope by jury design)

Recorded in the jury verdict §Cross-Phase Deferrals. These are platform / backend decisions, not A6 gaps:

1. **Backend RFQ actor derivation.** Backend currently requires client-supplied `user_id` on RFQ mutations. PR #65 sent the immutable JWT `sub` claim as a frontend-only mitigation. Canonical fix: derive actor identity from authenticated JWT server-side and remove `user_id` from request bodies. → Future backend hardening phase.
2. **Production identity provider selection.** A6 gated the dev paste-token flow (J-A6-10); selecting a production IdP / reverse-proxy auth model is a platform decision. → Future platform phase.
3. **Token storage hardening.** HTTP-only cookies, CSRF, CSP, full XSS-sink inventory. Jury rejected J-A6-OPUS-12 (sessionStorage XSS) as scope-out for A6. → Future security/platform phase.
4. **Backend status endpoint semantics.** `/contracts/hedge/{contract_id}/status` can theoretically still set `settled` server-side. Frontend gate (PR #64) removed `settled` / `partially_settled` from `VALID_TRANSITIONS` + added defence-in-depth refusal in `transitionStatus`. Canonical fix: backend rejects `settled` on the generic status patch and forces settlement through the ledger endpoint. → Future backend hardening phase.

---

## 5. Quality-gate evidence

### 5.1 Pre-push hook v2 (Sonnet 4.6 tool-use sieve) absorption

| PR | Hook P1 | Hook P2 | Hook P3 | Notes |
|---|---|---|---|---|
| #64 | 0 | 0 | 3 INFO | All stylistic confirmations, no action required |
| #65 | 0 | 0 | 1 | `userSub` vs `userName` type-annotation consistency — left as-is (load-bearing) |
| #66 | 0 | 1 → fixed | 1 | P2 sweep miss on `step="0.001"` UX-only comment; one Tipo-I FP on re-word (partial-diff blindness, known FP class) |
| #67 | 0 | 1 → fixed | 2 | P2 sibling-bullet sweep miss on nav-visibility test; 3 Tipo-I FP on test-only follow-up (partial-diff blindness, documented in `reference_pre_push_hook_calibration`) |

**Across A6, hook v2 surfaced 0 real P1, 2 real P2 (both absorbed), and 0 false-positive P1 against full-diff pushes.** The 4 Tipo-I FPs that appeared were all in partial-diff or test-only follow-up pushes where the hook could not see symbols defined in earlier commits — the same FP class already documented in `reference_pre_push_hook_calibration`. No new FP class introduced.

### 5.2 Codex Connector review absorption

| PR | Codex reviews | Inline catches | Adjudication |
|---|---|---|---|
| #64 | 2 (commit-anchored to `2b16bc4cb7` + `ee6f6c3bfa`) | 4 P2 | All 4 adjudicated as already-addressed in `b1234c284` (canonical fields wired before review commit-anchor caught up) |
| #65 | 2 (`ac56664368` + `e52b8ce53d`) | 1 P1 + 1 P2 | Real P1 (`$effect` self-loop) absorbed in `e1752efab`; cross-RFQ reset P2 absorbed in same fix |
| #66 | silent 👍 | 0 | Codex did not post any inline catches on PR-A6-3 |
| #67 | silent 👍 | 0 | Codex did not post any inline catches on PR-A6-4 |

**Across A6 implementation PRs, Codex caught 1 real P1 (RFQ `$effect` self-loop, absorbed in `e1752efab`) and 5 P2s (all absorbed or adjudicated).** Codex silence on PR #66 and PR #67 is consistent with the established pattern that pre-emptive dispatch rigor + hook-v2 first-sieve compresses Codex catches into the early waves.

### 5.3 Backend pytest on final main `aa255e2be`

CI `Backend: pytest` ran green on the merge commit. No A6 PR touched backend code; the suite ran against the pre-existing 945 / 9 skipped baseline.

### 5.4 Frontend test growth

| Surface | Tests at A6 entry | Tests at A6 closure | Delta |
|---|---|---|---|
| `npm test` total | 113 (baseline pre-PR-A6-1) | **215** | **+102** |
| Test files | 9 | 18 | +9 |

New test files landed during A6:

- `frontend-svelte/src/lib/api/paths.test.ts`
- `frontend-svelte/src/lib/api/errors.test.ts`
- `frontend-svelte/src/lib/api/paths.drift.test.ts`
- `frontend-svelte/src/lib/api/contracts-settlement-guard.test.ts`
- `frontend-svelte/src/lib/api/page-contracts.test.ts`
- `frontend-svelte/src/lib/api/rfq-evidence-integrity.test.ts`
- `frontend-svelte/src/lib/api/analytics-response-shape.test.ts`
- `frontend-svelte/src/lib/rfq/quantity.test.ts`
- `frontend-svelte/src/lib/api/financial-display-precision.test.ts`
- `frontend-svelte/src/lib/config/runtime.test.ts`
- `frontend-svelte/src/lib/api/paths.orders-audit.test.ts`
- `frontend-svelte/src/lib/api/reconstructability-surfaces.test.ts`

Plus 5 new `userSub` cases inside `auth.svelte.test.ts`.

### 5.5 Static drift guards added

- `STALE_PATH_LITERALS` list in `frontend-svelte/src/lib/api/paths.ts` + `paths.drift.test.ts` fail-closes the build if any of the 7 retired stale URL literals reappears in `frontend-svelte/src` production code.
- `contracts-settlement-guard.test.ts` enforces page-level invariants on `VALID_TRANSITIONS` / `TRANSITION_CONFIG` / `transitionStatus` refusal.
- `rfq-evidence-integrity.test.ts` enforces source-scan invariants for actor identity (no `userName \|\| 'trader'`) and single-parse (no double `.json()` reads).
- `reconstructability-surfaces.test.ts` enforces page-level invariants on the new orders / audit routes + the auditor-only nav gate + the login dev-gate behaviour.

### 5.6 Hook artifact paths (for reproducibility)

Cached pre-push hook v2 reports for every A6 push live under `.cache/dispatch_review/` on each contributor checkout — they are not committed but are referenced by sha in each PR body for forensic replay.

---

## 6. Institutional surface added to main

### 6.1 New routes (read-only, contract-driven)

- `frontend-svelte/src/routes/(protected)/orders/+page.svelte` — order list
- `frontend-svelte/src/routes/(protected)/orders/[id]/+page.svelte` — order detail
- `frontend-svelte/src/routes/(protected)/audit/+page.svelte` — auditor-gated audit-event list + HMAC verification

### 6.2 New library modules

- `frontend-svelte/src/lib/api/paths.ts` — typed contract path builders + retired-literal drift guard
- `frontend-svelte/src/lib/api/errors.ts` — `describeApiError()` non-2xx body extractor
- `frontend-svelte/src/lib/api/analytics-response-shape.ts` — `validatePnlSnapshot` / `validateMtmSnapshot` runtime validators
- `frontend-svelte/src/lib/rfq/quantity.ts` — `validateMtQuantity` MT-scale validator (`MT_NUMERIC_SCALE = 3`)
- `frontend-svelte/src/lib/config/runtime.ts` — `runtimeFlags` singleton + dev-login gate with explicit reason codes
- `frontend-svelte/src/lib/api/types/entities.ts` — `OrderRead`, `OrderListResponse`, `AuditEventRead`, `AuditEventListResponse`, `AuditVerifyResponse`, `MarketPrice` (rebuilt to mirror `CashSettlementPriceRead`)

### 6.3 Modified routes

- `cashflow/+page.svelte` — canonical `/cashflow/analytic` + `/cashflow/projection` paths; ledger tab now reports missing parameter
- `contracts/+page.svelte` — `/contracts/hedge` list with explicit non-2xx banner
- `contracts/[id]/+page.svelte` — corrected detail path; settlement transitions removed from `VALID_TRANSITIONS`; defence-in-depth refusal in `transitionStatus`
- `analytics/mtm/+page.svelte` + `analytics/pnl/+page.svelte` — operator-supplied parameters; missing-parameter state on mount; runtime response-shape validators
- `rfq/[id]/+page.svelte` — `requireActorSub()` gate; `parseListBodyOnce()` + `describeListLoadFailure()`; evidence preserved on non-2xx reload
- `rfq/new/+page.svelte` — JWT `sub` actor; `step="0.001"` MT-quantity input with canonical string preservation
- `market-data/+page.svelte` — `formatPrice(price_usd, 'USD/MT')` with 6-decimal preservation; client-side computed row-to-row change
- `(public)/login/+page.svelte` — runtime-flag gated paste-token form; hard-fail config error in non-dev/non-opt-in builds
- `(protected)/+layout.svelte` — `/orders` always in nav; `/audit` only when `authStore.hasRole('auditor')`

### 6.4 Auth store surface change

- `frontend-svelte/src/lib/stores/auth.svelte.ts` — added immutable `userSub` accessor derived from JWT `sub` (returns `null` when absent). Caller contract: hard-fail on `null`, never coerce to display name.

---

## 7. Working-tree state at closure

Repo: `D:/Projetos/Hedge-Control-New` on `main` at `aa255e2be`.

- Tracked dirty: `.claude/scheduled_tasks.lock` (Claude harness lockfile, untouched)
- Untracked: `Python/` (untouched)
- No local A6 branches (all four implementation branches deleted from origin post-merge by the GitHub auto-cleanup; `git branch -a` confirms no `audit-a6/*` remnants)

Stale worktrees from prior phases still registered (not part of A6, no action without authorization):

- `D:/Projetos/Hedge-Control-New-pr-a3-4`
- `D:/Projetos/Hedge-Control-New-pr-a3-5`
- `D:/Projetos/Hedge-Control-New-pr-a4-1`
- `D:/Projetos/Hedge-Control-New-pr-a4-2`
- `D:/Projetos/Hedge-Control-New-pr-a4-3`

Open PRs unrelated to A6 (drafts from prior cycles, decision pending):

- #18 `codex/frontend-audited-lockfile`
- #19 `codex/frontend-table-warning-bundle-fixes`

---

## 8. Lessons absorbed across A6 (for future An phases)

1. **Pre-emptive dispatch rigor compresses Codex catches to zero on later waves.** PR #66 and PR #67 received zero Codex inline catches. The dispatch artifacts for those waves had already absorbed the conceptual catches that surfaced as P1/P2 in earlier waves' implementation phase. The institutional pattern from A2 ("dispatch-side rigor is multiplicatively cheaper than implementation-side rigor") held at the wave-to-wave level inside a single phase, not only at the PR-to-PR level.

2. **Hook v2 partial-diff FP class is now reproducible across phases.** A6 surfaced 4 Tipo-I FPs from hook v2, all on partial-diff or test-only follow-up pushes where the hook reviewed a 1-file diff and could not see symbols defined in earlier commits on the same branch. This is identical to the FP class documented in `reference_pre_push_hook_calibration` from A3. No new FP class. Hook v2 remains effective on full-diff pushes (0 P1, 2 absorbed P2 across A6).

3. **Frontend audit acceptance criteria are display-correctness + reconstructability, not mutation-safety.** A6 jury downgraded multiple Tier-1 candidates to Tier-2 with the same reasoning: display corruption is operator misdirection, not a submitted mutation. The only T1 findings (J-A6-02 settlement-via-status, J-A6-04 fabricated actor identity) both submitted incorrect mutations. This calibration should anchor future frontend phases.

4. **Frontend role gating is a UX courtesy, not a security boundary.** PR #67's `/audit` route hides the nav entry and the page body when `hasRole('auditor')` is false, but the backend `require_role("auditor")` on `/audit/events` and `/audit/events/{id}/verify` is the authoritative gate. The dispatch was explicit about this; future frontend phases must continue to draw this distinction in every role-gated surface.

5. **Settlement / actor-identity remediations are intrinsically dual-layer.** PR #64 + PR #65 both made frontend-only changes for findings whose canonical fix sits in the backend (status-endpoint refusal of `settled`; actor derivation from JWT). The frontend slice closed the jury finding; the backend slice is a documented cross-phase deferral. This split must be made explicit in every dual-layer remediation dispatch.

6. **Dev-login gates need three reason codes, not a boolean.** PR #67's `runtimeFlags` exposes `dev-mode`, `explicit-opt-in`, and `disabled-no-production-login` — each with a distinct operator-visible banner. A binary "enabled / disabled" would have failed the dispatch §4 requirement to *explain why* manual login is reachable in a given build.

---

## 9. Next-phase trigger

Phase A6 closed. Per the original handoff order, the four mandatory institutional audits (A1, A2, A3, A4, A5, A6) are all now closed:

| Phase | Status | Closed |
|---|---|---|
| A1 — Primitives Econômicas | ✅ closed | 2026-05-06 |
| A2 — RFQ Lifecycle | ✅ closed | 2026-05-09 |
| A3 — Valuation (MTM / P&L / Cashflow / Scenario) | ✅ closed | 2026-05-10 |
| A4 — Integrations | ✅ closed | 2026-05-10 |
| A5 — Cross-cutting | ✅ closed | 2026-05-12 |
| **A6 — Frontend** | **✅ closed** | **2026-05-13** |

Available next frentes (decision pending Andrei):

1. **Cross-phase deferral backlog.** Address one or more of the documented deferrals — backend RFQ actor derivation (A2 → A4 → A6), LLM confidence calibration (A2 → A4), LLM-generated outbound text (A2 → A4), backend status endpoint semantics (A6), token-storage hardening (A6), production IdP selection (A6), deal-engine price-reuse / scenario-vs-A1 exposure drift (A3 → A1 follow-up).
2. **Next institutional audit cycle.** Re-audit a closed phase with newer adversarial pairings (e.g., Phase A1 follow-up to close the deferred deal-engine + scenario-vs-A1 risks).
3. **Platform / infra phase.** Railway migration completion, IdP selection, token storage hardening, CSP/CSRF/XSS-sink inventory — all currently outside the audit-cycle protocol.

No automatic next-phase recommendation. Andrei to choose.
