---
name: audit-cycle
description: Initiates a new Phase An or Cluster N adversarial audit cycle following the institutional protocol. Generates Stage 1/2/3 adversarial prompts, the jury-verdict markdown skeleton, and per-wave dispatch templates. Use when starting a new audit phase, opening a new cross-phase cluster, or kicking off a new findings round. Pairs with the `dispatch-author` skill (run that after the jury verdict lands).
---

# Audit Cycle Protocol — Phase An / Cluster N

This is the institutional audit cycle pattern used across Phase A1–A6 and Clusters 1–4. It is a reusable, deterministic protocol. Do not improvise the structure.

## Stages

```
Stage 1 (Opus)  ─┐
Stage 2 (Gemini) ┼─► Jury verdict ─► Wave dispatches ─► Executor sessions ─► Review gates ─► Merge
Stage 3 (GPT-5.5)┘
```

1. **Stage 1/2/3 adversarial findings** — three different frontier models, each blind to the others, produce a findings markdown.
2. **Jury verdict** — orchestrator adjudicates, classifies (T1/T2/T3 severity), declares closure waves.
3. **Wave dispatches** — one dispatch markdown per remediation wave (use the `dispatch-author` skill).
4. **Executor sessions** — one executor per dispatch produces one PR.
5. **Review gates** — pre-push dispatch-review hook + AugmentCode + Greptile.
6. **Merge** — Greptile `+1` reaction is the silent-acceptance signal.

## Artifact paths

All artifacts live under `docs/audits/` with date-prefixed kebab-case filenames:

```
docs/audits/
  2026-MM-DD-<phase|cluster>-stage1-opus-prompt.md
  2026-MM-DD-<phase|cluster>-stage1-opus-findings.md
  2026-MM-DD-<phase|cluster>-stage2-gemini-prompt.md
  2026-MM-DD-<phase|cluster>-stage2-gemini-findings.md
  2026-MM-DD-<phase|cluster>-stage3-gpt55-prompt.md
  2026-MM-DD-<phase|cluster>-stage3-gpt55-findings.md
  2026-MM-DD-<phase|cluster>-jury-verdict.md
  2026-MM-DD-<phase|cluster>-pr-1-<topic>-dispatch.md
  2026-MM-DD-<phase|cluster>-pr-2-<topic>-dispatch.md
  ...
  2026-MM-DD-<phase|cluster>-closure.md   (only when all waves merged)
```

## Workflow when invoked

When this skill is invoked, ask the user:

1. **Audit scope name** — e.g. `phase-a7`, `cluster-5`, `cluster-3-followup`.
2. **Subject** — what code/surface is under audit (e.g. "Cashflow projection + ledger reconciliation", "Frontend CSP enforcement").
3. **Today's date** — for the artifact prefix. Convert relative dates to absolute.

Then:

### Step 1 — Generate the three stage prompts

Each stage prompt is a markdown file in `docs/audits/` that the user will paste into the corresponding frontier model. Each prompt MUST include:

- **Role**: "You are a [Opus|Gemini|GPT-5.5] adversarial reviewer. You have not seen the other reviewers' findings."
- **Subject**: one paragraph describing the surface under audit, with file-path anchors.
- **Authority docs to consume**: `docs/systemconstitucion.md`, `docs/governance.md`, `CLAUDE.md`.
- **Findings format**: T1 (constitutional violation), T2 (governance drift), T3 (style/taste). Each finding requires: file path, line range, quoted snippet, constitutional anchor.
- **Anti-padding clause**: "If you find fewer than N issues, say so. Do not pad with style nits to inflate the count."
- **Output destination**: `docs/audits/<date>-<scope>-stage<N>-<model>-findings.md`.

Generate the prompt files via `Write`. Do NOT execute the models from inside this skill — the user runs each model independently against their preferred surface (browser, API console, CLI).

### Step 2 — Skeleton the jury verdict

Once the user reports all three findings files exist, generate `docs/audits/<date>-<scope>-jury-verdict.md` with this structure:

```markdown
# Jury Verdict — <Scope>

Date: <YYYY-MM-DD>
Status: DRAFT (awaiting adjudication)
Reviewers: Opus | Gemini | GPT-5.5

## Findings inventory

| ID | Severity | Subject | Files | Source(s) |
|----|----------|---------|-------|-----------|
| J-<scope>-01 | T1 | ... | ... | Opus §X, Gemini §Y |
| ... |

## Adjudication

For each finding, the jury declares:
- **CONFIRMED** — verified against code; goes to a wave dispatch.
- **MERGED** — duplicate of another finding; cross-reference.
- **REJECTED** — false positive; documented reason.
- **DEFERRED** — real but out-of-scope; cross-phase backlog entry.

## Wave structure

| Wave | Findings closed | Rationale |
|------|-----------------|-----------|
| PR-<scope>-1 | J-<scope>-01, J-<scope>-04 | Same surface; minimal review burden |
| PR-<scope>-2 | J-<scope>-02 | Standalone, large diff |

## Deferrals

| Finding | Defer to | Reason |
|---------|----------|--------|
| ... | Cluster N+1 | Touches surface under active migration |

## Closure criteria

- All CONFIRMED findings landed via merged PRs.
- Closure doc `<date>-<scope>-closure.md` written with metrics measured against merged HEAD (re-measure, do not copy from PR bodies — see `feedback_closure_metrics_remeasure`).
- All deferrals added to `docs/audits/<date>-cross-phase-deferral-backlog.md` if it exists; otherwise create.
```

Do NOT pre-fill the inventory rows — that is the user's adjudication work. Generate the skeleton only.

### Step 3 — Hand off to dispatch-author

Once the jury verdict has CONFIRMED findings assigned to waves, tell the user:

> Jury verdict skeleton at `<path>`. Once adjudicated, run `/dispatch-author <wave-id>` for each wave to author the per-PR dispatch markdown.

## Hard rules

- **Three distinct adversaries.** Not three runs of the same model. The diversity is the point.
- **Adjudicate, don't sum.** A T2 finding that three reviewers all flagged is still T2, not T1+T1+T1.
- **DEFERRAL is a first-class outcome.** Better to defer cleanly than to bundle scope creep into a wave.
- **Closure metrics are re-measured.** PR body metrics snapshot review-time state, not merged HEAD (`feedback_closure_metrics_remeasure`).
- **Codex is decommissioned.** Current review gates are AugmentCode (catches) + Greptile (catches + `+1` acceptance signal + Greptile Review CI check). See `reference_review_gates_2026_05_17`.

## Reference patterns

- Reusable cycle template: `reference_audit_cycle_pattern.md` (auto-memory)
- Recent closures: A6 (`docs/audits/2026-05-13-phase-a6-closure.md`), Cluster 4 PR-CL4-2 absorbed cleanly under new gates
- Anti-fabrication discipline: `feedback_executor_false_completion_pattern.md`
