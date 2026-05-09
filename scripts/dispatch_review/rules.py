"""Loader for the in-repo rule sheet at ``docs/audit-protocol/dispatch-review-rules.md``."""

from __future__ import annotations

from pathlib import Path

_RULE_SHEET_RELATIVE = Path("docs") / "audit-protocol" / "dispatch-review-rules.md"


def load_rule_sheet(repo_root: Path) -> str:
    path = repo_root / _RULE_SHEET_RELATIVE
    if not path.is_file():
        raise FileNotFoundError(
            f"Rule sheet not found at {path}. Run from a repo root where "
            f"{_RULE_SHEET_RELATIVE} exists, or check that this file was not "
            "deleted from main."
        )
    return path.read_text(encoding="utf-8")


def load_governance(repo_root: Path) -> str:
    path = repo_root / "docs" / "governance.md"
    if not path.is_file():
        raise FileNotFoundError(f"governance.md not found at {path}")
    return path.read_text(encoding="utf-8")
