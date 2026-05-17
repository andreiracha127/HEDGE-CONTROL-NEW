---
name: dispatch-author
description: Authors a wave dispatch markdown for a single jury-verdict wave, following the §1–§11 institutional structure and docs/audit-protocol/dispatch-review-rules.md. Pre-runs the self-consistency cross-section sweep before producing the file. Use after the `audit-cycle` skill produces an adjudicated jury verdict. Invoke as `/dispatch-author <wave-id>` (e.g. `/dispatch-author PR-CL5-1`).
---

# Dispatch Author — Wave Dispatch Markdown

This skill authors one wave dispatch markdown following the institutional §1–§11 structure. It is the protocol used for every dispatch from Phase A1 through Cluster 4.

## When to use

Invoke this skill **only** after a jury verdict exists with CONFIRMED findings grouped into a wave. The jury verdict lives at `docs/audits/<date>-<scope>-jury-verdict.md`. If no such verdict exists, hand back to the `/audit-cycle` skill.

## Mandatory pre-load

Before authoring, read these in full:

1. `docs/audit-protocol/dispatch-review-rules.md` — the rule sheet the pre-push hook will execute against this dispatch.
2. `docs/systemconstitucion.md` — supreme rules.
3. `docs/governance.md` — operational governance.
4. The jury verdict for the scope this wave belongs to.

If `docs/audit-protocol/dispatch-review-rules.md` does not exist, stop and tell the user — the rule sheet is required.

## Workflow when invoked

When invoked as `/dispatch-author <wave-id>`:

### Step 1 — Resolve the wave

From the wave id (e.g. `PR-CL5-1`), locate:
- The jury verdict file (most recent `*-jury-verdict.md` for the scope).
- The CONFIRMED findings assigned to this wave.
- The closure criteria specific to those findings.

If multiple jury verdicts could match, ask the user to disambiguate by date.

### Step 2 — Author the dispatch (§1–§11)

Generate `docs/audits/<date>-<scope>-pr-<N>-<topic>-dispatch.md` with this exact section structure:

```markdown
# <Wave id> — <Topic> Dispatch

Cycle: <Scope>
Wave: <wave-id>
Jury verdict: docs/audits/<verdict-file>
Findings closed by this wave: <J-IDs>
Status: DRAFT

## §1 Scope
What this PR delivers. One paragraph. Specific files and behaviors.

## §2 Boundary
What this PR DOES NOT touch. Other waves' scope, deferrals, future work.
Inconsistency between §1 and §2 is the #1 dispatch-review-rules catch — verify they don't overlap.

## §3 Pre-step (if any)
Manual SQL, env var rotation, dashboard config, anything the executor must do
BEFORE writing code. Often empty. If non-empty, must be plausible against
current code state (do not prescribe a migration that already shipped).

## §4 Backend changes
Per-file directive. Quote the line range that changes. Include:
- New columns / models / services / decorators
- Exact import paths
- Constitutional anchor for each rule being enforced

## §5 Database / Alembic changes
One numbered revision continuing from the current head. Include:
- `down_revision` set to the current head (check via `alembic heads`)
- SQLite-compatible DDL with `with_variant` fallbacks for Postgres-only types
- Idempotency on data backfills (`INSERT ... ON CONFLICT DO NOTHING` or equivalent)
- Forward + reverse pair (`upgrade()` and `downgrade()`)
- Chain hygiene: never rewrite an applied revision's `down_revision`

## §6 Frontend changes (if any)
SvelteKit 2 / Svelte 5 runes. Regen schema if backend types change:
`npm run api:types`. VITE_* vars live in `frontend-svelte/.env`.

## §7 Tests
- Backend: pytest, SQLite in-memory. Coverage target.
- Frontend: vitest. E2E only if surface is user-facing.
- RBAC matrix tests if route gates change.

## §8 Audit-trail emission
Every mutation in this PR's scope MUST emit an HMAC-signed audit row.
Cite `app/services/audit_trail_service.py:record(...)` call sites added.
If this PR also ships a *companion* audit-trail evidence PR, cross-reference
its branch / PR number here — but do not duplicate the content (see
`feedback_codex_companion_doc_not_yet_merged`).

## §9 Docs
Updates to `docs/governance.md`, `docs/systemconstitucion.md`, runbooks,
or `CLAUDE.md`. Often empty; non-empty means a constitutional clarification
is part of the wave.

## §10 Acceptance criteria
Bulleted, measurable. Each item must be verifiable post-merge by re-running
a specific command (`pytest tests/test_X.py::test_Y`, `alembic heads`,
`grep -rn ... | wc -l`). Avoid prose like "looks good" — that's untestable.

## §11 Workflow
1. Executor opens isolated branch from current main.
2. Implements §3–§9 in order.
3. Runs full test suite + ruff.
4. Pushes — pre-push hook reviews dispatch (it shouldn't fire on code-only push, but if
   the executor edited this dispatch file, the hook will run).
5. Opens PR linking back to this dispatch + jury verdict.
6. AugmentCode + Greptile review.
7. Greptile `+1` reaction is the silent-acceptance signal.
8. Merge when human approves + acceptance signals received.
```

### Step 3 — Self-consistency cross-section sweep

**Before writing the file**, run the sweep listed in `feedback_dispatch_self_consistency`:

- **Tipo I (fact mismatch)** — every cited import path, file path, line number, fixture name, and identifier exists in the actual code at the current HEAD. Verify with `grep` / `Read`. Do not trust memory.
- **Tipo II (self-defeat)** — §1/§2/§3/§4/§5/§6/§7/§8/§9/§10/§11 must not internally contradict. Common patterns: §4 deletes a method §10 asserts via test; §3 SQL pre-step duplicates a §5 migration; §10 acceptance criterion not measurable from §4–§9 deliverables.
- **Tipo III (layer-boundary inconsistency)** — backend contract change in §4 without §6 frontend regen step; new route in §4 without §7 RBAC matrix test; new mutation in §4 without §8 audit-trail emission directive.
- **Cross-section sweep** — verify §4, §6, §9, §10, §11 are pairwise consistent. This is the recurring missed-class from `project_phase_a2_w1b_pr5_dispatch_landed`.

If the sweep surfaces any contradiction, fix it in the draft before writing.

### Step 4 — Pre-authorize transport-partner client patches

Per `feedback_dispatch_transport_partner_clause`: if §4 ships a new backend transport contract (cookie shape, CSRF header, JWT claim, protocol header, OpenAPI route), §6 must pre-authorize the minimum-viable client patch needed to consume it. Artificial backend/frontend splits are untestable end-to-end and incentivize silent scope creep.

### Step 5 — Write the file and report

Write the dispatch markdown. Then report to the user:

```
Dispatch authored: docs/audits/<filename>
Findings covered: <J-IDs>
Self-consistency sweep: PASS | FAIL (<class>: <count>)

Next steps:
1. Review the dispatch markdown.
2. Push it (pre-push hook will run a tool-use review).
3. After hook + reviewer absorption, open the executor session.
```

## Hard rules

- **Do not duplicate the jury verdict content.** The dispatch consumes the verdict; the verdict is the canon. Reference, don't restate.
- **§3 pre-step must be plausible against the current code state.** If you can't quote the file the SQL touches, don't prescribe SQL.
- **§5 migrations must continue from the current head.** Run `alembic heads` (or equivalent) before authoring. Never rewrite ancestry.
- **§10 acceptance criteria must be commands, not adjectives.** "Tests pass" is not measurable; `pytest tests/test_X.py -v` is.
- **No prescriptive value uncited.** Every import/fixture/identifier in the dispatch must exist at HEAD or be explicitly marked as new (see `feedback_verify_lib_api_against_pinned_version`).
- **No directive that undermines §1's purpose.** The dispatch self-consistency rule (`feedback_dispatch_self_consistency`) is the single most-violated rule across cycles.

## Reference patterns

- Rule sheet: `docs/audit-protocol/dispatch-review-rules.md`
- Self-consistency feedback: `feedback_dispatch_self_consistency.md` (auto-memory)
- Recent dispatch landings: `project_cluster_4_pr1_dispatch_landed`, `project_cluster_3_dispatches_landed`
- Hook v2 active: dispatches will be reviewed by Sonnet 4.6 + tool-use on push
