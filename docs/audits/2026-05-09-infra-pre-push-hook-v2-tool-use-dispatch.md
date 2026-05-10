# Infra — Pre-push Hook v2: Tool-Use Enhancement — Dispatch

**Track:** Infra (non-audit — extends `pre-push hook v1` with custom tool-use to eliminate the 3 FP classes documented in `reference_pre_push_hook_calibration`)
**Authoring date:** 2026-05-09
**Branch name:** `infra/pre-push-hook-v2-tool-use`
**Base:** `main` (currently `bf021b837`, post-PR-#42 merge)
**Findings covered:** none (this dispatch ships *tooling enhancement*; it does NOT touch any audit finding)
**Depends on:** hook v1 (already in main since `57dd57d26`)

---

## 0. Motivation

Hook v1 (landed in main 2026-05-09 across `57dd57d26..bf021b837`) reduced PR #42's Codex round count from a historic peak of ~18 to **2 Codex rounds** (~89% reduction). 8 real P1 catches were absorbed via 8 push iterations before reaching Codex, who then absorbed a further 4 catches the hook missed (HTTPException + resolve_symbol imports, LME_ALU canonical symbol, `/scenario/what-if/run` route path, OpenAPI runtime-vs-schema nullability scope).

Hook v1 calibration evidence (`reference_pre_push_hook_calibration` memory, 2026-05-09):

- ~70% catch rate on mechanically-detectable institutional violations Codex would also flag.
- ~25% false-positive rate on emitted P1 (3 of ~12). FP root causes:
  - **utils/ visibility gap**: Sonnet inferred `PriceQuote` was at `app.services.price_lookup_service` because cited files imported it from there — actually re-exported; canonical home is `app.utils.price_reference`. Sonnet had no visibility into `utils/` modules unless the dispatch backticks the path explicitly.
  - **File-resolver 200-line cap**: `file_resolver.resolve_cited_files` truncates each cited file at 200 lines (`scripts/dispatch_review/file_resolver.py` `_LINE_CAP = 200`). Line numbers beyond ~200 (e.g. `:467, :480, :545, :590` for `_mtm_for_*` call sites in `scenario_whatif_service.py`) cannot be Tipo-I-verified against the inlined excerpt — Sonnet flagged them as unverifiable when they were actually correct.
  - **Identifier mapping inference**: Sonnet's claim `"ALUMINUM"` was not in `COMMODITY_SYMBOL_MAP` was wrong — the map at `price_lookup_service.py:21-37` has both short codes (`LME_AL`) AND human aliases (`ALUMINUM`, `ALUMINIUM`). Sonnet inferred from a partial cited test file showing only short-code keys.

All three FP classes share a structural cause: **the model can only see what `file_resolver.resolve_cited_files` pre-inlined**. It cannot dynamically read additional files, follow imports, search for symbol definitions, or grep for identifiers. When the truth lives outside the pre-inlined excerpts, Sonnet either invents an inference (FPs) or flags a verification gap (false P1).

Two alternative fixes were considered:

- **Aggressive pre-fetch** — `file_resolver` follows imports recursively and inlines all dependent files. Rejected: token budget grows unbounded, cache TTL behavior degrades, and the model still cannot dynamically search beyond what was inlined.
- **MCP connector** — pass `mcp_servers` parameter to Anthropic API, expose Serena MCP server. Rejected at this surface: Serena ships in stdio mode (subprocess), not HTTP/SSE, so adapting requires either a port shim or a parallel HTTP-mode Serena instance — non-trivial setup with surface area beyond v2 scope.

This dispatch ships **custom tool-use** via the native Anthropic Messages API: define a small set of read-only tools (`read_file`, `find_symbol`, `grep_pattern`), let Sonnet call them iteratively during review, terminate the loop when Sonnet calls the existing `report_findings` tool. This is the canonical Anthropic-supported pattern (`anthropic==0.100.0`, `from anthropic.types import ToolUseBlock, ToolResultBlockParam`), keeps the implementation in-tree (no external services), and surgically resolves the 3 FP classes:

- `read_file(path)` lets Sonnet inspect any file in the repo (within an allowlist root) — resolves utils/ visibility gap and identifier mapping inference.
- `find_symbol(name)` lets Sonnet grep for a class/function/dict definition — resolves identifier mapping inference at scale.
- `grep_pattern(pattern, path_glob)` lets Sonnet search for arbitrary regex patterns — resolves line-number verification (Sonnet can grep for the call-site code, returning the actual line + matching context).

After this dispatch ships, the hook executes a multi-turn conversation: each turn either (a) Sonnet emits one or more `tool_use` blocks → tool handlers execute and return `tool_result` blocks → next turn, OR (b) Sonnet emits the final `report_findings` tool_use → loop ends. A cap of N=12 iterations and ~150k cumulative tokens guards against runaway loops.

The expected gain: FP rate drops from ~25% → <5% (Sonnet verifies before asserting). Catch rate may also rise slightly because Sonnet can now investigate paths the file_resolver didn't pre-inline. Cost increases ~3-4× per push (multi-turn = more API roundtrips + larger output token budget for tool_use blocks), landing around R$ 1.50-4.00/push triggered (vs v1's R$ 0.30-0.80). Worth the trade given hook is the difference between 2 and 18 Codex rounds.

---

## 1. Mission

Extend hook v1 to support **custom tool-use** so Sonnet can dynamically read files, search for symbols, and grep for patterns during dispatch review — eliminating the 3 FP classes that limited v1's precision.

After this PR ships:

- `scripts/dispatch_review/tool_handlers.py` exposes 3 read-only tool handlers: `read_file`, `find_symbol`, `grep_pattern`.
- `scripts/dispatch_review/tools.py` defines the corresponding Anthropic tool schemas + a dispatch table mapping tool name → handler.
- `scripts/dispatch_review/client.py` runs a **multi-turn loop**: messages.create → if `stop_reason == "tool_use"` and at least one tool_use block is NOT `report_findings`, execute the tool(s), append `tool_result` blocks to messages, repeat. Loop terminates when Sonnet emits the `report_findings` tool_use.
- Hard caps: max iterations = 12, max cumulative output tokens = 60000. Exceeding either raises with a clear error (no silent fallback per §5).
- All tools are **read-only** and **scoped to the repo root** (no filesystem writes, no subprocess execution outside whitelisted operations, no path traversal beyond repo root).
- Cache artifact (`.cache/dispatch_review/<branch>-<sha>.json`) gains a new `tool_calls` array logging each `(name, input, result_summary)` for post-hoc audit + calibration data collection.
- Hook v1's `report_findings` schema (Pydantic `ReviewReport`) is unchanged — v2 only adds investigation tools, not output schema changes.

**Persona reinforcement** for the LLM reviewer: same senior-institutional-engineer persona as hook v1, but with the explicit instruction that **identifier verification via tool calls is mandatory before raising P1 Tipo-I findings**. Inferring from cited files is acceptable for hypothesis generation; before emitting a P1, the model MUST verify via `read_file` or `find_symbol`.

---

## 2. Reference docs (read before coding)

- **`docs/governance.md`** — full file (217 lines). Already loaded as cached system block in v1; no change to that loading.
- **`docs/audit-protocol/dispatch-review-rules.md`** — 30 sub-rules. Already loaded; v2 prepends a small instruction section about tool-use discipline.
- **`<memory>/reference_pre_push_hook_calibration.md`** — empirical data driving v2's design priorities.
- **`<memory>/project_pre_push_hook_v1_landed.md`** — v1 architecture history.
- **`docs/audits/2026-05-09-infra-pre-push-dispatch-review-hook-dispatch.md`** — v1 dispatch (already merged); reference for sectioning conventions.
- **`scripts/pre_push_review.py`** — CLI entry; gains no signature changes but the underlying call_review acquires a multi-turn loop.
- **`scripts/dispatch_review/client.py`** — current single-turn implementation (`call_review` function). The 30-line `for attempt in range(_MAX_RETRIES)` retry loop wraps `client.messages.create(...)`; this PR wraps that retry loop in an outer multi-turn loop.
- **`scripts/dispatch_review/prompt_builder.py`** — current `build_cached_system_blocks` returns 4 system blocks; v2 augments block 4 (`_REVIEW_PROTOCOL_PROSE`) with tool-use instructions.
- **`scripts/dispatch_review/file_resolver.py`** — `_LINE_CAP = 200`. v2 keeps this cap for pre-inlining (token budget protection); the new `read_file` tool can read up to 500 lines per call, with explicit start/end_line params.
- **`scripts/dispatch_review/schema.py`** — `ReviewReport` and `build_report_findings_tool` UNCHANGED. New `build_review_tools` function added returning the 3 investigation tools + the existing `report_findings` tool, all in a single list passed to `client.messages.create`.
- **`backend/tests/scripts/`** — existing test layout. v2 adds `test_tool_handlers.py`.
- **Anthropic SDK tool-use API docs** — `anthropic==0.100.0` exports `ToolUseBlock`, `ToolResultBlockParam`. The Messages API documents `tools=[...]` parameter with `tool_use` `stop_reason` and message-history pattern (assistant `tool_use` block + user `tool_result` block). VERIFY-LATEST: confirm the typed-import paths against the pinned SDK version before authoring (current paths are `from anthropic.types import ToolUseBlock` and `from anthropic.types import ToolResultBlockParam`; both resolved successfully under SDK 0.100.0 at authoring time).

---

## 3. Scope IN — what this PR ships

> **Verification disclaimer:** every prescribed identifier and module path was authored against `bf021b837` (post-PR-#42 merge). VERIFY-LATEST tags mark items where SDK or model behavior may have evolved.

### 3.1 New module — `scripts/dispatch_review/tool_handlers.py`

New file. Pure Python functions executing each tool's logic. Handlers receive a `dict` (the tool input) and a `Path` (the repo root) and return a `dict` (the structured tool result). All handlers are **read-only** and **scoped to `repo_root`** (path traversal outside repo root is rejected; file system writes are not implemented).

```python
"""Read-only tool handlers for the pre-push hook v2 multi-turn review."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

_MAX_LINES_PER_READ = 500
_MAX_GREP_RESULTS = 80
_MAX_FIND_SYMBOL_BYTES = 8000


def _resolve_within_repo(repo_root: Path, raw_path: str) -> Path:
    """Resolve a path under repo_root; reject any traversal outside."""
    candidate = (repo_root / raw_path).resolve()
    repo_root_resolved = repo_root.resolve()
    if not str(candidate).startswith(str(repo_root_resolved)):
        raise ValueError(f"path {raw_path!r} resolves outside repo root")
    return candidate


def handle_read_file(payload: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    path_str = payload["path"]
    start_line = int(payload.get("start_line") or 1)
    end_line = payload.get("end_line")
    try:
        target = _resolve_within_repo(repo_root, path_str)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not target.is_file():
        return {"ok": False, "error": f"not a file: {path_str}"}
    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    end_clamped = int(end_line) if end_line is not None else min(start_line + _MAX_LINES_PER_READ - 1, len(lines))
    if end_clamped - start_line + 1 > _MAX_LINES_PER_READ:
        end_clamped = start_line + _MAX_LINES_PER_READ - 1
    excerpt = "\n".join(lines[start_line - 1 : end_clamped])
    return {
        "ok": True,
        "path": path_str,
        "start_line": start_line,
        "end_line": end_clamped,
        "total_lines": len(lines),
        "excerpt": excerpt,
    }


def handle_find_symbol(payload: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    """Locate where a Python class/function/constant is DEFINED.

    Implementation: regex grep across `backend/app/` and `backend/tests/`
    for `^(class|def)\\s+<name>\\b` or `^<NAME>\\s*[:=]`. Returns first
    match's file:line + a 30-line excerpt around the definition.
    """
    name = payload["name"]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return {"ok": False, "error": f"invalid Python identifier: {name!r}"}
    pattern = (
        rf"^(class\s+{re.escape(name)}\b|def\s+{re.escape(name)}\b|{re.escape(name)}\s*[:=])"
    )
    return _grep_with_context(repo_root, pattern, ["backend/app", "backend/tests", "scripts"], context_lines=15, byte_cap=_MAX_FIND_SYMBOL_BYTES)


def handle_grep_pattern(payload: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    pattern = payload["pattern"]
    search_path = payload.get("search_path") or "backend/app"
    return _grep_with_context(repo_root, pattern, [search_path], context_lines=int(payload.get("context_lines") or 0), byte_cap=_MAX_GREP_RESULTS * 200)


def _grep_with_context(repo_root: Path, pattern: str, search_paths: list[str], *, context_lines: int, byte_cap: int) -> dict[str, Any]:
    # Use Python's pathlib + re instead of subprocess.run('rg') for portability
    # and to avoid pulling in ripgrep as an implicit dependency. For 100k+
    # files this would be slow; for our repo (~few hundred Python files)
    # it is acceptable.
    matches: list[dict[str, Any]] = []
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return {"ok": False, "error": f"invalid regex: {exc}"}
    cumulative_bytes = 0
    for sp in search_paths:
        root = (repo_root / sp).resolve()
        if not root.exists():
            continue
        files = root.rglob("*.py") if root.is_dir() else [root]
        for f in files:
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for idx, line in enumerate(lines, start=1):
                if compiled.search(line):
                    excerpt_start = max(1, idx - context_lines)
                    excerpt_end = min(len(lines), idx + context_lines)
                    excerpt = "\n".join(f"{n}: {lines[n - 1]}" for n in range(excerpt_start, excerpt_end + 1))
                    rel = f.relative_to(repo_root).as_posix()
                    entry = {"file": rel, "line": idx, "excerpt": excerpt}
                    cumulative_bytes += len(excerpt) + len(rel) + 16
                    if cumulative_bytes > byte_cap:
                        return {"ok": True, "matches": matches, "truncated": True}
                    matches.append(entry)
                    if len(matches) >= _MAX_GREP_RESULTS:
                        return {"ok": True, "matches": matches, "truncated": True}
    return {"ok": True, "matches": matches, "truncated": False}


HANDLERS = {
    "read_file": handle_read_file,
    "find_symbol": handle_find_symbol,
    "grep_pattern": handle_grep_pattern,
}
```

**Why pure Python regex instead of `subprocess.run("rg")`**: ripgrep is not in the project's dependency closure (verify via `which rg` — not installed in CI runners). Pulling it in would add an installation step. The repo size (~few hundred Python files in `backend/app/`) is small enough that pure-Python regex completes in under 200 ms per call. If a future cycle measures grep latency dominating multi-turn loop time, swap the `_grep_with_context` body to subprocess+ripgrep.

**Why no `subprocess.run('serena')` for `find_symbol`**: Serena MCP runs in stdio mode under Claude Code, not as a CLI invocable from a hook. Bridging would require the MCP-connector option (rejected per §0). The regex-based `find_symbol` is a deliberate downgrade from Serena's LSP-grade symbol resolution; it works for the institutional dispatch authoring patterns (class definitions, function definitions, constant assignments at module level) but does not handle method overrides or class-internal lookups. **In-scope identifiers cited in dispatches are nearly all module-level**, making this acceptable for v2.

### 3.2 New module — `scripts/dispatch_review/tools.py`

New file. Anthropic tool schemas + dispatch table.

```python
"""Anthropic tool definitions for the multi-turn dispatch review (hook v2)."""

from __future__ import annotations

from typing import Any

READ_FILE_TOOL: dict[str, Any] = {
    "name": "read_file",
    "description": (
        "Read a file in the repo (read-only). Use this to verify identifier "
        "definitions, schema field names, line numbers, or any prescription "
        "in concrete code blocks against the actual codebase. Returns up to "
        "500 lines per call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Path relative to repo root. Examples: "
                    "'backend/app/services/price_lookup_service.py', "
                    "'backend/app/schemas/scenario.py'."
                ),
            },
            "start_line": {"type": "integer", "minimum": 1, "description": "1-indexed start line. Default 1."},
            "end_line": {"type": "integer", "minimum": 1, "description": "1-indexed end line (inclusive). Default = start_line + 499."},
        },
        "required": ["path"],
    },
}

FIND_SYMBOL_TOOL: dict[str, Any] = {
    "name": "find_symbol",
    "description": (
        "Find where a Python class, function, or module-level constant is "
        "defined. Searches backend/app/, backend/tests/, scripts/. Returns "
        "the first match's file:line plus a 30-line excerpt around the "
        "definition. Use this to resolve identifier-location questions "
        "(e.g., 'is PriceQuote in utils/ or services/?')."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The Python identifier (class, function, or constant name).",
            },
        },
        "required": ["name"],
    },
}

GREP_PATTERN_TOOL: dict[str, Any] = {
    "name": "grep_pattern",
    "description": (
        "Search for a Python regex pattern within a directory or file. "
        "Returns up to 80 matches with file:line and an N-line context "
        "excerpt. Use this to verify line numbers in dispatch prescriptions, "
        "find call sites, or audit existing test fixtures for the "
        "pre-fix-cleanup directive."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python re.compile-compatible regex."},
            "search_path": {
                "type": "string",
                "description": (
                    "Directory or exact file path under repo root. NO glob "
                    "syntax (no `**`, `*`, `?`); pass a literal path. The "
                    "handler walks the directory recursively for *.py files. "
                    "Default 'backend/app'."
                ),
            },
            "context_lines": {"type": "integer", "minimum": 0, "maximum": 20, "description": "Lines of surrounding context. Default 0."},
        },
        "required": ["pattern"],
    },
}


def build_review_tools() -> list[dict[str, Any]]:
    """Return the 3 investigation tools + the report_findings tool.

    The report_findings tool stays imported from `schema.build_report_findings_tool`
    to keep the schema module the single source of truth for output shape.
    """
    from .schema import build_report_findings_tool
    return [READ_FILE_TOOL, FIND_SYMBOL_TOOL, GREP_PATTERN_TOOL, build_report_findings_tool()]
```

### 3.3 Multi-turn loop — `scripts/dispatch_review/client.py`

Update `call_review` to run the multi-turn loop. The single-turn `client.messages.create(...)` invocation becomes the body of a `for iteration in range(MAX_ITERATIONS)` loop; each iteration interprets the response.

**Current** at `scripts/dispatch_review/client.py:23-71` (single-turn body inside retry loop):

```python
def call_review(
    *,
    model: str,
    cached_system_blocks: list[dict[str, Any]],
    user_payload: str,
    max_tokens: int = 8192,
) -> ReviewReport:
    ...
    response = client.messages.create(
        model=model, max_tokens=max_tokens, system=cached_system_blocks,
        tools=[tool], tool_choice={"type": "tool", "name": "report_findings"},
        messages=[{"role": "user", "content": user_payload}],
    )
    ...
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "report_findings":
            return ReviewReport.model_validate(_coerce_list_fields(dict(block.input)))
```

**Replacement** (truncated for the dispatch — full implementation in §11 step list):

```python
_MAX_ITERATIONS = 12
_MAX_CUMULATIVE_OUTPUT_TOKENS = 60_000
_PER_TURN_MAX_TOKENS = 8_192


def _create_with_retry(
    client: Anthropic,
    *,
    model: str,
    max_tokens: int,
    cached_system_blocks: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
):
    """Network-retry wrapper around messages.create — preserves v1's
    3-attempt exponential backoff on RateLimitError / APIConnectionError /
    APIStatusError; AuthenticationError fails fast (no retry).
    """
    ...  # extracted verbatim from v1's inner retry loop


def call_review(
    *,
    model: str,
    cached_system_blocks: list[dict[str, Any]],
    user_payload: str,
    repo_root: Path,
) -> tuple[ReviewReport, list[dict[str, Any]]]:
    """Multi-turn review. Returns (report, tool_call_log)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set...")

    client = Anthropic()
    tools = build_review_tools()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_payload}]
    tool_call_log: list[dict[str, Any]] = []
    cumulative_output_tokens = 0

    for iteration in range(_MAX_ITERATIONS):
        response = _create_with_retry(
            client, model=model, max_tokens=_PER_TURN_MAX_TOKENS,
            cached_system_blocks=cached_system_blocks, tools=tools, messages=messages,
        )
        cumulative_output_tokens += getattr(response.usage, "output_tokens", 0)
        if cumulative_output_tokens > _MAX_CUMULATIVE_OUTPUT_TOKENS:
            raise RuntimeError(
                f"cumulative output exceeded {_MAX_CUMULATIVE_OUTPUT_TOKENS} tokens; "
                "loop terminated to prevent runaway cost"
            )

        # Did the model emit a final report?
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "report_findings":
                return (
                    ReviewReport.model_validate(_coerce_list_fields(dict(block.input))),
                    tool_call_log,
                )

        # Otherwise, execute any investigation tool_use blocks.
        tool_results: list[dict[str, Any]] = []
        executed_any = False
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            executed_any = True
            handler = HANDLERS.get(block.name)
            if handler is None:
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps({"ok": False, "error": f"unknown tool: {block.name}"})})
                continue
            try:
                result = handler(dict(block.input), repo_root=repo_root)
            except Exception as exc:  # noqa: BLE001  -- we MUST surface tool errors to the model, not the hook
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            tool_call_log.append({"iteration": iteration, "name": block.name, "input": dict(block.input), "result_summary": _summarize_for_log(result)})
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)})

        if not executed_any:
            raise RuntimeError(
                f"iteration {iteration}: model emitted no tool_use block and no report_findings; "
                f"stop_reason={response.stop_reason!r}"
            )

        # Append assistant turn + tool results, continue.
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"review did not converge after {_MAX_ITERATIONS} iterations")
```

**Critical design points**:

- **No `tool_choice` forcing** in the multi-turn case. v1 forced `tool_choice={"type": "tool", "name": "report_findings"}` to guarantee structured output on a single turn. v2 lets the model choose between investigation tools and the final `report_findings` — forcing would prevent the model from calling `read_file`. The model is steered to call `report_findings` last via the system prompt instruction (§3.5).
- **Retry/backoff** stays on the inner `_create_with_retry`. Network errors retry per turn; `MAX_ITERATIONS` caps the outer loop.
- **`tool_results` content is JSON-serialized**. Anthropic accepts both string content and structured content for `tool_result`; JSON-string is the simplest portable shape.
- **Response content history** is preserved (`messages.append({"role": "assistant", "content": response.content})`) so the model can reason across turns.
- **`tool_call_log`** is a flat list of `(iteration, name, input, result_summary)` dicts written to the cache artifact (§3.6).

### 3.4 prompt_builder — instruct Sonnet about tools

Update `_REVIEW_PROTOCOL_PROSE` in `scripts/dispatch_review/prompt_builder.py` to add a "Tool-use discipline" section. The cached system blocks 1-3 (persona + governance + rule sheet) are unchanged; only block 4 grows.

New §"Tool-use discipline" appended to existing `_REVIEW_PROTOCOL_PROSE`:

```
# Tool-use discipline (v2)

You have 3 read-only investigation tools (`read_file`, `find_symbol`,
`grep_pattern`) plus the `report_findings` tool.

When you have a hypothesis that a dispatch identifier (function name,
schema field, dict key, file path, line number) is wrong, **VERIFY before
flagging P1**. Use:
- `find_symbol(name="X")` to locate where X is defined.
- `read_file(path="...", start_line=, end_line=)` to inspect specific
  ranges.
- `grep_pattern(pattern="...", path_glob="...")` to find call sites,
  identifier mappings, or to verify line numbers in the cited code.

Discipline rules:
- Inferring from cited file excerpts is acceptable for HYPOTHESIS
  GENERATION; before asserting P1 Tipo-I (identifier doesn't exist),
  you MUST have a tool result confirming the identifier is missing.
- A tool may return `{"ok": false, "error": ...}` — do NOT interpret
  that as proof. It indicates the tool failed (bad input, not found at
  the prescribed path); investigate further with a different tool call.
- Be efficient — typical reviews need 3-8 tool calls. The hook caps at
  12 iterations. Plan investigations: read the most authoritative source
  first (e.g., for a class location, `find_symbol` once is better than
  3 sequential `grep_pattern` searches).
- When you are confident the review is complete, call `report_findings`
  with your full ReviewReport. Do NOT call other tools after
  `report_findings` — that call ends the loop.

Severity tier reminder (unchanged from v1):
- P1 (blocking): Tipo I fact mismatch, Tipo II self-defeat, governance
  §2.x violation. P1 emission requires tool-verified evidence.
- P2 (warning): sibling-bullet sweep miss, NULL-safety oversight,
  decimal quantization, etc.
- P3 (info): stylistic, redundant, minor unverified.
```

The `_REVIEW_PROTOCOL_PROSE` block stays uncached (4th system block; small, dispatch-specific). Caching it would not save much because it changes whenever the rule sheet changes, and the rule sheet is the cached block right before it.

### 3.5 schema.py — minimal addition

`ReviewReport` and `build_report_findings_tool` are UNCHANGED. The only addition is exporting (or importing inside `tools.py`) the existing `build_report_findings_tool` so `build_review_tools` can compose it. No schema field changes.

### 3.6 Cache artifact extension

Update `scripts/dispatch_review/cache.py::write_cache_artifact` to accept the optional `tool_call_log` parameter and write it under a `tool_calls` key in the JSON. Backward-compatible: artifacts without `tool_calls` (v1 outputs) still parse.

```python
def write_cache_artifact(
    report: ReviewReport, *, repo_root: Path, branch: str, head_sha: str,
    tool_calls: list[dict[str, Any]] | None = None,
) -> Path:
    ...
    payload = report.model_dump(mode="json")
    if tool_calls is not None:
        payload["tool_calls"] = tool_calls
    ...
```

Why `tool_call_log`: post-hoc calibration data. After the next 5-10 cycles of v2 in production, the orchestrator will have N artifacts each containing `tool_calls`. Quick analysis of "which tool got called most often, on which dispatches, with which results" tells us whether the tools are well-designed. This is the v2 calibration evidence loop, mirroring how v1 calibration data drove v2's design priorities.

### 3.7 file_resolver — UNCHANGED

`scripts/dispatch_review/file_resolver.py` stays at the 200-line cap for pre-inlining. Pre-inlining gives Sonnet a fast first pass; the new `read_file` tool covers gaps. **Do NOT raise `_LINE_CAP`** beyond 200 — that re-inflates token budget on every call without the dynamic targeting that tool-use provides.

### 3.8 pre_push_review.py — minor update

Update `scripts/pre_push_review.py::main` to pass `repo_root` into `call_review` and to receive `(report, tool_call_log)` instead of just `report`. Pass `tool_call_log` to `write_cache_artifact`. The CLI surface (args, exit codes) is unchanged.

**Skip-guard placement is invariant**: the no-dispatch-paths early-exit (`if not dispatch_paths: print(...); return 0`) MUST stay ABOVE the `call_review` invocation in `main`. Moving it inside the multi-turn loop would break `backend/tests/scripts/test_pre_push_review_skip.py::test_main_exits_0_with_no_dispatch_paths`. The existing skip test is declared UNCHANGED in §7 — that contract is safe ONLY if the early-exit guard placement is preserved.

### 3.9 Tests — `backend/tests/scripts/test_tool_handlers.py`

New test file. 8 mechanical tests covering the 3 handlers + path-traversal protection + truncation behavior. The multi-turn loop in `client.py` is NOT unit-tested in v2 (would require fixture-mocking the Anthropic API which is fragile). The end-to-end smoke test runs the actual hook against the merged Wave-2 dispatch (`docs/audits/2026-05-09-phase-a3-pr-2-commodity-correctness-dispatch.md`) and inspects the resulting JSON artifact.

Test enumeration (mechanical):
- `test_handle_read_file_returns_excerpt` — fixture file, assert excerpt content + `total_lines` field.
- `test_handle_read_file_caps_at_500_lines` — fixture 1000-line file, assert excerpt has ≤ 500 lines.
- `test_handle_read_file_rejects_path_traversal` — `path="../../etc/passwd"`, assert `ok: False, error: "outside repo root"`.
- `test_handle_read_file_returns_error_on_missing` — non-existent path, assert `ok: False`.
- `test_handle_find_symbol_locates_class_definition` — fixture with `class Foo:` → assert `find_symbol(name="Foo")` returns matching line.
- `test_handle_find_symbol_rejects_invalid_identifier` — `name="not a thing!"`, assert `ok: False, error: "invalid Python identifier"`.
- `test_handle_grep_pattern_returns_matches_with_context` — fixture file with known pattern + 2-line context, assert excerpt format.
- `test_handle_grep_pattern_truncates_at_80_results` — fixture with 200 matches, assert response has `truncated: True` and ≤ 80 matches.

`backend/tests/scripts/conftest.py` is unchanged (the `sys.path` insert covers the new test).

### 3.10 Cost projection update

Per-push cost grows from v1's R$ 0.30-0.80 (cache hit) / R$ 1.50-4.00 (cache miss) to v2's:

- Cached read of system blocks: ~R$ 0.05 (unchanged)
- 5-10 tool_use turns × ~3-8 k tokens output each: ~R$ 0.50-1.50 added
- `report_findings` final turn: ~R$ 0.20
- **Total cache hit**: ~R$ 0.75-1.75 per push
- **Total cache miss**: ~R$ 2.00-5.00 per push

vs v1 R$ 0.30-0.80 cache hit. ~2-3× cost increase, justified by FP rate dropping 25% → <5% — every avoided FP-iteration saves ~R$ 0.30 + ~10 min orchestrator time.

---

## 4. Scope OUT — explicitly NOT in this PR

- **Replace the v1 `report_findings` schema**: `ReviewReport` Pydantic model unchanged.
- **MCP connector via `mcp_servers` parameter**: deferred to v3 if v2's catch rate plateaus or Serena LSP-grade resolution becomes essential.
- **Multi-model ensemble** (Haiku first sieve → Sonnet second sieve → report): future iteration, not v2.
- **Auto-fix mode** where the LLM proposes a patch via a `propose_edit` tool: rejected for v2; the orchestrator stays in the loop for fixes.
- **Parallel tool calling**: v2 executes tool_use blocks sequentially within a single turn (Anthropic API supports parallel; the v2 implementation walks `response.content` one block at a time). v3 may add parallel for read_file fan-out.
- **Subprocess-based ripgrep**: pure Python regex is the v2 implementation. If future calibration shows grep latency dominating, swap to `subprocess.run(["rg", ...])` then.
- **Write tools** (any tool that mutates filesystem, runs subprocess, makes HTTP requests, or otherwise has side effects): v2 is read-only.
- **Tools that wrap Serena MCP**: not in v2. Serena requires stdio adapter; out of scope.
- **Pre-fetch via `file_resolver` recursive import-following**: rejected per §0.
- **Calibration eval suite** (corpus of past Codex catches → measure recall against them): future dispatch.
- **GitHub Action mirror**: still local-only.
- **Frontend regen**: this PR ships no schemas / no API surface change.

---

## 5. Operational rules (institutional infra discipline)

- **Hard caps are non-negotiable**: `MAX_ITERATIONS=12` and `MAX_CUMULATIVE_OUTPUT_TOKENS=60000` MUST raise non-zero exit when exceeded. No silent loop continuation. The cap protects against pathological cases (e.g., model loops on the same `find_symbol` call without converging).
- **Tool errors do NOT silently skip**: a tool handler raising MUST return a structured `{"ok": False, "error": "..."}` to the model so it can adapt — but a hook-level exception in the multi-turn loop itself MUST exit non-zero with a clear error message (per `feedback_dispatch_self_consistency` no-silent-fallback rule).
- **Read-only tools, scoped to repo root**: `_resolve_within_repo` rejection is enforced in every handler that touches the filesystem. Test coverage MUST include path-traversal rejection.
- **Audit trail**: cache artifact's `tool_calls` log is the canonical record. Never log credentials or API keys; the log records `(name, input, result_summary)` only.
- **Reproducibility**: model identifier still pinned (no `latest` aliases). Tool definitions in `tools.py` are versioned in git so any historical review run can be reproduced from `(git SHA, model ID, dispatch SHA)`.
- **Bypass discipline**: `git push --no-verify` continues to be the only escape valve. v2 expanding tool surface should NOT make bypass more attractive — calibration data shows v2 reduces FPs, so bypass should become rarer, not more frequent.

---

## 6. Acceptance criteria

- [ ] `scripts/dispatch_review/tool_handlers.py` exists with 3 handlers: `handle_read_file`, `handle_find_symbol`, `handle_grep_pattern`. Each handler is read-only, scoped to `repo_root`, and returns structured `{"ok": bool, ...}` dicts.
- [ ] `_resolve_within_repo` rejects path traversal (test asserts `ok: False, error: "outside repo root"` for `path="../../etc/passwd"`).
- [ ] `scripts/dispatch_review/tools.py` exists with `READ_FILE_TOOL`, `FIND_SYMBOL_TOOL`, `GREP_PATTERN_TOOL` dicts and a `build_review_tools()` function returning all 4 tools (3 investigation + 1 `report_findings`).
- [ ] `scripts/dispatch_review/client.py::call_review` runs a multi-turn loop with `_MAX_ITERATIONS=12` and `_MAX_CUMULATIVE_OUTPUT_TOKENS=60000`. Returns `(ReviewReport, tool_call_log)`. Raises non-zero exit on cap exceedance OR on no-tool-emitted iteration.
- [ ] `client.messages.create` is called WITHOUT `tool_choice` (multi-turn requires the model to choose between investigation tools and `report_findings`).
- [ ] `scripts/dispatch_review/cache.py::write_cache_artifact` accepts and persists optional `tool_calls: list[dict] | None` parameter.
- [ ] `scripts/dispatch_review/prompt_builder.py::_REVIEW_PROTOCOL_PROSE` updated with the §3.4 tool-use discipline block.
- [ ] `scripts/pre_push_review.py::main` passes `repo_root` into `call_review` and forwards `tool_call_log` to `write_cache_artifact`.
- [ ] `scripts/dispatch_review/file_resolver.py` UNCHANGED (`_LINE_CAP=200`).
- [ ] `scripts/dispatch_review/schema.py` UNCHANGED (`ReviewReport` shape stays).
- [ ] `backend/tests/scripts/test_tool_handlers.py` exists with 8 mechanical tests.
- [ ] Manual e2e: invoke the new hook against the merged Wave-2 dispatch (`docs/audits/2026-05-09-phase-a3-pr-2-commodity-correctness-dispatch.md`). Inspect the cache artifact's `tool_calls` array — at least 1 `read_file` or `find_symbol` call observed; the `ReviewReport` either matches or improves on hook v1's findings on the same dispatch.
- [ ] Backend full suite green except known failures (`test_ws.py` Python 3.14).

---

## 7. Test coverage required

- `backend/tests/scripts/test_tool_handlers.py` (NEW) — 8 tests per §3.9 enumeration.
- `backend/tests/scripts/test_file_resolver.py` (existing) — UNCHANGED. The `_LINE_CAP=200` test continues to assert the cap.
- `backend/tests/scripts/test_schema.py` (existing) — UNCHANGED.
- `backend/tests/scripts/test_install_git_hooks.py` (existing) — UNCHANGED.
- `backend/tests/scripts/test_pre_push_review_skip.py` (existing) — UNCHANGED.

**Manual end-to-end smoke test** (NOT pytest; documented in §11): invoke `python scripts/pre_push_review.py --dispatch-paths docs/audits/2026-05-09-phase-a3-pr-2-commodity-correctness-dispatch.md --branch test-v2 --head-sha v2smoke` from the worktree. Inspect the JSON artifact under `.cache/dispatch_review/test-v2-v2smoke.json`. Verify:

1. `tool_calls` array exists and has ≥ 1 entry
2. At least one `read_file` or `find_symbol` call targeted `backend/app/utils/price_reference.py` or `backend/app/services/price_lookup_service.py` (the FP class 1 + 3 surfaces from v1)
3. The `p1_blocking` array does NOT contain the v1 FPs (e.g., "PriceQuote location mismatch" should not appear; the model should have verified via tool call)
4. Total cumulative_output_tokens (computable from sum of per-turn outputs) < 60000

Document the smoke test result in the PR body's "Acceptance evidence" section.

---

## 8. Critical sequencing

This PR ships against `main` at `bf021b837` (post-PR-#42 merge). It depends on hook v1 being in place; without v1, there is no `scripts/dispatch_review/` package to extend.

- **Branch base**: `origin/main` at `bf021b837` or later.
- **Migration chain**: untouched.
- **Downstream dependency**: Wave 3 dispatch (PR-A3-3, J-A3-OPUS-02/06/07) benefits from this hook v2 — but does NOT block on it. If v2 is delayed, Wave 3 authors against v1 with known FP classes.
- **Recommended merge order**: (a) This infra PR (v2) lands first; (b) Wave 3 dispatch authors against v2 with reduced FP load; (c) PR-A3-2 implementation runs in parallel (executor session, separate worktree, independent of v2 timing).

The hook v2 is a **productivity multiplier**, not a prerequisite for any audit-cycle correctness invariant.

---

## 9. PR shape

**Title:** `infra: pre-push hook v2 — tool-use enhancement (Sonnet investigates before asserting)`

**Body skeleton:**

```markdown
## Summary

Hook v2 extends v1 with custom tool-use so Sonnet 4.6 can dynamically
read files, search symbols, and grep for patterns during dispatch
review. Eliminates the 3 false-positive classes documented in
`reference_pre_push_hook_calibration` (utils/ visibility gap, 200-line
file_resolver cap, identifier-mapping inference).

Tools added (read-only, scoped to repo root):
- `read_file(path, start_line?, end_line?)` — up to 500 lines
- `find_symbol(name)` — locate Python class/function/constant definition
- `grep_pattern(pattern, path_glob?, context_lines?)` — regex search

Multi-turn loop in `call_review` with hard caps:
- MAX_ITERATIONS = 12
- MAX_CUMULATIVE_OUTPUT_TOKENS = 60000

Cache artifact gains `tool_calls` array for post-hoc calibration.

## Files changed

- `scripts/dispatch_review/tool_handlers.py` (NEW) — handler functions
- `scripts/dispatch_review/tools.py` (NEW) — Anthropic tool schemas
- `scripts/dispatch_review/client.py` — multi-turn loop, caps, no `tool_choice` forcing
- `scripts/dispatch_review/prompt_builder.py` — `_REVIEW_PROTOCOL_PROSE` updated with tool-use discipline
- `scripts/dispatch_review/cache.py` — `tool_calls` field
- `scripts/pre_push_review.py` — pass `repo_root`, forward `tool_call_log`
- `backend/tests/scripts/test_tool_handlers.py` (NEW) — 8 mechanical tests

## Acceptance evidence

- [ ] All criteria from dispatch §6 met
- [ ] Manual e2e smoke test on merged Wave-2 dispatch produced expected `tool_calls` evidence (see §7)
- [ ] No P1 FPs from the 3 known v1 FP classes (utils/ visibility, line numbers, identifier mapping inference)

## Constitutional impact

None — this PR ships tooling that complements the existing audit
review pipeline. No production code path touched.

## Out of scope

See dispatch §4 — schema changes, MCP connector, multi-model ensemble,
auto-fix, parallel tool calling, write tools, frontend regen.

## Cost projection

~R$ 0.75-1.75 per push that triggers review (cache hit; multi-turn).
~2-3× v1's cost. Justified by FP rate dropping 25% → <5%.
```

---

## 10. Constraints — what NOT to do

- DO NOT enable `tool_choice` forcing in the multi-turn loop. Forcing the model to call only one tool prevents investigation; the model must be free to choose between investigation tools and `report_findings`.
- DO NOT raise `_LINE_CAP` in `file_resolver.py`. Pre-inlining stays bounded at 200 lines/file; the new `read_file` tool covers gaps.
- DO NOT add write tools, subprocess-execution tools, or tools that make HTTP requests. v2 is read-only.
- DO NOT skip the `_resolve_within_repo` check in any handler that takes a path argument. Path-traversal rejection is enforced per handler, not centralized.
- DO NOT use ripgrep / `subprocess.run(["rg", ...])`. Pure Python regex is the v2 implementation; swap only after measured calibration evidence.
- DO NOT log API keys, full tool inputs that may contain secrets, or full tool results that may contain credentials. The `result_summary` field is a redacted summary, not a verbatim copy.
- DO NOT remove the `report_findings` tool from `build_review_tools`. It is the loop-termination signal.
- DO NOT pin a `claude-sonnet-latest`-style alias. Pin the same dated/versioned identifier as v1 (`claude-sonnet-4-6` or successor).
- DO NOT use `--no-verify` during this PR's own implementation cycle UNLESS the hook v1 itself produces a runaway FP cycle on the v2 dispatch. The hook v1 SHOULD review this dispatch — that's the institutional integrity check.
- DO NOT auto-merge — wait for Codex review.

---

## 11. Workflow

1. `git fetch origin && git worktree add D:/Projetos/Hedge-Control-New-hook-v2 origin/main && cd D:/Projetos/Hedge-Control-New-hook-v2 && git checkout -b infra/pre-push-hook-v2-tool-use`.
2. Configure `.claude/settings.local.json` per the worktree pattern (allow git/gh/pytest/python/pip; deny `--force` raw, `--auto`, `--no-verify`, push to main).
3. Read references in §2 — especially `reference_pre_push_hook_calibration` for the empirical FP classes v2 targets.
4. Verify Anthropic SDK current pinned version + tool-use API surface: `python -c "from anthropic.types import ToolUseBlock, ToolResultBlockParam; print('OK')"`. Update §2 if the type-import paths changed in a newer SDK.
5. Create `scripts/dispatch_review/tool_handlers.py` per §3.1. Pure Python regex; no ripgrep dependency.
6. Implement `_resolve_within_repo` first; it's the security-critical helper used by every path-taking handler.
7. Implement `handle_read_file` per §3.1. Enforce `_MAX_LINES_PER_READ=500`.
8. Implement `_grep_with_context` (shared by `handle_find_symbol` and `handle_grep_pattern`). Enforce `_MAX_GREP_RESULTS=80` and byte cap.
9. Implement `handle_find_symbol` and `handle_grep_pattern` per §3.1.
10. Create `scripts/dispatch_review/tools.py` per §3.2. Tool schemas + `build_review_tools()`.
11. Update `scripts/dispatch_review/client.py::call_review` per §3.3. Multi-turn loop, no `tool_choice` forcing, hard caps, tool dispatch, `tool_call_log`. Add `_create_with_retry` helper if extracting the inner network retry from the existing body keeps the code clean.
12. Update `scripts/dispatch_review/prompt_builder.py::_REVIEW_PROTOCOL_PROSE` per §3.4 (append the tool-use discipline subsection).
13. Update `scripts/dispatch_review/cache.py::write_cache_artifact` per §3.6 (optional `tool_calls` parameter).
14. Update `scripts/pre_push_review.py::main` per §3.8 (pass `repo_root`, forward `tool_call_log`).
15. Verify `scripts/dispatch_review/file_resolver.py` UNCHANGED. Verify `scripts/dispatch_review/schema.py` UNCHANGED.
16. Author `backend/tests/scripts/test_tool_handlers.py` per §3.9 (8 mechanical tests).
17. Run targeted pytest: `pytest backend/tests/scripts/ -v`. All pre-existing v1 tests + new v2 tests must pass.
18. Full backend suite: `pytest backend/tests/ -v` — green except known failures (3 pre-existing `test_ws.py` Python 3.14 failures).
19. **Manual e2e smoke test** per §7: invoke `python scripts/pre_push_review.py --dispatch-paths docs/audits/2026-05-09-phase-a3-pr-2-commodity-correctness-dispatch.md --branch test-v2 --head-sha v2smoke`. Inspect the JSON artifact. Document findings in PR body.
20. `git push -u origin infra/pre-push-hook-v2-tool-use && gh pr create --base main --title "<§9 title>" --body-file <body>` — DO NOT use `--draft`.
21. **Hook v1 will review this PR's dispatch** when pushed. Absorb any P1 returns; treat hook v1 self-review of v2 dispatch as institutional integrity check.
22. **STOP. Wait for Codex review.** Address each catch as a new commit. Expected catch count: 3-7 (broader surface than a typical wave dispatch — Python, multi-turn protocol, regex security).
23. Report back to orchestrator with PR URL, final SHA, Codex review state, files-touched grouping, test counts, and the manual e2e log.

---

## 12. Final report shape

When complete, report to orchestrator:
- Branch + PR URL + final SHA.
- Files touched (grouped: scripts/dispatch_review/ / scripts/ / tests / docs).
- Test pass/fail counts vs main baseline.
- Codex review status + catches absorbed (per round).
- Hook v1 self-review JSON artifact path + summary.
- Manual e2e log: `pre_push_review.py` JSON artifact for the Wave-2 dispatch, with annotated comparison against v1's findings on the same dispatch.
- Anthropic SDK pinned version + dated model identifier used.
- Cumulative API spend observed during smoke + manual tests (Anthropic Console usage page).

Keep report under 800 words.

Boa caça.
