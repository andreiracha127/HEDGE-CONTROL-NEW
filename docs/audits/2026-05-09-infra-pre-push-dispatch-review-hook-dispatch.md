# Infra — Pre-push Dispatch Review Hook — Dispatch

**Track:** Infra (non-audit — reduces Codex round inflation across audit cycles)
**Authoring date:** 2026-05-09
**Branch name:** `infra/pre-push-dispatch-review`
**Base:** `main` (currently `030a49bff`, post-Phase-A3-Wave-1)
**Findings covered:** none (this dispatch ships *tooling* that complements the Codex review pipeline; it does NOT touch any audit finding)

---

## 0. Motivation

Codex Connector reviews are the institutional final-line authority for dispatch correctness (`feedback_review_priority`: "Codex Connector outranks CI green"; `reference_codex_connector_calibration`: ~100% accuracy across hundreds of bugs). They are also **slow at the cycle level** — not because Codex itself is slow per round, but because each dispatch tends to require 5–13 sequential rounds to converge:

- PR #37 (A2 W-1b PR-5 dispatch): **14 catches across 10 rounds**.
- PR #40 (A3 Wave 1 PR-A3-1 dispatch): **25 catches across 13 rounds — record**.
- PR #42 (A3 Wave 2 PR-A3-2 dispatch, Iteration 1): 1 catch (P2) — Tipo I fact-mismatch, scenario response shape.

Each round consumes orchestrator wall-time (read catch → verify via Serena → 8-section sweep → edit → push → wait Codex re-review). 13 rounds at ~10–20 min/round = 2–4 hours of orchestration per dispatch. Across the remaining A3 waves (3 more) + Phase A4/A5/A6, the round count is the dominant cycle-time driver.

Many of the catches Codex returns are **mechanically detectable** — they fail one of the 30+ accumulated sub-rules in `feedback_dispatch_self_consistency`:

- **Tipo I fact-mismatch**: prescribed identifier doesn't exist (function signature, schema field, enum member, dict key, file path).
- **Tipo II self-defeat**: §3 prescribes work that §10 forbids; §6 acceptance bullet contradicts §3 implementation; §11 step references a function whose existence §3 deletes.
- **Sibling-bullet sweep miss**: updated bullet in a list with siblings carrying inconsistent identifiers/shape.
- **Concrete-code identifier verification**: dict literal / kwargs / ORM `Model(...)` enumeration missing a field that the schema requires.
- **Lookup chain end-to-end**: prescribed lookup key but the producer or consumer wasn't verified.
- **Pricing-domain awareness**: `strip(...)` with hyphen/plus/period/comma in pricing context.
- **Coverage validation**: static map keyed by year/version that fails-open instead of fails-closed outside maintained scope.
- **Decimal precision quantization**: full-precision computation crossing into rounded DB column without quantization at the boundary.
- **Schema CHECK constraint awareness**: implementation assumption about field semantics not verified against `__table_args__`.

A pre-push LLM pass that captures ~60–75 % of these mechanical catches would compress the Codex round count from 13 → 4–6, recovering 60–80 % of the per-dispatch orchestrator cost. The hook is a **first sieve**, not a replacement for Codex (which remains the final-line authority per `feedback_review_priority`).

This dispatch ships:

1. A Python script `scripts/pre_push_review.py` that invokes Anthropic Claude Sonnet 4.6 to review dispatch markdown files against the institutional self-consistency rules and produces a structured `{p1, p2, p3}` finding list.
2. A versioned `.githooks/pre-push` shell wrapper that triggers the script when a `docs/**/*-dispatch.md` file is in the push range.
3. A versioned rule sheet `docs/audit-protocol/dispatch-review-rules.md` that consolidates the 30+ sub-rules from `feedback_dispatch_self_consistency` into a hookable artifact (memory files are per-user; the repo file is shareable).
4. A bootstrap script `scripts/install_git_hooks.py` that runs `git config core.hooksPath .githooks` (one-time per clone).
5. Anthropic SDK pinned in `backend/requirements.txt`.
6. README / AGENTS update documenting the install step + bypass rules.

---

## 1. Mission

Reduce Codex review round count per dispatch by ~60 % via a pre-push LLM-based first-sieve review. The sieve must:

- Be **fast enough** that orchestrator wall-time per push stays under 60 s (Sonnet 4.6 typical 15–40 s for ~30 k token input).
- Be **scope-targeted** — only fires when a dispatch markdown is in the push diff. Regular code commits, doc edits not touching dispatches, and bug-fix branches all skip the LLM call.
- Produce **structured output** so the hook can mechanically decide block/warn/exit. P1 findings block the push (`exit 1`); P2/P3 print and exit 0.
- Be **bypassable** via `git push --no-verify` (consciously opt-out, not silent fallback). Per `feedback_dispatch_self_consistency` "DO NOT use --no-verify to skip git hooks": the bypass is a deliberate orchestrator decision, not a default state.
- Be **auditable** — every push that triggers the hook leaves a JSON artifact in `.cache/dispatch_review/<branch>-<sha>.json` so the orchestrator can post-mortem disagreements with Codex.

After this dispatch ships, the Codex feedback loop on subsequent dispatches should drop from 5–13 rounds → 1–4 rounds. The orchestrator continues to wait for Codex top-level review (`feedback_review_priority` unchanged); the hook only changes what arrives at Codex's input.

**Persona for the LLM acting as reviewer**: senior software engineer with decades of experience in institutional financial systems (asset management, derivatives, MTM/P&L attribution, multi-curve valuation). Same persona as the orchestrator — adversarial-tuned. The system prompt enforces this explicitly.

---

## 2. Reference docs (read before coding)

- **`docs/governance.md`** — full file (217 lines). Cached as the constitutional ground truth.
- **`C:\Users\Andrei\.claude\projects\d--Projetos-Hedge-Control-New\memory\feedback_dispatch_self_consistency.md`** — 53 lines. The accumulated 30+ sub-rules. **The new in-repo rule sheet (§3.3) is derived from this; the memory file remains the orchestrator's persistent source of truth.**
- **`memory\feedback_review_priority.md`** — Codex outranks CI green; the hook does NOT replace Codex.
- **`memory\reference_codex_connector_calibration.md`** — Codex calibration record (~100 % accuracy); hook calibration target (~60–75 % capture rate of mechanical catches).
- **`memory\feedback_verify_lib_api_against_pinned_version.md`** — when prescribing any library API call (Anthropic SDK shape, Pydantic schema, etc.), verify against actual pinned version before authoring.
- **`docs/audits/2026-05-09-phase-a3-pr-1-price-provenance-dispatch.md`** — the 13-round / 25-catch dispatch (PR #40). Reference for the kinds of catches Codex produced; the hook's rule set is calibrated against this corpus.
- **`docs/audits/2026-05-09-phase-a3-pr-2-commodity-correctness-dispatch.md`** — the current PR #42 dispatch (Iteration 2). Reference for the structural shape the hook is reviewing.
- **`backend/requirements.txt`** — pinning convention. Existing entries `httpx==0.28.1`, `openai==2.34.0`. Anthropic SDK is added per §3.4.
- **`package.json` (root)** — minimal monorepo root; `engines.node>=18`. The hook does NOT add npm dependencies (Python-only).

---

## 3. Scope IN — what this PR ships

> **Verification disclaimer:** every prescribed module path, function signature, requirements pin, and SDK identifier in §3 was authored against `030a49bff` (post-Wave-1) **OR** marked as VERIFY-LATEST where the upstream is volatile (Anthropic SDK version). Treat VERIFY-LATEST tags as mandatory — pin to the latest stable at implementation time.

### 3.1 `scripts/pre_push_review.py` — the LLM call wrapper

New file. Single-purpose CLI script invoked by the hook. Reads a list of dispatch file paths from stdin, calls Anthropic API, writes JSON output, decides exit code.

#### 3.1.1 CLI shape

```
python scripts/pre_push_review.py \
    --dispatch-paths docs/audits/2026-05-09-phase-a3-pr-2-commodity-correctness-dispatch.md \
    --branch audit-a3/pr-2-dispatch \
    --head-sha b9c6146f5
```

Or via stdin:

```
git diff --name-only origin/audit-a3/pr-2-dispatch..HEAD -- 'docs/**/*-dispatch.md' \
    | python scripts/pre_push_review.py --branch audit-a3/pr-2-dispatch --head-sha b9c6146f5
```

#### 3.1.2 Module structure

```
scripts/
  pre_push_review.py        # CLI entrypoint
  dispatch_review/
    __init__.py
    client.py               # Anthropic API call + retry/backoff
    prompt_builder.py       # Assembles cached system blocks + variable user block
    schema.py               # Pydantic output schema (P1/P2/P3 findings)
    rules.py                # Loads docs/audit-protocol/dispatch-review-rules.md as a string
    file_resolver.py        # Resolves "cited file paths" inside the dispatch (regex on `backend/...`, `docs/...`)
    cache.py                # Reads/writes .cache/dispatch_review/*.json artifacts
```

Single-package layout under `scripts/`. No new top-level Python package; the hook script is not part of the FastAPI backend.

#### 3.1.3 Anthropic API call

```python
# scripts/dispatch_review/client.py
from anthropic import Anthropic

_MODEL = "claude-sonnet-4-6"  # VERIFY-LATEST: confirm this is still the current Sonnet 4.6 production identifier (or the dated form the SDK release notes prefer at implementation time); do NOT use any `latest` alias

def call_review(
    *,
    cached_system_blocks: list[dict],   # governance + rule sheet + memory feedbacks
    user_payload: str,                   # dispatch text + cited file excerpts + diff range
    tools: list[dict],                   # the report_findings tool schema
) -> dict:
    client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    response = client.messages.create(
        model=_MODEL,
        max_tokens=8192,
        system=cached_system_blocks,
        tools=tools,
        tool_choice={"type": "tool", "name": "report_findings"},
        messages=[{"role": "user", "content": user_payload}],
    )
    # The model is forced to call report_findings; extract its input.
    for block in response.content:
        if block.type == "tool_use" and block.name == "report_findings":
            return block.input
    raise RuntimeError("Model did not call report_findings tool")
```

**Why `tool_choice={"type": "tool", "name": "report_findings"}`**: forces the model to call exactly that tool, guaranteeing structured JSON output. Without forcing, the model may emit prose. **VERIFY-LATEST**: confirm the `tool_choice` shape against the SDK version pinned in §3.4 (Anthropic SDK API surface for tool-use forcing has been stable since 0.30.x but verify before authoring).

**Pin the explicit non-aliased form** (e.g. `claude-sonnet-4-6` if that remains the current stable, or whatever dated form the SDK release notes prefer at implementation time). Do NOT use `claude-sonnet-latest`-style aliases — institutional reproducibility requires a frozen model identifier so the rule-set calibration stays stable across runs. Verify the identifier against the Anthropic SDK release notes / Claude API model docs immediately before authoring, since model lifecycle moves fast.

**Retry/backoff**: on `anthropic.RateLimitError` or `anthropic.APIConnectionError`, retry up to 3× with exponential backoff (1s, 4s, 16s). On `anthropic.AuthenticationError`, fail fast (no retry — credential issue, not transient).

#### 3.1.4 Cached system blocks

```python
# scripts/dispatch_review/prompt_builder.py

def build_cached_system_blocks(repo_root: Path) -> list[dict[str, Any]]:
    """Return 4 system blocks. Blocks 1-3 are cached (TTL 5 min ephemeral);
    block 4 (the review protocol prose) is small and not worth caching.

    Block 1 — persona preamble (stable string constant)
    Block 2 — docs/governance.md (stable per main HEAD)
    Block 3 — docs/audit-protocol/dispatch-review-rules.md (stable per rule-sheet HEAD)
    Block 4 — review protocol prose (the 8-section sweep instructions)
    """
    return [
        {
            "type": "text",
            "text": _PERSONA_PREAMBLE,           # ~500 tokens
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": load_governance(repo_root),   # ~6000 tokens
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": load_rule_sheet(repo_root),   # ~5000 tokens (30 rules)
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": _REVIEW_PROTOCOL_PROSE,       # ~400 tokens, dispatch-specific
            # No cache_control on the last block — small + dispatch-specific
        },
    ]
```

**Memory feedback files NOT in the system prompt**: `<memory>/feedback_*.md`
under the orchestrator's per-user Claude Code directory are NOT loaded by
the hook. They are per-user and not shareable across the repo. The
versioned rule sheet at `docs/audit-protocol/dispatch-review-rules.md` is
the canonical in-repo distillation — every sub-rule absorbed into the
memory MUST be appended to the rule sheet in the same commit (institutional
invariant; see §3.3).

Per Anthropic prompt caching docs (VERIFY-LATEST against the SDK version): `cache_control: {"type": "ephemeral"}` on a system block makes the block + everything before it cacheable. TTL is **~5 minutes by default at authoring time** (VERIFY-LATEST: confirm against current Anthropic prompt-caching docs at implementation time). The block ordering above places stable content first (persona → governance → rule sheet) so cache hits land on the first three blocks consistently and only the trailing review-protocol prose re-bills.

**Token budget per call**:
- Cached system: ~12 k tokens (cache write on first call; cache read on subsequent calls within 5 min)
- User payload (dispatch + cited files): ~30–80 k tokens
- Output: ≤ 8 k tokens (forced into `report_findings` tool input)
- **Total**: ~50–100 k tokens — well under Sonnet 4.6's 200 k context.

**Cost target**: with prompt caching active and 3-tier discount on cached reads (~10 % of normal input cost), per-push cost lands around **R$ 1.50 – 4.00 / push** at current Anthropic pricing. Without caching: **R$ 5–12 / push**. Cache hit-rate target across a working session: > 70 %.

#### 3.1.5 User payload

```python
# scripts/dispatch_review/prompt_builder.py

def build_user_payload(dispatch_paths: list[Path], head_sha: str, branch: str) -> str:
    parts: list[str] = []
    parts.append(f"## Dispatch review request — branch {branch} @ {head_sha}\n")
    for path in dispatch_paths:
        parts.append(f"\n### Dispatch file: `{path}`\n")
        parts.append("```markdown\n")
        parts.append(path.read_text(encoding="utf-8"))
        parts.append("\n```\n")
        # Resolve cited backend/docs files inside the dispatch and inline them.
        cited = resolve_cited_files(path)
        for cited_path, excerpt in cited.items():
            parts.append(f"\n#### Cited file (verbatim excerpt): `{cited_path}`\n")
            parts.append("```\n")
            parts.append(excerpt)
            parts.append("\n```\n")
    return "".join(parts)
```

#### 3.1.6 `file_resolver.resolve_cited_files`

Regex-extract paths matching `backend/app/**/*.py`, `backend/tests/**/*.py`, `docs/governance.md`, `docs/audits/**/*.md` from the dispatch markdown. For each, read the file and include either (a) the full file if ≤ 300 lines, or (b) the symbol bodies referenced by name in the dispatch (function/class names extracted via regex). Cap each cited file at 200 lines of context to keep payload ≤ 80 k tokens.

**Out-of-scope file types**: do NOT auto-include `frontend-svelte/**/*.ts` (frontend audit is Phase A6; current dispatches don't reference frontend identifiers in concrete code).

**Alembic migration files**: include them when explicitly cited (e.g. `backend/alembic/versions/038_a3_price_provenance.py` in a PR-A3-1-style dispatch). Migration concrete-code blocks (`op.add_column`, `op.batch_alter_table`, `op.create_table` arguments) are common Tipo-I catch surface — auto-excluding them silently degrades hook recall on a known catch class. The narrowed heuristic: include alembic version files matched by `backend/alembic/versions/[^`\s]+\.py` in the dispatch text; do not pull in *all* migrations indiscriminately.

#### 3.1.7 Output schema (Pydantic)

```python
# scripts/dispatch_review/schema.py
from typing import Literal
from pydantic import BaseModel, Field

class Finding(BaseModel):
    rule: str = Field(..., description="The self-consistency sub-rule violated, e.g. 'Tipo-I-fact-mismatch'")
    section: str = Field(..., description="Dispatch section the violation lives in, e.g. '§3.7.5'")
    snippet: str = Field(..., max_length=1200, description="The exact dispatch excerpt that violates the rule")
    why: str = Field(..., max_length=2500, description="Why this is wrong (cite the file/symbol that contradicts it)")
    fix_suggestion: str = Field(..., max_length=2000, description="Concrete suggestion for resolving the catch")

class ReviewReport(BaseModel):
    p1_blocking: list[Finding] = Field(default_factory=list, description="Tier-1 blocking findings; non-empty list halts the push")
    p2_warn: list[Finding] = Field(default_factory=list, description="Tier-2 warnings; printed but do not block")
    p3_info: list[Finding] = Field(default_factory=list, description="Informational; printed quietly")
    summary: str = Field(..., max_length=2000, description="One-paragraph summary of the dispatch's overall self-consistency state")
```

#### 3.1.8 Tool-use schema for forced structured output

```python
# scripts/dispatch_review/schema.py

REPORT_FINDINGS_TOOL = {
    "name": "report_findings",
    "description": "Report the dispatch self-consistency review findings, partitioned into P1 (blocking), P2 (warning), P3 (info).",
    "input_schema": ReviewReport.model_json_schema(),
}
```

The model is forced to call this tool exactly once via `tool_choice`. Its `input` payload validates against `ReviewReport.model_json_schema()`.

**VERIFY-LATEST**: confirm `model_json_schema()` produces a JSON Schema with `type: "object"` at the top level (Anthropic tool-use requires `type: object` at the root). If Pydantic emits a `$defs`-only top level, wrap manually.

#### 3.1.9 Block/warn decision

```python
# scripts/pre_push_review.py (entry)

def main() -> int:
    paths = read_dispatch_paths_from_args_or_stdin()
    if not paths:
        print("[pre-push-review] no dispatch files in push range -- skipping")
        return 0
    try:
        report = run_review(paths, branch=..., head_sha=...)
    except (RuntimeError, anthropic.APIError) as exc:
        # No silent fallback: per §5, API failures must produce a clear
        # non-zero exit, not a traceback.
        print(f"[pre-push-review] API call failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    write_cache_artifact(report, branch=..., head_sha=...)
    if report.p1_blocking:
        print_findings(report.p1_blocking, level="P1 BLOCKING")
        print(f"\n[pre-push-review] {len(report.p1_blocking)} P1 finding(s) -- push blocked. Use `git push --no-verify` to override (not recommended).")
        return 1
    if report.p2_warn:
        print_findings(report.p2_warn, level="P2 WARNING")
    if report.p3_info:
        print_findings(report.p3_info, level="P3 INFO")
    return 0
```

#### 3.1.10 Cache artifact

Write `.cache/dispatch_review/{branch_slug}-{head_sha}.json` containing the full `ReviewReport` JSON. `branch_slug` strips slashes (`audit-a3/pr-2-dispatch` → `audit-a3-pr-2-dispatch`). The `.cache/` directory is gitignored (verify before push: amend `.gitignore` if `.cache/` is not already ignored).

### 3.2 `.githooks/pre-push` — the hook shell wrapper

New file. Bash script (POSIX `sh`-compatible since Andrei's environment runs Git for Windows + PowerShell, but git hooks always invoke `sh`). The wrapper detects whether any dispatch file is in the push range, and only then invokes the Python script.

```sh
#!/usr/bin/env sh
# .githooks/pre-push
# Versioned pre-push hook. Invoke via: git config core.hooksPath .githooks (one-time per clone).
# Reads stdin per git pre-push protocol: `<local_ref> <local_sha> <remote_ref> <remote_sha>` lines.

set -e

REMOTE_NAME="$1"
REMOTE_URL="$2"

while read -r local_ref local_sha remote_ref remote_sha; do
    # Skip branch deletes
    if [ "$local_sha" = "0000000000000000000000000000000000000000" ]; then
        continue
    fi

    # Determine diff range. If remote_sha is all-zeros (new branch), diff vs origin/main.
    if [ "$remote_sha" = "0000000000000000000000000000000000000000" ]; then
        DIFF_RANGE="origin/main..$local_sha"
    else
        DIFF_RANGE="$remote_sha..$local_sha"
    fi

    DISPATCH_FILES=$(git diff --name-only "$DIFF_RANGE" -- 'docs/**/*-dispatch.md' || true)

    if [ -z "$DISPATCH_FILES" ]; then
        # No dispatch in push range — skip review.
        continue
    fi

    BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)

    # Invoke the Python reviewer.
    echo "$DISPATCH_FILES" | python scripts/pre_push_review.py \
        --branch "$BRANCH_NAME" \
        --head-sha "$local_sha" \
        --remote-name "$REMOTE_NAME"
    REVIEW_EXIT=$?

    if [ "$REVIEW_EXIT" -ne 0 ]; then
        exit "$REVIEW_EXIT"
    fi
done

exit 0
```

**Hook protocol** (per `man githooks` / git docs): pre-push receives `<remote_name> <remote_url>` as args; reads stdin lines `<local_ref> <local_sha> <remote_ref> <remote_sha>`. The wrapper iterates stdin entries (one per ref pushed in a multi-ref push).

**Skip on branch delete**: when `local_sha` is the zero SHA, the user is deleting a remote branch — no dispatch review applies.

**Skip on no-dispatch-changed**: the most common path (regular code commits) exits in ≤ 100 ms with no API call.

### 3.3 `docs/audit-protocol/dispatch-review-rules.md` — versioned rule sheet

New file. Distilled from `feedback_dispatch_self_consistency` into a hook-readable artifact (the memory file is per-user; the repo file is the canonical hook input + onboarding doc for new engineers).

Structure (concrete shape, not just headers):

```markdown
# Dispatch Self-Consistency Rules — Hook Input

This file is consumed by `scripts/pre_push_review.py` as a system-prompt block.
It enumerates the institutional self-consistency rules a dispatch must satisfy
before reaching Codex Connector review.

Source of truth for rule evolution: orchestrator's per-user memory at
`<memory>/feedback_dispatch_self_consistency.md`. When a new sub-rule is
absorbed from a Codex catch, append it here in the same commit that updates
the memory file.

## Persona for the reviewer

You are a senior software engineer with decades of experience in institutional
financial systems (asset management, derivatives, MTM/P&L attribution,
multi-curve valuation). You review dispatch artifacts with the same rigor as
the Codex Connector — no bajulação, no scope creep, surface every fact mismatch
or self-defeating directive you find. The dispatch is reviewed against the
constitutional `docs/governance.md` (institutional supreme authority) and the
30+ self-consistency sub-rules below.

## Severity tiers

- **P1 (blocking)**: Tipo I fact mismatch (identifier doesn't exist), Tipo II
  self-defeat (§3 contradicts §10 / §6 contradicts §3 / §11 contradicts §3),
  governance violation (any §2.x rule of governance.md broken by the dispatch).
- **P2 (warning)**: sibling-bullet sweep miss, missing concrete-code field
  enumeration, NULL-safety oversight in comparator updates, decimal
  quantization boundary missing.
- **P3 (info)**: stylistic inconsistencies, redundant prescriptions, minor
  unverified claims that don't undermine the PR's purpose.

## The 30+ sub-rules

### Rule 1 — Identifier verification
Every concrete code prescription naming a function, class, attribute, enum
member, dict key, or schema field must reference an identifier that exists in
the codebase (Serena-verifiable). Inventing identifiers is P1.

[... continue for all 14 sub-rules, each with a one-paragraph statement +
example violation + example correct shape, derived from
`feedback_dispatch_self_consistency` ...]
```

The rule sheet is the single source the LLM reviewer consumes. **Every time `feedback_dispatch_self_consistency` gains a sub-rule, this file MUST be updated in the same commit** — institutional invariant. Phase A3 wave-5 closure is when the 9 PR-A3-1 sub-rules consolidate (per the memory entry); that consolidation lands in this file.

**Authoring scope for this PR**: the rule sheet ships at v1 with the 14 sub-rules currently captured in `feedback_dispatch_self_consistency` (status quo as of authoring date 2026-05-09). The 9 PR-A3-1-cycle additions (parallel-persistence-symmetry, comparator tracking, NULL-safety after NULL-able shape, pricing-domain awareness, decimal precision quantization, multi-leg multi-call patterns, DB-level uniqueness constraints, schema invariant verification, out-of-scope forbid trap, coverage validation) are ALL included — the implementer reads them out of the memory file (verbatim where possible) and writes them into the rule sheet during this PR.

### 3.4 Anthropic SDK pinning

Append to `backend/requirements.txt`:

```
anthropic==<VERIFY-LATEST>  # pin to the latest stable on PyPI at implementation time
```

**Do NOT inherit any version pin literal from this dispatch** — the implementer MUST run `pip index versions anthropic` (or browse PyPI) and pin the exact current GA release. Pin minor (`0.X.Y` → next `0.(X+1).0` is a real upgrade requiring re-verification of the SDK shapes prescribed in §3.1.3 and §3.1.4).

**Why pin in `backend/requirements.txt` and not a separate `scripts/requirements.txt`**: the backend already has `openai==2.34.0` and `httpx==0.28.1`; adding one more cloud SDK keeps dependency management single-rooted. Implementer environment installs both backend + scripts deps from the same lock file. If a future audit decides to split scripts deps into a separate file, do it then — not in this PR.

**Authentication**: `ANTHROPIC_API_KEY` in env. The hook fails fast with a clear error message if the key is missing. Document the env-var setup in §3.8 README update.

### 3.5 Diff-detection trigger

The hook's first action (per §3.2) is `git diff --name-only "$DIFF_RANGE" -- 'docs/**/*-dispatch.md'`. If empty, hook exits 0 in ~100 ms. This means:

- Regular code-only commits: no LLM call, no cost.
- Branches that touch dispatches but the *current push* doesn't include those files: no LLM call (the diff range is push-scoped).
- Pushes where multiple dispatches changed (e.g., two waves authored together): a single LLM call covering all changed dispatches (one `build_user_payload` concatenation, one `report_findings` invocation; see §3.1.5 multi-path batching).

**Glob shape**: `docs/**/*-dispatch.md` — matches `docs/audits/2026-05-09-phase-a3-pr-2-commodity-correctness-dispatch.md`, `docs/audits/2026-05-09-infra-pre-push-dispatch-review-hook-dispatch.md` (this PR), and any future dispatch following the trailing-`-dispatch.md` naming convention. **Verify**: every existing dispatch in `docs/audits/` matches this glob — grep before authoring.

**Multi-dispatch push behavior**: when N dispatches are in the push range, `build_user_payload` (§3.1.5) iterates and concatenates them into ONE Anthropic call (one `report_findings` invocation, one `ReviewReport`). This is intentional — a single call benefits from cache hit on the system blocks while keeping the per-push cost roughly flat. Token-budget check: each dispatch adds ~30-80 k tokens of user payload; 2-3 dispatches in one push is comfortable inside Sonnet 4.6's 200 k context. If a future push exceeds N=4 dispatches, consider splitting; for v1, single-call batching is the contract.

### 3.6 `scripts/install_git_hooks.py` — bootstrap

New file. One-time setup script:

```python
# scripts/install_git_hooks.py
import subprocess, sys, pathlib

def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    hooks_dir = repo_root / ".githooks"
    if not hooks_dir.is_dir():
        print(f"ERROR: {hooks_dir} not found", file=sys.stderr)
        return 1
    subprocess.check_call(["git", "config", "core.hooksPath", ".githooks"], cwd=repo_root)
    # On Unix-like systems chmod the hook executable; on Windows git treats hooks as executable regardless.
    pre_push = hooks_dir / "pre-push"
    if pre_push.is_file():
        try:
            pre_push.chmod(0o755)
        except (OSError, NotImplementedError):
            pass  # Windows: chmod is a no-op
    print("[install_git_hooks] core.hooksPath set to .githooks")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

**Idempotent**: re-running does no harm — `git config` overwrites, chmod is no-op on already-executable files. Document in §3.8 README that every fresh clone runs `python scripts/install_git_hooks.py` once.

### 3.7 `.gitignore` amendment

Append:

```
# pre-push dispatch review cache
.cache/dispatch_review/
```

**Verify before authoring**: read `.gitignore` and confirm `.cache/` is not already ignored at a broader scope. If `.cache/` is already ignored as a parent, the new entry is redundant — drop it.

### 3.8 README / AGENTS update

Append a short subsection to `README.md` (or create `docs/dev-setup.md` if README is minimal) titled **"Pre-push dispatch review hook"**:

```markdown
## Pre-push dispatch review hook

This repo runs an LLM-based first-sieve review on dispatch markdown files
before they reach the Codex Connector. To install (one-time per clone):

    python scripts/install_git_hooks.py

The hook fires on `git push` only when a `docs/**/*-dispatch.md` file is in
the push range. Set `ANTHROPIC_API_KEY` in your environment. To bypass the
hook for a single push (not recommended; see `docs/audit-protocol/`), use
`git push --no-verify`.

Cost: ~R$ 1.50–4.00 per push that triggers the review (Sonnet 4.6 with
prompt caching).
```

If `AGENTS.md` exists at repo root (Claude / Cursor / Codex agent context file), mirror this subsection there. **Verify**: grep for `AGENTS.md` at repo root before authoring; do not create it if absent (this PR is not the right vehicle to introduce a project-level agent context file).

---

## 4. Scope OUT — explicitly NOT in this PR

- **Replace Codex Connector review**: the hook is a first sieve. Codex remains final-line authority per `feedback_review_priority`. After hook passes, the orchestrator still waits for Codex top-level review before recommending merge.
- **Review code diffs (non-dispatch)**: this PR's hook only reviews `docs/**/*-dispatch.md`. Reviewing backend code changes is a separate concern (CI runs pytest; potential future hook for code review is out of scope here).
- **Run on `pre-commit`**: per the orchestrator analysis, pre-commit fires too often during drafting (latency mata UX). Pre-push only.
- **Local LLM (Qwen Coder 14B / similar)**: explicitly rejected. Reasoning gap on Tipo II / III catches kills the cost-benefit math. Document the rejection in §3 of the rule sheet for posterity.
- **Multi-model ensemble** (Haiku + Sonnet two-tier sieve): future iteration. v1 is single-call Sonnet 4.6.
- **Auto-fix mode** where the LLM proposes a patch: Codex doesn't auto-fix either; orchestrator stays in the loop. v1 only reports.
- **GitHub Action mirror** of the same review: out of scope. The hook is local-only. A CI action would re-bill the API on every push event server-side; the local hook is the cheaper integration point.
- **Calibration eval suite**: building a corpus of past Codex catches (PR #37 + #40 + #42) and measuring the LLM's recall/precision against that corpus is a follow-up dispatch. v1 ships untested-for-recall-rate; Andrei tunes the rule sheet by inspection over the next 2–3 dispatches.
- **PostHog / Sentry / structured logging integration**: cache-artifact JSON (§3.1.10) is the only persistence layer in v1.
- **Frontend regen**: this PR ships no schemas / no API surface change.

---

## 5. Operational rules (institutional infra discipline)

- **Reproducibility**: model identifier MUST be a fully-pinned dated form (`claude-sonnet-4-5-20250929`-shape), never `latest`-aliased. Rule-sheet content is versioned in git so any historical review run can be reproduced from `(git SHA, model ID, dispatch SHA)`.
- **No silent fallback**: if `ANTHROPIC_API_KEY` is missing OR the API call fails after retries, the hook MUST exit non-zero with a clear error message. Do NOT default to "review skipped" — that would re-create the silent-fallback institutional violation pattern that A1/A2/A3 audits have been hammering.
- **No API leakage**: cache artifacts (§3.1.10) MUST NOT include the API key, and the LLM's input/output stays on disk only as JSON (no remote sync, no Slack posting). The hook is a local tool.
- **Audit trail**: every triggered run leaves a JSON artifact. Orchestrator can review post-hoc when Codex catches something the hook missed (false negative) — feeds back into rule-sheet evolution.
- **Bypass discipline**: `git push --no-verify` is the only bypass. Document in §3.8 that bypassing without the orchestrator's deliberate decision violates `feedback_dispatch_self_consistency` "DO NOT use --no-verify to skip git hooks". Codex will catch the violation on the next dispatch anyway — bypass costs orchestrator credibility, not just CI seconds.

---

## 6. Acceptance criteria

- [ ] `scripts/pre_push_review.py` exists; running `python scripts/pre_push_review.py --help` prints usage; running it with no dispatch paths exits 0 with the "no dispatch files" message.
- [ ] `scripts/dispatch_review/` package exists with `__init__.py`, `client.py`, `prompt_builder.py`, `schema.py`, `rules.py`, `file_resolver.py`, `cache.py`.
- [ ] `.githooks/pre-push` exists; executable bit set on Unix; first line is `#!/usr/bin/env sh`.
- [ ] `scripts/install_git_hooks.py` exists; running it sets `git config core.hooksPath .githooks`; running it twice is a no-op (idempotent).
- [ ] `docs/audit-protocol/dispatch-review-rules.md` exists; enumerates 30+ sub-rules; every sub-rule has a one-paragraph statement + example violation + example correct shape.
- [ ] `backend/requirements.txt` has an `anthropic==<verified-latest>` line.
- [ ] `.gitignore` ignores `.cache/dispatch_review/` (or already covers `.cache/` at parent scope).
- [ ] README (or `docs/dev-setup.md`) documents the install + bypass procedure.
- [ ] Hook fires on `git push` when a `docs/**/*-dispatch.md` is in push range; skips silently otherwise. Verified by manual end-to-end test in §7.
- [ ] LLM call uses prompt caching (`cache_control: ephemeral` on the first 3 system blocks).
- [ ] LLM call uses tool-use forced output (`tool_choice={"type": "tool", "name": "report_findings"}`).
- [ ] Output validates against `ReviewReport` Pydantic schema; cache artifact JSON written to `.cache/dispatch_review/`.
- [ ] P1 findings exit 1 (block); P2/P3 exit 0 (print + continue).
- [ ] `git push --no-verify` bypasses the hook (built-in git behavior; no extra code needed).
- [ ] Hook adds < 200 ms latency on regular code-only pushes (no dispatch in range).
- [ ] No credential / API key written to any cache artifact, log, or repo file.

---

## 7. Test coverage required

This PR has limited unit-test surface (most of the value is in the LLM call, which can't be unit-tested cheaply). Cover what *is* mechanically testable:

- `tests/scripts/test_file_resolver.py`:
  - `test_resolve_cited_files_extracts_backend_paths` — fixture: temp markdown citing `backend/app/services/foo.py:42`; assert resolver returns `Path("backend/app/services/foo.py")` with the expected line excerpt.
  - `test_resolve_cited_files_skips_frontend_paths` — fixture: markdown citing `frontend-svelte/src/lib/api/schema.d.ts`; assert NOT included (per §3.1.6 out-of-scope rule).
  - `test_resolve_cited_files_caps_at_200_lines` — fixture: markdown citing a 500-line file; assert excerpt ≤ 200 lines.

- `tests/scripts/test_schema.py`:
  - `test_review_report_validates_well_formed_payload` — feed a hand-crafted JSON with 1 P1 + 2 P2 findings; assert `ReviewReport.model_validate(...)` succeeds.
  - `test_review_report_rejects_missing_required_field` — payload missing `summary`; assert `ValidationError` raised.
  - `test_report_findings_tool_schema_root_is_object` — load `REPORT_FINDINGS_TOOL["input_schema"]`; assert `["type"] == "object"`.

- `tests/scripts/test_install_git_hooks.py`:
  - `test_install_sets_hooks_path` — fixture: temp git repo; run `install_git_hooks.main()`; assert `git config core.hooksPath` returns `.githooks`.
  - `test_install_is_idempotent` — run twice; assert no error and config unchanged on second run.

- `tests/scripts/test_pre_push_review_skip_path.py`:
  - `test_main_exits_0_with_no_dispatch_paths` — invoke `pre_push_review.main()` with empty stdin; assert exit code 0 and "skipping" message printed.

- **Manual end-to-end** (NOT a pytest test; documented in §11 step Y): orchestrator runs a synthetic push of the current PR-A3-2 dispatch (Iteration 2) through the new hook. Verify that the hook detects the dispatch in range, calls the API, prints findings, and either blocks or warns based on P1 presence. The output is sanity-checked against the orchestrator's manual 8-section sweep result for the same dispatch.

**Test placement**: `backend/tests/scripts/` mirrors the source layout (`scripts/`). Update `backend/pytest.ini` (or pyproject.toml `[tool.pytest.ini_options]`) to include the new test path **only if** scripts/ tests don't already match the default discovery rootdir — verify before authoring.

**Test framework**: pytest, same as backend. **Do NOT introduce a separate test runner for the scripts package.**

**No HTTP mocking of the Anthropic API in v1**: the API call is the riskiest line of the script, but mocking it requires careful fixture maintenance against SDK shape evolution. Skip in v1 — let the manual e2e test exercise the live call once. Codex Connector review on this PR will catch any obvious wiring bug in the prompt builder.

---

## 8. Critical sequencing

This PR ships against **post-Wave-1 main** (`030a49bff`) or later. **The current `audit-a3/pr-2-dispatch` branch (PR #42) is in flight**; this PR (`infra/pre-push-dispatch-review`) is **independent of PR #42** — it can author and merge in parallel without affecting the A3 wave plan.

- **Branch base**: `origin/main` at `030a49bff`.
- **Migration chain**: untouched.
- **Downstream dependency**: future Phase A3 Wave 2/3/4/5 dispatches benefit from this hook — but they do NOT block on this PR. If this infra PR is delayed, Wave 3+ continue under the manual orchestration model.
- **Recommended merge order**: (a) PR #42 Iteration 2 lands (closes Wave 2). (b) This infra PR opens, gets Codex review, lands. (c) Wave 3 dispatch authors against the new hook in place.

The hook is **NOT** a prerequisite for Wave 3 — it is a productivity multiplier. If the orchestrator decides Wave 3 is more urgent, this PR can land after Wave 5 closure with no audit-cycle correctness impact.

---

## 9. PR shape

**Title:** `infra: pre-push dispatch review hook (Sonnet 4.6 first-sieve)`

**Body skeleton:**

```markdown
## Summary

Local pre-push hook that invokes Anthropic Claude Sonnet 4.6 against
`docs/**/*-dispatch.md` files in the push range, applying the 30+
institutional self-consistency sub-rules accumulated from Phase A1/A2/A3
Codex review cycles. P1 findings block the push; P2/P3 print and continue.

Goal: reduce Codex Connector round count per dispatch from 5–13 → 1–4
by catching mechanically-detectable Tipo I / II / III violations before
the dispatch reaches Codex.

## Files changed

- `scripts/pre_push_review.py` — CLI entrypoint
- `scripts/dispatch_review/` — package (client, prompt_builder, schema, rules, file_resolver, cache)
- `scripts/install_git_hooks.py` — bootstrap setting `core.hooksPath`
- `.githooks/pre-push` — versioned hook wrapper
- `docs/audit-protocol/dispatch-review-rules.md` — versioned rule sheet (30+ sub-rules)
- `backend/requirements.txt` — adds `anthropic==<verified-latest>`
- `.gitignore` — ignores `.cache/dispatch_review/`
- README / dev-setup doc — install + bypass instructions
- Tests: `backend/tests/scripts/test_*` (5 mechanical tests)

## Acceptance evidence

- [ ] All criteria from dispatch §6 met
- [ ] Manual end-to-end sanity check on PR-A3-2 dispatch (Iteration 2) — see §7
- [ ] Hook adds < 200 ms latency on code-only pushes (timed)
- [ ] No credential / key written to any artifact

## Constitutional impact

None directly — this PR ships tooling that complements the existing audit
review pipeline. It does NOT modify any production code path; the FastAPI
backend is untouched except for the new `anthropic` dependency.

## Out of scope

See dispatch §4 — Codex replacement, code diff review, pre-commit timing,
local LLM, multi-model ensemble, auto-fix, GitHub Action mirror, calibration
eval suite, PostHog/Sentry, frontend regen.

## Cost projection

~R$ 1.50–4.00 per push that triggers the review (Sonnet 4.6 + prompt cache).
Expected savings: 8–10 fewer Codex rounds across the remaining A3/A4/A5/A6
dispatches × ~15 min orchestration cost per round = ~20+ orchestrator-hours
recovered.
```

---

## 10. Constraints — what NOT to do

- DO NOT call the Anthropic API on every commit (pre-commit hook). Only pre-push, only when a dispatch markdown changed in the push range.
- DO NOT use `claude-sonnet-latest` or any aliased model identifier. Pin the dated form for reproducibility.
- DO NOT bundle a copy of the orchestrator's per-user memory feedback files into the repo. The rule sheet at `docs/audit-protocol/dispatch-review-rules.md` is the canonical in-repo artifact; memory files remain per-user.
- DO NOT silently skip the hook on API error. Fail with a clear non-zero exit and a documented error message.
- DO NOT log or persist the API key. The cache artifact contains only the `ReviewReport` JSON.
- DO NOT include `frontend-svelte/**` paths in `file_resolver.resolve_cited_files`. Frontend audit is Phase A6; surfacing frontend code in the prompt blows the token budget without benefit at this audit phase.
- DO NOT introduce a new top-level Python package or virtualenv layout. The scripts package lives next to backend; `backend/requirements.txt` is the dependency root.
- DO NOT add npm dependencies. `package.json` root stays minimal.
- DO NOT use `--no-verify` during this PR's own implementation cycle. Codex will review this PR; the dispatch reviewer doesn't apply to itself yet (this PR introduces it).
- DO NOT ship the rule sheet missing any of the 30+ sub-rules. The institutional invariant — "memory and rule sheet move together" — kicks in starting with this commit.
- DO NOT auto-merge — wait for Codex review.

---

## 11. Workflow

1. `git fetch origin && git worktree add D:/Projetos/Hedge-Control-New-infra-hook origin/main && cd D:/Projetos/Hedge-Control-New-infra-hook && git checkout -b infra/pre-push-dispatch-review`.
2. Configure `.claude/settings.local.json` per the worktree pattern (`defaultMode: bypassPermissions`, allow `git`/`gh`/`pytest`/`python`/`pip`, deny `--force` raw, `--auto`, `--no-verify`, push to `main`).
3. Read the constitutional + memory references in §2.
4. Verify Anthropic SDK current stable version: `pip index versions anthropic` or browse PyPI; pin in `backend/requirements.txt` as `anthropic==<verified>`. Confirm the model identifier in `_MODEL` (`scripts/dispatch_review/client.py`) is current — `claude-sonnet-4-6` was the production Sonnet 4.6 alias at authoring time; verify against the Anthropic model docs / SDK release notes immediately before sealing. Never use `latest` aliases.
5. Create `scripts/dispatch_review/` package skeleton (6 modules). Stub each module with module docstring + import skeleton.
6. Implement `scripts/dispatch_review/schema.py` first (Pydantic models + tool schema). Test it.
7. Implement `scripts/dispatch_review/rules.py` (file loader for `docs/audit-protocol/dispatch-review-rules.md`).
8. Implement `scripts/dispatch_review/file_resolver.py`. Test it (3 unit tests).
9. Author `docs/audit-protocol/dispatch-review-rules.md` v1: copy the orchestrator's `feedback_dispatch_self_consistency` memory content (the 30+ sub-rules), expand each sub-rule into the structure prescribed in §3.3 (statement + example violation + example correct shape).
10. Implement `scripts/dispatch_review/prompt_builder.py` — cached system blocks per §3.1.4; user payload per §3.1.5. Verify cache_control schema against the SDK pinned version.
11. Implement `scripts/dispatch_review/client.py` — Anthropic API call with retry/backoff; tool-use forcing.
12. Implement `scripts/dispatch_review/cache.py` — JSON write to `.cache/dispatch_review/{slug}-{sha}.json`.
13. Implement `scripts/pre_push_review.py` entrypoint — CLI parsing, dispatch path enumeration, orchestration of the above modules, exit code logic.
14. Author `.githooks/pre-push` per §3.2.
15. Author `scripts/install_git_hooks.py` per §3.6.
16. Update `.gitignore` per §3.7.
17. Update `backend/requirements.txt` per §3.4. **Run `pip install -r backend/requirements.txt`** in the implementer venv to confirm pin resolves.
18. Update README / `docs/dev-setup.md` per §3.8.
19. Run unit tests: `pytest backend/tests/scripts/ -v`.
20. **Manual end-to-end test**: from the worktree, run `python scripts/install_git_hooks.py`. Confirm `git config core.hooksPath` shows `.githooks`. Then synthesize a fake push by piping the current PR-A3-2 dispatch path into `python scripts/pre_push_review.py`. Inspect the output JSON; sanity-check against the orchestrator's manual review of the same dispatch.
21. Full backend pytest: `pytest backend/tests/ -v` — green except known failures (3 pre-existing `test_ws.py` Python 3.14 failures).
22. `git push -u origin infra/pre-push-dispatch-review && gh pr create --base main --title "<§9 title>" --body-file <body>` — DO NOT use `--draft`.
23. **STOP. Wait for Codex review.** Address each catch as a new commit. Expected catch count: 4–8 (broader surface than a typical wave dispatch — touches Python tooling, shell, docs).
24. Report back with PR URL, final SHA, Codex review state, files-touched grouping, test counts, and the manual e2e log.

---

## 12. Final report shape

When complete, report to orchestrator:
- Branch + PR URL + final SHA.
- Files touched (grouped: scripts/ / .githooks/ / docs/audit-protocol/ / requirements / tests).
- Test pass/fail counts vs main baseline.
- Codex review status + catches absorbed (per round).
- Manual e2e log: `pre_push_review.py` output JSON for PR-A3-2 dispatch (Iteration 2), with orchestrator's annotation comparing the LLM's findings against the manual 8-section sweep result.
- Anthropic SDK pinned version + dated model identifier used.
- Cost observed for the manual e2e run (visible in Anthropic Console usage page).

Keep report under 700 words.

Boa caça.
