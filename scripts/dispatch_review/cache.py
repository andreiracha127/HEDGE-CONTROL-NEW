"""JSON cache-artifact writer for review reports."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .schema import ReviewReport

_CACHE_RELATIVE = Path(".cache") / "dispatch_review"


def _slugify_branch(branch: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-") or "unknown-branch"


def write_cache_artifact(
    report: ReviewReport,
    *,
    repo_root: Path,
    branch: str,
    head_sha: str,
) -> Path:
    cache_dir = repo_root / _CACHE_RELATIVE
    cache_dir.mkdir(parents=True, exist_ok=True)
    short_sha = head_sha[:12] if head_sha else "no-sha"
    out_path = cache_dir / f"{_slugify_branch(branch)}-{short_sha}.json"
    payload = report.model_dump(mode="json")
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out_path
