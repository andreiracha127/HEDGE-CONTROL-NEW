"""Tests for ``scripts/install_git_hooks.py`` idempotence."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import install_git_hooks


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _setup_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    _git(["init", "-q"], cwd=repo)
    hooks_dir = repo / ".githooks"
    hooks_dir.mkdir()
    (hooks_dir / "pre-push").write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
    monkeypatch.setattr(install_git_hooks, "__file__", str(repo / "scripts" / "install_git_hooks.py"))
    (repo / "scripts").mkdir()
    return repo


def test_install_sets_hooks_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = _setup_repo(tmp_path, monkeypatch)
    rc = install_git_hooks.main()
    assert rc == 0
    assert _git(["config", "core.hooksPath"], cwd=repo) == ".githooks"


def test_install_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = _setup_repo(tmp_path, monkeypatch)
    assert install_git_hooks.main() == 0
    assert install_git_hooks.main() == 0
    assert _git(["config", "core.hooksPath"], cwd=repo) == ".githooks"
