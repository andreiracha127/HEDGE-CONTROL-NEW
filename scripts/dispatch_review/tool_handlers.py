"""Read-only tool handlers for the pre-push hook v2 multi-turn review."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_MAX_LINES_PER_READ = 500
_MAX_BYTES_PER_READ = 60_000
_MAX_FILE_SIZE_BYTES = 2_000_000
_MAX_GREP_RESULTS = 80
_MAX_FIND_SYMBOL_BYTES = 8000

_SECRET_BEARING_BASENAME_PREFIXES = (".env",)
_SECRET_BEARING_BASENAMES = frozenset(
    {
        "credentials.json",
        "credentials.yaml",
        "credentials.yml",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
    }
)


def _is_secret_bearing_path(path: Path) -> bool:
    """Return True when the basename belongs to the secret denylist."""
    name = path.name
    if name in _SECRET_BEARING_BASENAMES:
        return True
    return any(name == prefix or name.startswith(prefix + ".") for prefix in _SECRET_BEARING_BASENAME_PREFIXES)


def _resolve_within_repo(repo_root: Path, raw_path: str) -> Path:
    """Resolve a path under repo_root and reject traversal outside it."""
    repo_root_resolved = repo_root.resolve()
    candidate = (repo_root_resolved / raw_path).resolve()
    try:
        candidate.relative_to(repo_root_resolved)
    except ValueError as exc:
        raise ValueError(f"path {raw_path!r} resolves outside repo root") from exc
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
    if _is_secret_bearing_path(target):
        return {
            "ok": False,
            "error": (
                f"path {path_str!r} matches the secret-bearing denylist; "
                "reads of .env / credentials.* / secrets.* / SSH key files are refused. "
                "Use find_symbol or grep_pattern on source files instead."
            ),
        }

    try:
        file_size = target.stat().st_size
    except OSError as exc:
        return {"ok": False, "error": f"cannot stat file {path_str!r}: {exc}"}
    if file_size > _MAX_FILE_SIZE_BYTES:
        return {
            "ok": False,
            "error": (
                f"file {path_str!r} is {file_size} bytes (>{_MAX_FILE_SIZE_BYTES}); "
                "likely a generated artifact or source map. Use grep_pattern with "
                "a narrower path or read a different file."
            ),
        }

    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    is_empty_file_at_line_1 = len(lines) == 0 and start_line == 1
    if not is_empty_file_at_line_1:
        if start_line < 1:
            return {
                "ok": False,
                "error": (
                    f"start_line={start_line} must be >= 1; Python slicing with "
                    "negative indices would silently return the wrong range."
                ),
            }
        if start_line > len(lines):
            return {
                "ok": False,
                "error": (
                    f"start_line={start_line} is past EOF (file has {len(lines)} lines). "
                    f"Pass start_line in [1..{max(len(lines), 1)}]."
                ),
            }
        if end_line is not None and int(end_line) < start_line:
            return {
                "ok": False,
                "error": (
                    f"end_line={end_line} < start_line={start_line}. "
                    "end_line must be >= start_line."
                ),
            }

    end_clamped = int(end_line) if end_line is not None else min(
        start_line + _MAX_LINES_PER_READ - 1,
        max(len(lines), 1),
    )
    if end_clamped - start_line + 1 > _MAX_LINES_PER_READ:
        end_clamped = start_line + _MAX_LINES_PER_READ - 1

    excerpt = "\n".join(lines[start_line - 1 : end_clamped])
    excerpt_truncated = False
    if len(excerpt) > _MAX_BYTES_PER_READ:
        excerpt = excerpt[:_MAX_BYTES_PER_READ]
        excerpt_truncated = True

    return {
        "ok": True,
        "path": path_str,
        "start_line": start_line,
        "end_line": end_clamped,
        "total_lines": len(lines),
        "excerpt": excerpt,
        "excerpt_truncated": excerpt_truncated,
    }


def handle_find_symbol(payload: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    """Locate a Python class, function, method, or module-level constant."""
    name = payload["name"]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return {"ok": False, "error": f"invalid Python identifier: {name!r}"}
    pattern = rf"^\s*(class\s+{re.escape(name)}\b|(?:async\s+)?def\s+{re.escape(name)}\b|{re.escape(name)}\s*[:=])"
    return _grep_with_context(
        repo_root,
        pattern,
        ["backend/app", "backend/tests", "scripts"],
        context_lines=15,
        byte_cap=_MAX_FIND_SYMBOL_BYTES,
    )


def handle_grep_pattern(payload: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    pattern = payload["pattern"]
    search_path = payload.get("search_path") or "backend/app"
    context_lines = int(payload.get("context_lines") or 0)
    return _grep_with_context(
        repo_root,
        pattern,
        [search_path],
        context_lines=context_lines,
        byte_cap=_MAX_GREP_RESULTS * 200,
    )


def _grep_with_context(
    repo_root: Path,
    pattern: str,
    search_paths: list[str],
    *,
    context_lines: int,
    byte_cap: int,
) -> dict[str, Any]:
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return {"ok": False, "error": f"invalid regex: {exc}"}

    matches: list[dict[str, Any]] = []
    cumulative_bytes = 0
    searched_count = 0
    inspected_files = 0
    repo_root_resolved = repo_root.resolve()

    for search_path in search_paths:
        try:
            root = _resolve_within_repo(repo_root_resolved, search_path)
        except ValueError:
            continue
        if not root.exists():
            continue
        searched_count += 1
        files = root.rglob("*.py") if root.is_dir() else [root]
        for file_path in files:
            if file_path.is_symlink():
                continue
            try:
                resolved_file = file_path.resolve()
                resolved_file.relative_to(repo_root_resolved)
            except (OSError, ValueError):
                continue
            if _is_secret_bearing_path(file_path):
                continue
            try:
                if file_path.stat().st_size > _MAX_FILE_SIZE_BYTES:
                    continue
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue

            inspected_files += 1
            for idx, line in enumerate(lines, start=1):
                if not compiled.search(line):
                    continue
                excerpt_start = max(1, idx - context_lines)
                excerpt_end = min(len(lines), idx + context_lines)
                excerpt = "\n".join(
                    f"{line_no}: {lines[line_no - 1]}"
                    for line_no in range(excerpt_start, excerpt_end + 1)
                )
                rel = resolved_file.relative_to(repo_root_resolved).as_posix()
                entry = {"file": rel, "line": idx, "excerpt": excerpt}
                cumulative_bytes += len(excerpt) + len(rel) + 16
                if cumulative_bytes > byte_cap:
                    if matches:
                        return {
                            "ok": True,
                            "matches": matches,
                            "truncated": True,
                            "searched_count": searched_count,
                            "inspected_files": inspected_files,
                        }
                    available = max(0, byte_cap - len(rel) - 16)
                    if available > 0:
                        entry["excerpt"] = excerpt[:available] + "\n# ...[truncated]"
                        matches.append(entry)
                        return {
                            "ok": True,
                            "matches": matches,
                            "truncated": True,
                            "searched_count": searched_count,
                            "inspected_files": inspected_files,
                        }
                    return {
                        "ok": False,
                        "error": (
                            "first matching excerpt exceeds byte_cap even after truncation. "
                            "Try a narrower search_path or a more specific pattern."
                        ),
                        "matches": [],
                        "searched_count": searched_count,
                        "inspected_files": inspected_files,
                        "truncated": True,
                    }
                matches.append(entry)
                if len(matches) >= _MAX_GREP_RESULTS:
                    return {
                        "ok": True,
                        "matches": matches,
                        "truncated": True,
                        "searched_count": searched_count,
                        "inspected_files": inspected_files,
                    }

    if searched_count == 0:
        return {
            "ok": False,
            "error": (
                f"no requested search root could be inspected (received {len(search_paths)} "
                "path(s); 0 passed _resolve_within_repo + exists() validation). "
                "Pass an in-repo path like 'backend/app' or 'backend/app/services/foo.py'."
            ),
            "matches": [],
            "searched_count": 0,
            "inspected_files": 0,
        }
    if inspected_files == 0:
        return {
            "ok": False,
            "error": (
                f"all candidate files under {searched_count} validated search root(s) "
                "were skipped (symlinks, secret-bearing basenames, oversized files, "
                "or OSError-on-read). Zero file contents were actually inspected."
            ),
            "matches": [],
            "searched_count": searched_count,
            "inspected_files": 0,
        }
    return {
        "ok": True,
        "matches": matches,
        "truncated": False,
        "searched_count": searched_count,
        "inspected_files": inspected_files,
    }


HANDLERS = {
    "read_file": handle_read_file,
    "find_symbol": handle_find_symbol,
    "grep_pattern": handle_grep_pattern,
}
