# AGENTS.md — Greptile review loop for non-Claude-Code agents

This file teaches the Antigravity (Gemini) agent — and any other agent that doesn't auto-discover Claude Code's `~/.claude/skills/` — how to execute the two Greptile workflows we use on this repo.

Source of truth: `github.com/greptileai/skills` (vendored at `C:\Users\Andrei\.claude\skills\greptile\`). When in doubt, read `SKILL.md` there.

Repo context:
- Always GitHub (origin `github.com:andreiracha127/Hedge-Control-New`) — Perforce/GitLab branches in the upstream skills do not apply here.
- `gh` is authenticated as `Andreicr1`.
- Greptile is installed; `+1` reaction on the PR is the silent-acceptance signal (not just `/reviews`). Query `/issues/{N}/reactions` too.
- Pre-push hook v2 (`.githooks/pre-push`) runs an LLM dispatch-review on `docs/**/*-dispatch.md`. Don't `--no-verify` without orchestrator authorization.

---

## 1. `check-pr` — analyze an open PR

**When to run:** user says "check PR", "review feedback on PR N", "is PR N ready", or wants to triage unresolved comments + failing checks before merge.

**Inputs:** PR number (optional — defaults to the PR on the current branch).

### Steps

#### 1.1 Resolve PR number

```bash
PR=${1:-$(gh pr view --json number -q .number)}
OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
```

#### 1.2 Wait for pending checks to terminalize

```bash
while true; do
  ROLLUP=$(gh pr view "$PR" --json statusCheckRollup -q '.statusCheckRollup[]?.status' | sort -u)
  echo "$ROLLUP" | grep -qE '(PENDING|IN_PROGRESS|QUEUED)' || break
  sleep 30
done
```

#### 1.3 Fetch the four data sources

```bash
gh pr view "$PR" --json title,body,state,headRefName,headRefOid,reviews,statusCheckRollup
gh api "repos/$OWNER_REPO/pulls/$PR/comments"          # inline review comments
gh api "repos/$OWNER_REPO/issues/$PR/comments"         # general PR comments
gh api "repos/$OWNER_REPO/issues/$PR/reactions"        # silent +1 acceptance (Greptile / Codex pattern)
```

#### 1.4 Categorize each finding

| Category | Meaning | Action |
|---|---|---|
| **Actionable** | Code change / test / description fix | Fix, then resolve thread |
| **Informational** | LGTM, deploy preview, FYI | Resolve thread, no code change |
| **Already addressed** | Resolved by a later commit | Resolve thread |
| **Stale (pre-current-HEAD)** | `commit_id` of inline comment != current HEAD SHA | Resolve thread — don't re-fix (see `feedback_inline_review_commit_id_check`) |

Stale-check command for an inline comment ID:

```bash
gh api "repos/$OWNER_REPO/pulls/comments/<COMMENT_ID>" --jq '.commit_id'
# compare to: gh pr view "$PR" --json headRefOid -q .headRefOid
```

#### 1.5 Report

Output a markdown table with columns: Area | Issue | Status | Action Needed. Then ask the user whether to apply fixes.

#### 1.6 Apply fixes (only if user confirms)

1. Switch to the PR branch: `gh pr checkout "$PR"`.
2. Edit files.
3. Commit + push (let the pre-push hook run — do **not** add `--no-verify`).
4. Resolve threads (see §1.7).

#### 1.7 Resolve threads (GraphQL, batched)

Fetch unresolved thread IDs:

```bash
gh api graphql -f query='
query($owner:String!,$repo:String!,$pr:Int!,$cursor:String) {
  repository(owner:$owner,name:$repo) {
    pullRequest(number:$pr) {
      reviewThreads(first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { id isResolved comments(first:1) { nodes { body path author { login } } } }
      }
    }
  }
}' -F owner="$(echo $OWNER_REPO | cut -d/ -f1)" -F repo="$(echo $OWNER_REPO | cut -d/ -f2)" -F pr="$PR"
```

Paginate with `-F cursor=ENDCURSOR` if `hasNextPage` is true.

Batch-resolve with aliases (`t1`, `t2`, ...):

```bash
gh api graphql -f query='
mutation {
  t1: resolveReviewThread(input: {threadId: "THREAD_ID_1"}) { thread { isResolved } }
  t2: resolveReviewThread(input: {threadId: "THREAD_ID_2"}) { thread { isResolved } }
}'
```

---

## 2. `greploop` — iterate a PR until Greptile gives 5/5 + 0 unresolved

**When to run:** user says "greploop PR N", "loop greptile on PR N", or wants the PR optimized to a clean Greptile pass before merge.

**Inputs:** PR number (optional — defaults to current branch).

**Hard cap:** 5 iterations. Report and stop regardless of state.

### Iteration cycle

#### 2.A Trigger (or wait for) Greptile review

```bash
HEAD_SHA=$(gh pr view "$PR" --json headRefOid -q .headRefOid)

# Is Greptile already running? Don't re-request.
GREPTILE_STATE=$(gh pr checks "$PR" --json name,state \
  | jq -r '.[] | select(.name | test("greptile"; "i")) | .state')

if [[ "$GREPTILE_STATE" != "PENDING" && "$GREPTILE_STATE" != "IN_PROGRESS" ]]; then
  gh pr comment "$PR" --body "@greptile review"
fi
```

#### 2.B Poll Greptile check run until completed

```bash
while true; do
  RUN=$(gh api "repos/$OWNER_REPO/commits/$HEAD_SHA/check-runs" \
    --jq '.check_runs[] | select(.name | test("greptile"; "i"))' 2>/dev/null)
  [ -z "$RUN" ] && { sleep 5; continue; }
  STATUS=$(echo "$RUN" | jq -r '.status // "completed"')
  [ "$STATUS" = "completed" ] && break
  sleep 10
done
```

#### 2.C Fetch the latest score + unresolved comments

Score lives in one of two places — read **both**, keep the more recent:

```bash
gh pr view "$PR" --json body -q '.body'                    # PR description block
gh api "repos/$OWNER_REPO/pulls/$PR/reviews"               # filter author.login == "greptile-apps[bot]"
```

Parse for `Confidence: X/5` or `X/5`.

Unresolved inline comments:

```bash
gh api "repos/$OWNER_REPO/pulls/$PR/comments" \
  | jq '[.[] | select(.user.login | test("greptile"; "i"))]'
```

Cross-check resolution status against the GraphQL thread query in §1.7 (REST `pulls/comments` doesn't expose `isResolved`).

#### 2.D Exit conditions

Stop if **any** is true:
- Confidence == `5/5` AND zero unresolved Greptile threads.
- Iteration count == 5.

#### 2.E Fix actionable comments

For each unresolved Greptile thread:
1. Read the file at the line; understand context.
2. Actionable → apply fix.
3. Informational / false positive → still resolve the thread, note the rationale in the commit message.

Watch for two project-specific FP classes (from this repo's memory):
- **Companion-doc-not-yet-merged** — Greptile P2 about a doc that lives in a different PR is deferred, not actioned (`feedback_codex_companion_doc_not_yet_merged`).
- **Stale inline thread** — comment SHA != current HEAD SHA. Resolve, do not re-fix (`feedback_stale_inline_thread_survival`).

#### 2.F Commit, push, resolve, loop

```bash
git add -A
git commit -m "address greptile review feedback (greploop iter N)"
git push                  # pre-push hook will run on dispatch markdown — let it
```

Resolve resolved threads via the batched GraphQL mutation in §1.7. Then go back to §2.A.

### Final report

| Field | Value |
|---|---|
| PR | #N |
| Iterations | N (≤5) |
| Final confidence | X/5 |
| Comments resolved | N |
| Remaining unresolved | N |

If `Remaining > 0` after 5 iters, list them with file:line and the original comment body, then hand back to the human.

---

## Notes on this repo

- **Constitution / Governance** (`docs/systemconstitucion.md`, `docs/governance.md`) override convenience. If a Greptile catch contradicts a constitutional rule, halt and write `BLOCKED — requires governance decision` instead of pushing the fix.
- **Audit trail** mutations need HMAC signatures via `audit_trail_service`. Never bypass.
- **Dispatch markdown** (`docs/**/*-dispatch.md`) triggers the pre-push hook v2 LLM review before reaching Greptile. P1 from the hook blocks the push. Absorb the hook's catches first; *then* push and let Greptile see clean dispatches.
- **Codex Connector silent 👍 ships as a `+1` reaction**, not a review entry. Query `/issues/{N}/reactions` to detect acceptance — relevant to `check-pr` step 1.3.
