"""Extract repo file paths cited inside a dispatch markdown and inline excerpts."""

from __future__ import annotations

import re
from pathlib import Path

_PATH_PATTERN = re.compile(
    r"`(backend/(?:app|tests|alembic/versions)/[^`\s]+\.py|docs/governance\.md|docs/audits/[^`\s]+\.md)`"
)
_LINE_CAP = 200


def _normalize(path_str: str) -> str:
    return path_str.replace("\\", "/")


def extract_cited_paths(dispatch_text: str) -> list[str]:
    raw = _PATH_PATTERN.findall(dispatch_text)
    seen: set[str] = set()
    ordered: list[str] = []
    for entry in raw:
        normalized = _normalize(entry).split("#", 1)[0].split(":", 1)[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def resolve_cited_files(
    dispatch_path: Path, repo_root: Path
) -> dict[str, str]:
    """Return ``{relative_path: capped excerpt}`` for paths cited in the dispatch.

    Frontend paths (``frontend-svelte/**``) are intentionally excluded — see
    dispatch §3.1.6. Alembic migration files (``backend/alembic/versions/**``)
    are included **only when explicitly cited** by the dispatch (the regex
    requires the full path inside backticks); they are common Tipo-I catch
    surface for ``op.add_column`` / ``op.batch_alter_table`` mismatches.
    """
    text = dispatch_path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for rel in extract_cited_paths(text):
        if rel.startswith("frontend"):
            continue
        full = repo_root / rel
        if not full.is_file():
            continue
        try:
            content = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = content.splitlines()
        if len(lines) > _LINE_CAP:
            lines = lines[:_LINE_CAP]
            lines.append(f"# ... [truncated at {_LINE_CAP} lines]")
        out[rel] = "\n".join(lines)
    return out
