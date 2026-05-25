"""Generate the E2E production-readiness go/no-go report."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pytest_failures(payload: dict[str, Any]) -> list[str]:
    return [
        test.get("nodeid", "<unknown>")
        for test in payload.get("tests", [])
        if test.get("outcome") in {"failed", "error"}
    ]


def _playwright_unexpected(payload: dict[str, Any]) -> int:
    stats = payload.get("stats", {})
    return int(stats.get("unexpected", 0) or 0)


def _override_allowed(failures: list[str], rationale: str | None) -> bool:
    if not rationale:
        return False
    return bool(failures) and all("test_scenario_isolation.py" in f for f in failures)


def _render_report(
    *,
    verdict: str,
    pytest_failures: list[str],
    playwright_unexpected: int,
    override_rationale: str | None,
) -> str:
    lines = [
        "# E2E Production Readiness Go/No-Go",
        "",
        f"Generated UTC: {datetime.now(UTC).isoformat()}",
        f"Verdict: {verdict}",
        "",
        "## Pytest",
        f"Failures: {len(pytest_failures)}",
    ]
    if pytest_failures:
        lines.extend(f"- {failure}" for failure in pytest_failures)
    lines.extend(
        [
            "",
            "## Playwright",
            f"Unexpected failures: {playwright_unexpected}",
        ]
    )
    if override_rationale:
        lines.extend(["", "## Override", f"Override: {override_rationale}"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pytest-json", required=True)
    parser.add_argument("--playwright-json", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--override-rationale")
    args = parser.parse_args(argv)

    pytest_payload = _load_json(Path(args.pytest_json))
    playwright_payload = _load_json(Path(args.playwright_json))
    failures = _pytest_failures(pytest_payload)
    unexpected = _playwright_unexpected(playwright_payload)

    clean = not failures and unexpected == 0
    override = _override_allowed(failures, args.override_rationale) and unexpected == 0
    verdict = "GO" if clean or override else "NO-GO"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _render_report(
            verdict=verdict,
            pytest_failures=failures,
            playwright_unexpected=unexpected,
            override_rationale=args.override_rationale if override else None,
        ),
        encoding="utf-8",
    )
    return 0 if verdict == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
