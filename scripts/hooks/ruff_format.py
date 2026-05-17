#!/usr/bin/env python3
"""PostToolUse hook: runs `ruff check --fix` then `ruff format` on the edited
Python file when the path falls inside backend/.

Reads the Claude Code hook JSON from stdin. Never blocks (always exits 0).
Stderr is informational and surfaced to the user but does not fail the tool
call.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# Matches both absolute `/.../backend/...` and repo-relative `backend/...` paths
# (after backslash normalization). Claude Code hook payloads can be either form
# depending on platform and how the session is rooted (PR #90 Greptile + AugmentCode).
BACKEND_PATH = re.compile(r"(?:^|/)backend/")

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path") or ""
    if not file_path.endswith(".py"):
        return 0

    normalized = file_path.replace("\\", "/")
    if not BACKEND_PATH.search(normalized):
        return 0

    if not BACKEND_DIR.exists():
        return 0

    # Resolve to absolute before invoking ruff. A relative `backend/app/...` with
    # cwd=BACKEND_DIR would otherwise resolve to a non-existent `backend/backend/...`.
    abs_path = str(Path(file_path).resolve())

    try:
        check = subprocess.run(
            ["ruff", "check", "--fix", abs_path],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=15,
        )
        fmt = subprocess.run(
            ["ruff", "format", abs_path],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        print("ruff not found on PATH; skipping format", file=sys.stderr)
        return 0
    except subprocess.TimeoutExpired:
        print("ruff timed out; skipping format", file=sys.stderr)
        return 0

    msgs: list[str] = []
    if check.returncode != 0 and check.stdout.strip():
        msgs.append("ruff check (autofix attempted):")
        msgs.append(check.stdout.strip())
    if fmt.returncode != 0 and fmt.stderr.strip():
        msgs.append("ruff format:")
        msgs.append(fmt.stderr.strip())

    if msgs:
        print("\n".join(msgs), file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
