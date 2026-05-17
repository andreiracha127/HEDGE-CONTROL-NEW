#!/usr/bin/env python3
"""PreToolUse hook: blocks float() literals on market-data ingest paths.

Constitutional rule (docs/governance.md, MARKET-DATA GOVERNANCE):
  Live float parsing is prohibited on the ingest path. Westmetall ingest must
  reject float inputs and construct via Decimal(str(raw)) only.

Reads the Claude Code hook JSON payload from stdin. Exits 2 to block the
Edit/Write, 0 to allow. Stderr is shown to Claude and the user.
"""
from __future__ import annotations

import json
import re
import sys

INGEST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"backend[\\/]+app[\\/]+services[\\/]+westmetall[_a-zA-Z0-9]*\.py$"),
    re.compile(r"backend[\\/]+app[\\/]+services[\\/]+cash_settlement_prices\.py$"),
    re.compile(r"backend[\\/]+app[\\/]+services[\\/]+price_lookup_service\.py$"),
    re.compile(r"backend[\\/]+app[\\/]+services[\\/]+market_data_governance\.py$"),
)

# Match float(...) but skip the standard Python sentinel idioms
# float("inf"), float("-inf"), float("infinity"), float("-infinity"), float("nan")
# (case-insensitive on the literal token). These are not market-data parses;
# blocking them is a false positive and would permanently block any Write that
# replays existing sentinel-bearing lines (see PR #90 Greptile review).
FLOAT_LITERAL = re.compile(
    r"\bfloat\s*\("
    r"(?!\s*['\"]"
    r"(?i:inf(?:inity)?|-inf(?:inity)?|nan)"
    r"['\"]\s*\))"
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    file_path = (tool_input.get("file_path") or "").replace("/", "\\")

    if not any(pattern.search(file_path) for pattern in INGEST_PATTERNS):
        return 0

    candidate = (
        tool_input.get("new_string")
        or tool_input.get("content")
        or ""
    )

    if not FLOAT_LITERAL.search(candidate):
        return 0

    print(
        "\nBLOCKED — precision_guard.py\n"
        "----------------------------\n"
        "float(...) literal detected on a market-data ingest path.\n\n"
        "Constitutional rule (docs/governance.md, MARKET-DATA GOVERNANCE):\n"
        "  'Live float parsing is prohibited on the ingest path. Westmetall\n"
        "   ingest must reject float inputs and construct via Decimal(str(raw))\n"
        "   only.'\n\n"
        f"  File: {file_path}\n\n"
        "Remediation:\n"
        "  - If parsing external numeric input: Decimal(str(raw_value)).\n"
        "  - If converting an already-Decimal value to float for transport,\n"
        "    do it at the serialization boundary (Pydantic schema), not in\n"
        "    a service-layer ingest module.\n\n"
        "If this is genuinely required and governance-authorized, the only\n"
        "bypass is to commit without going through Claude (or to remove the\n"
        "ingest path from precision_guard.py INGEST_PATTERNS after governance\n"
        "amends the rule in docs/governance.md).\n",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
