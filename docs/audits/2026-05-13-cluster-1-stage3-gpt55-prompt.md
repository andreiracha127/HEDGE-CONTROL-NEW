# Cluster 1 Follow-Up Audit — Stage 3 Jury Dispatch

**Cluster:** 1 — A1 follow-up (deal-engine + exposure + scenario boundaries)
**Stage:** 3 of 3
**Target jury:** GPT 5.5
**Authoring date:** 2026-05-13
**Repository:** `D:/Projetos/Hedge-Control-New`
**Branch:** `main` @ `ba032f476` (post-Cluster-2 merge)
**Expected output:** `docs/audits/2026-05-13-cluster-1-jury-verdict.md`

## 1. Operating Instructions

You are the institutional jury for Cluster 1 (the A1 follow-up audit cycle). This is a read-only adjudication. Do not edit implementation code, tests, generated schemas, frontend files, migrations, or governance documents.

Your job is to adjudicate two independent backend auditor reports:

- **Auditor A (Opus 4.7):** `docs/audits/2026-05-13-cluster-1-findings-opus.md`
- **Auditor B (Gemini):** `docs/audits/2026-05-13-cluster-1-findings-gemini.md`

You must validate every accepted finding by reading the current code directly. Do not rubber-stamp either auditor. Do not reject a finding only because the other auditor missed it. Do not accept a finding unless it has a concrete failure mode supported by current backend code and, where relevant, the constitutional clause it violates.

Two of the four deferred surfaces — **D-1.3** (snapshot reuse on total price unavailability) and **D-1.4** (scenario aggregation duplication) — require explicit **institutional decisions**. The A3 jury punted these decisions to this follow-up audit. Your verdict must:

1. State a binding decision for D-1.3 ("accept reuse" / "always propagate unprovable" / "gate reuse with explicit flag + signed audit" / other), with constitutional rationale.
2. State a binding decision for D-1.4 ("extract shared primitive" / "maintain duplication with invariance test" / "other"), with constitutional rationale.
3. Carry those decisions into the recommended remediation waves so the implementation phase has unambiguous direction.

## 2. Inputs

Read these files first:

- `docs/governance.md`
- `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` §Cluster 1
- `docs/audits/2026-05-13-cluster-1-stage1-opus-prompt.md`
- `docs/audits/2026-05-13-cluster-1-stage2-gemini-prompt.md`
- `docs/audits/2026-05-13-cluster-1-findings-opus.md`
- `docs/audits/2026-05-13-cluster-1-findings-gemini.md`
- `docs/audits/2026-05-06-phase-a1-jury-verdict.md` — sections for `J-A1-OPUS-07` and `J-A1-OPUS-08`
- `docs/audits/2026-05-09-phase-a3-jury-verdict.md` §8 — `X-A3-J-01` and `X-A3-J-02`

Then inspect implementation evidence in the Cluster 1 backend scope:

- `backend/app/models/deal.py` — `Deal`, `DealLink`, lifecycle columns.
- `backend/app/models/exposure.py` — `Exposure`, `ContractExposure`, `HedgeExposure`, `HedgeTask`, lifecycle.
- `backend/app/services/deal_engine.py` — `add_link`, `remove_link`, `compute_deal_pnl` (especially the snapshot-reuse repair path), `compute_pnl_breakdown`, `update_deal_status`, `_recompute_tons`.
- `backend/app/services/exposure_engine.py` — `reconcile_from_orders` (§3.7 + §3.8), `_get_linked_qty_map`, `cancel_stale_tasks`, `list_pending_tasks`.
- `backend/app/services/exposure_service.py` — `compute_commercial_snapshot`, `compute_global_exposure`.
- `backend/app/services/scenario_whatif_service.py` — `_compute_commercial_exposure`, `_compute_global_exposure`, `_apply_deltas`, `run_what_if`.
- `backend/app/services/linkage_service.py` — `LinkageService.create` + every reader of `DealLink`.
- `backend/app/api/routes/deals.py`, `routes/exposures.py`, `routes/scenario.py`.
- Tests under `backend/tests/` covering these surfaces.

Derive current surface state via repo searches; do not trust the auditors' or original A1/A3 line citations:

- `rg -n "is_deleted|deleted_at" backend/app/models backend/app/services`
- `rg -n "DealLink" backend/app`
- `rg -n "DealPNLSnapshot|inputs_hash|unprovable_errors" backend/app/services/deal_engine.py`
- `rg -n "compute_commercial_exposure|compute_global_exposure|compute_commercial_snapshot" backend/app`
- `rg -n "PriceReferenceUnprovable" backend/app`

## 3. Binding Governance

Binding governance is `docs/governance.md`. For Cluster 1, these clauses are central:

- **§2.1 Economic primitives integrity** — exposure aggregation is canonical; duplication that creates drift potential is a finding under §2.1.
- **§2.6 No silent fallback / no overflow clamp** — silent extrapolation of economic state is a hard-fail condition.
- **§2.7 Audit reconstructability** — every economic mutation has reconstructible evidence; soft-delete must not orphan referential evidence; lifecycle must be explicit.
- Evidence missing and unprovable references are hard-fail.
- Phases remain explicit; do not broaden Cluster 1 into Cluster 2 / 3 / 4.

Hard-fail, determinism, auditability, reconstructability, no silent fallback, and lifecycle explicitness remain mandatory.

## 4. Jury Questions

For each auditor finding, answer:

1. Is the cited code path reachable in the current backend? (Verify the file and line against `main @ ba032f476`.)
2. Does the failure involve a real model, service, route, or aggregation primitive, or is it speculative?
3. Can it produce wrong P&L, wrong exposure aggregate, wrong scenario projection, wrong deal lifecycle decision, or break reconstructability of a closed A1/A3 invariant?
4. Does another layer (DB constraint, signed audit event, transactional boundary) make the finding non-blocking, and if so, what severity remains?
5. Does the finding belong in Cluster 1, or should it be deferred to Cluster 2 (closed) / 3 (security/platform) / 4 (market-data governance) / a separate future cycle?
6. Is the remediation boundary small enough for a controlled PR wave?

You may add fresh findings only if both auditors missed a concrete, evidence-backed issue discovered during adjudication. Fresh findings must meet the same standard as accepted auditor findings.

For **D-1.3** specifically, your verdict must state:

- Whether the current `compute_deal_pnl` snapshot-reuse path on `unprovable_errors` is institutionally legitimate.
- If accepted: under what conditions (e.g. "only when at least one persisted `price_reference` is fresher than X days", or "only with a corresponding signed audit row").
- If rejected: the constitutional shape of the fix (e.g. "always raise `PriceReferenceUnprovable` when zero live quotes are available").
- A one-paragraph constitutional rationale grounded in §2.6, §2.7, and the "no silent fallback" rule.

For **D-1.4** specifically, your verdict must state:

- Whether `scenario_whatif_service` may continue to duplicate aggregation logic or must be refactored to a shared primitive.
- If extraction is required: where the new primitive lives (e.g. `ExposureService.compute_commercial_exposure_pure`), what its signature is in outline (inputs / outputs), and whether scenario consumes it directly or wraps it with virtual-delta adjustments.
- If duplication is acceptable: under what discipline (e.g. "an invariance test asserting parity between scenario aggregation and live aggregation on a fixed fixture").
- A constitutional rationale grounded in §2.1.

## 5. Severity Taxonomy

Use this taxonomy:

- **Tier 1 / Blocking:** The backend can produce an incorrect economic state (wrong P&L, wrong exposure aggregate, wrong scenario projection, wrong deal lifecycle decision) or make a closed A1/A3 invariant unreconstructible. Includes silent fallback of stale price evidence without hard-fail.
- **Tier 2 / High:** Real edge case can mislead operators or stale critical state; live-data semantics remain correct under typical flow. Includes drift potential between scenario and live aggregation under a future A1 evolution.
- **Tier 3 / Medium:** Localized robustness, evidence, or coverage gap with plausible operational impact; no immediate economic-correctness breach.
- **Tier 4 / Low:** Documentation, cosmetic, test-only, or observability improvement. Do not carry Tier 4 unless it protects a concrete Cluster 1 boundary.

If an auditor overstates severity, downgrade. If an auditor understates a governance breach, upgrade. Explain every severity change.

## 6. Verdict Format

Write the verdict to:

`docs/audits/2026-05-13-cluster-1-jury-verdict.md`

Use this structure:

```markdown
# Cluster 1 Follow-Up Audit — Jury Verdict

## Executive Summary

- Total accepted findings: N
- Tier 1: N
- Tier 2: N
- Tier 3: N
- Tier 4: N
- Rejected auditor findings: N
- Fresh jury findings: N
- Original A1/A3 deferrals retired: M/4 (which of D-1.1 / D-1.2 / D-1.3 / D-1.4)

## Institutional Decisions

### D-1.3 — Deal Engine snapshot reuse on total price unavailability

**Decision:** Accept | Reject | Conditional accept (with the conditions named below)

**Rationale:**
One paragraph grounded in §2.6 (no silent fallback), §2.7 (reconstructability),
and the "evidence missing is hard-fail" rule.

**Implementation shape:**
The constitutional shape of the fix (or the conditions under which current
behavior is acceptable).

### D-1.4 — Scenario duplicates A1 exposure aggregation

**Decision:** Extract shared primitive | Maintain duplication with invariance test | Other

**Rationale:**
One paragraph grounded in §2.1 (economic primitives integrity) and drift-prevention discipline.

**Implementation shape:**
Where the shared primitive lives (or how the parity invariance is enforced).

## Accepted Findings

### J-CL1-XX — Canonical title

**Source:** Opus J-CL1-OPUS-XX | Gemini J-CL1-GEMINI-XX | Jury Fresh
**Severity:** Tier N / Blocking|High|Medium|Low
**Status:** Open
**Disposition:** Accepted | Accepted with severity change | Accepted as subsumed
**Deferral source:** D-1.1 | D-1.2 | D-1.3 | D-1.4 | Fresh
**Evidence:**
- `path/to/file.py:123` — code evidence at current main
- `path/to/test.py:456` — test gap or assertion, if relevant

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

### Auditor finding ID — short title

**Disposition:** Rejected
**Reason:** Evidence-based reason, with file/line references where relevant.

## Subsumed Findings

Map duplicate auditor findings to the canonical accepted finding.

## Cross-Cluster Deferrals

Items that are real but belong to Cluster 3 (security / platform), Cluster 4 (market-data governance), or a later cross-phase cleanup.

## Recommended Remediation Waves

### PR-CL1-1 — Short wave title
- Findings: J-CL1-...
- Scope boundary:
- Required verification:

### PR-CL1-2 — Short wave title
- Findings: J-CL1-...
- Scope boundary:
- Required verification:

## Anti-Findings Confirmed

Important suspected issues that were checked and found safe, with evidence.

## Self-Bias Confession

Identify any places where you gave benefit of the doubt to one auditor, where you upgraded or downgraded severity against the auditor recommendation, and where the available evidence was thin. State what additional verification would change your verdict.
```

## 7. Adjudication Rules

- Convergent findings (both auditors raised it) are not automatically correct. Verify them.
- Single-auditor findings are not automatically weak. Verify them.
- Reject findings that are merely style or generic "extract helper" preferences without a concrete institutional failure mode.
- Preserve narrow PR boundaries. Do not turn Cluster 1 into a wider service-layer rewrite.
- Do not alter `docs/governance.md`.
- Do not recommend merge of any future PR. This stage produces only the verdict + remediation sequencing.
- If either Stage 1 or Stage 2 report is missing or empty, stop and report the cycle as incomplete rather than fabricating a verdict.
- **For D-1.3 and D-1.4, you must produce a decision.** Punting to a further future audit is not allowed; the institutional debt has been deferred long enough.

## 8. Allowed Read-Only Verification

You may run read-only or build/test commands if useful:

- `pytest -q backend/tests`
- `pytest -q backend/tests/test_deal_engine*.py`
- `pytest -q backend/tests/test_exposure*.py`
- `pytest -q backend/tests/test_scenario*.py`
- `pytest -q backend/tests/test_linkage*.py`
- `python -m alembic heads` (must remain single head; you are not proposing migrations).
- Serena symbolic queries (`find_symbol`, `find_referencing_symbols`, `get_symbols_overview`).

Report any command run and its result. If a command is unavailable, state that explicitly and continue with direct code evidence.

## 9. Workflow

1. Read `docs/governance.md`, the cross-phase backlog §Cluster 1, both stage prompts, both findings reports, and the prior A1/A3 jury verdict excerpts.
2. Verify every cited code path against `main @ ba032f476`.
3. For each auditor finding, apply §4 jury questions and produce a disposition with evidence.
4. Produce binding institutional decisions for D-1.3 and D-1.4 (mandatory; see §1 and §6).
5. Group accepted findings into 2–4 recommended remediation waves with explicit scope boundaries.
6. Write the verdict to `docs/audits/2026-05-13-cluster-1-jury-verdict.md`.
7. Do not edit anything else.

## 10. Closure Criterion

This stage closes when the verdict is written and contains:

- Accepted / rejected / subsumed dispositions for every auditor finding.
- Binding decisions for D-1.3 and D-1.4 with constitutional rationale.
- 2–4 recommended remediation waves with scope boundaries small enough that each wave maps to a single executor PR.
- An honest self-bias confession.

The verdict is the input to the next phase (Cluster 1 remediation dispatches, authored after this verdict lands).
