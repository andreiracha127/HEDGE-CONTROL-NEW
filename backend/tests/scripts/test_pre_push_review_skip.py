"""Pre-push review trigger coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pre_push_review
from dispatch_review.schema import Finding, ReviewReport


def test_main_exits_0_with_no_changed_paths(capsys, tmp_path) -> None:
    rc = pre_push_review.main(
        [
            "--changed-paths",
            "--branch",
            "test-branch",
            "--head-sha",
            "deadbeef",
            "--repo-root",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "no changed files in push range" in captured.out


def test_backend_change_without_dispatch_invokes_reviewer_and_writes_artifact(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    changed_path = tmp_path / "backend" / "tests" / "test_migration.py"
    changed_path.parent.mkdir(parents=True)
    changed_path.write_text("def test_stub():\n    assert True\n", encoding="utf-8")
    payload_args: dict[str, object] = {}

    monkeypatch.setattr(pre_push_review, "build_cached_system_blocks", lambda _repo_root: [])

    def _build_user_payload(**kwargs):
        payload_args.update(kwargs)
        return "payload"

    monkeypatch.setattr(pre_push_review, "build_user_payload", _build_user_payload)
    monkeypatch.setattr(
        pre_push_review,
        "call_review",
        lambda **_kwargs: (ReviewReport(summary="clean", p1_blocking=[], p2_warn=[], p3_info=[]), []),
    )

    rc = pre_push_review.main(
        [
            "--changed-paths",
            "backend/tests/test_migration.py",
            "--branch",
            "test-branch",
            "--head-sha",
            "deadbeef123456",
            "--repo-root",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    artifact_path = tmp_path / ".cache" / "dispatch_review" / "test-branch-deadbeef1234.json"
    assert rc == 0
    assert "reviewing 1 changed file(s)" in captured.out
    assert "artifact written" in captured.out
    assert artifact_path.is_file()
    assert payload_args["changed_paths"] == ["backend/tests/test_migration.py"]
    assert payload_args["dispatch_paths"] == []


def test_dispatch_file_in_changed_paths_is_passed_as_optional_context(
    monkeypatch, tmp_path: Path
) -> None:
    dispatch_path = tmp_path / "docs" / "audits" / "feature-dispatch.md"
    dispatch_path.parent.mkdir(parents=True)
    dispatch_path.write_text("# Dispatch\n", encoding="utf-8")
    payload_args: dict[str, object] = {}

    monkeypatch.setattr(pre_push_review, "build_cached_system_blocks", lambda _repo_root: [])

    def _build_user_payload(**kwargs):
        payload_args.update(kwargs)
        return "payload"

    monkeypatch.setattr(pre_push_review, "build_user_payload", _build_user_payload)
    monkeypatch.setattr(
        pre_push_review,
        "call_review",
        lambda **_kwargs: (ReviewReport(summary="clean", p1_blocking=[], p2_warn=[], p3_info=[]), []),
    )

    rc = pre_push_review.main(
        [
            "--changed-paths",
            "docs/audits/feature-dispatch.md",
            "--branch",
            "test-branch",
            "--head-sha",
            "deadbeef123456",
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert payload_args["changed_paths"] == ["docs/audits/feature-dispatch.md"]
    assert payload_args["dispatch_paths"] == [dispatch_path.resolve()]


def test_p1_blocking_report_still_blocks_and_writes_artifact(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    changed_path = tmp_path / "backend" / "app" / "migration.py"
    changed_path.parent.mkdir(parents=True)
    changed_path.write_text("revision = 'abc'\n", encoding="utf-8")
    finding = Finding(
        rule="Tipo-I-fact-mismatch",
        section="changed files",
        snippet="bad migration",
        why="verified blocker",
        fix_suggestion="fix migration",
    )

    monkeypatch.setattr(pre_push_review, "build_cached_system_blocks", lambda _repo_root: [])
    monkeypatch.setattr(pre_push_review, "build_user_payload", lambda **_kwargs: "payload")
    monkeypatch.setattr(
        pre_push_review,
        "call_review",
        lambda **_kwargs: (
            ReviewReport(summary="blocked", p1_blocking=[finding], p2_warn=[], p3_info=[]),
            [{"name": "read_file", "ok": True}],
        ),
    )

    rc = pre_push_review.main(
        [
            "--changed-paths",
            "backend/app/migration.py",
            "--branch",
            "test-branch",
            "--head-sha",
            "deadbeef123456",
            "--repo-root",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    artifact_path = tmp_path / ".cache" / "dispatch_review" / "test-branch-deadbeef1234.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert rc == 1
    assert "P1 finding(s) -push blocked" in captured.out
    assert artifact_path.is_file()
    assert payload["p1_blocking"][0]["rule"] == "Tipo-I-fact-mismatch"
    assert payload["tool_calls"] == [{"name": "read_file", "ok": True}]
