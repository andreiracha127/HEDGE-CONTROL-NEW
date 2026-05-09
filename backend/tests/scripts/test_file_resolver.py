"""Tests for ``scripts/dispatch_review/file_resolver.py``."""

from __future__ import annotations

from pathlib import Path

from dispatch_review.file_resolver import extract_cited_paths, resolve_cited_files


def test_extract_cited_paths_finds_backend_python_paths() -> None:
    text = (
        "Edit `backend/app/services/foo.py` and check "
        "`backend/tests/test_foo.py` plus `docs/governance.md`."
    )
    assert extract_cited_paths(text) == [
        "backend/app/services/foo.py",
        "backend/tests/test_foo.py",
        "docs/governance.md",
    ]


def test_extract_cited_paths_strips_line_anchors_and_dedupes() -> None:
    text = (
        "See `backend/app/services/foo.py:42` then `backend/app/services/foo.py:73` "
        "and again `backend/app/services/foo.py`."
    )
    assert extract_cited_paths(text) == ["backend/app/services/foo.py"]


def test_resolve_cited_files_skips_frontend_and_caps_excerpt(tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "backend" / "app" / "services").mkdir(parents=True)
    (repo_root / "frontend-svelte" / "src").mkdir(parents=True)
    (repo_root / "docs" / "audits").mkdir(parents=True)

    big_file = repo_root / "backend" / "app" / "services" / "big.py"
    big_file.write_text("\n".join(f"line_{i}" for i in range(1, 501)), encoding="utf-8")

    fe_file = repo_root / "frontend-svelte" / "src" / "ui.ts"
    fe_file.write_text("// frontend should be skipped", encoding="utf-8")

    dispatch = repo_root / "docs" / "audits" / "fake-dispatch.md"
    dispatch.write_text(
        "Edit `backend/app/services/big.py` and `frontend-svelte/src/ui.ts`.",
        encoding="utf-8",
    )

    out = resolve_cited_files(dispatch, repo_root)
    assert "backend/app/services/big.py" in out
    assert "frontend-svelte/src/ui.ts" not in out
    excerpt_lines = out["backend/app/services/big.py"].splitlines()
    assert len(excerpt_lines) <= 201
    assert any("truncated" in line for line in excerpt_lines)


def test_resolve_cited_files_returns_empty_when_no_cited_paths(tmp_path: Path) -> None:
    dispatch = tmp_path / "no-citations-dispatch.md"
    dispatch.write_text("Pure prose. No backticked paths.", encoding="utf-8")
    assert resolve_cited_files(dispatch, tmp_path) == {}


def test_resolve_cited_files_includes_explicitly_cited_alembic_migration(tmp_path: Path) -> None:
    """Alembic migrations are common Tipo-I catch surface; when the dispatch
    backticks a specific migration path, the resolver MUST inline it so the
    LLM reviewer can verify ``op.add_column`` / ``op.batch_alter_table``
    arguments against the actual migration body.
    """
    repo_root = tmp_path
    path = "backend/alembic/versions/038_x.py"
    target = repo_root / path
    target.parent.mkdir(parents=True)
    target.write_text("def upgrade():\n    op.add_column('orders', col)\n", encoding="utf-8")
    dispatch = repo_root / "x-dispatch.md"
    dispatch.write_text(f"See `{path}`.", encoding="utf-8")
    out = resolve_cited_files(dispatch, repo_root)
    assert path in out
    assert "op.add_column" in out[path]
