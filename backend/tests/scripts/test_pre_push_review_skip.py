"""Pre-push review trigger coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pre_push_review
from dispatch_review.prompt_builder import build_cached_system_blocks
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


def test_default_model_is_haiku_and_env_can_override(
    monkeypatch, tmp_path: Path
) -> None:
    changed_path = tmp_path / "backend" / "tests" / "test_migration.py"
    changed_path.parent.mkdir(parents=True)
    changed_path.write_text("def test_stub():\n    assert True\n", encoding="utf-8")
    models: list[str] = []

    monkeypatch.setattr(pre_push_review, "build_cached_system_blocks", lambda _repo_root: [])
    monkeypatch.setattr(pre_push_review, "build_user_payload", lambda **_kwargs: "payload")

    def _call_review(**kwargs):
        models.append(kwargs["model"])
        return ReviewReport(summary="clean", p1_blocking=[], p2_warn=[], p3_info=[]), []

    monkeypatch.setattr(pre_push_review, "call_review", _call_review)

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

    monkeypatch.setenv("PRE_PUSH_REVIEW_MODEL", "claude-sonnet-4-6")
    rc_override = pre_push_review.main(
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

    assert rc == 0
    assert rc_override == 0
    assert models == ["claude-haiku-4-5", "claude-sonnet-4-6"]


def test_usage_log_is_written_to_artifact(
    monkeypatch, tmp_path: Path
) -> None:
    changed_path = tmp_path / "backend" / "tests" / "test_migration.py"
    changed_path.parent.mkdir(parents=True)
    changed_path.write_text("def test_stub():\n    assert True\n", encoding="utf-8")

    monkeypatch.setattr(pre_push_review, "build_cached_system_blocks", lambda _repo_root: [])
    monkeypatch.setattr(pre_push_review, "build_user_payload", lambda **_kwargs: "payload")

    def _call_review(**kwargs):
        kwargs["usage_log"].append(
            {
                "iteration": 0,
                "input_tokens": 100,
                "cache_creation_input_tokens": 20,
                "cache_read_input_tokens": 80,
                "output_tokens": 10,
            }
        )
        return ReviewReport(summary="clean", p1_blocking=[], p2_warn=[], p3_info=[]), []

    monkeypatch.setattr(pre_push_review, "call_review", _call_review)

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

    artifact_path = tmp_path / ".cache" / "dispatch_review" / "test-branch-deadbeef1234.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["usage_by_turn"] == [
        {
            "iteration": 0,
            "input_tokens": 100,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 80,
            "output_tokens": 10,
        }
    ]


def test_prompt_cache_can_be_disabled_by_env(monkeypatch, tmp_path: Path) -> None:
    governance_path = tmp_path / "docs" / "governance.md"
    rule_sheet_path = tmp_path / "docs" / "audit-protocol" / "dispatch-review-rules.md"
    governance_path.parent.mkdir(parents=True)
    rule_sheet_path.parent.mkdir(parents=True)
    governance_path.write_text("# Governance\n", encoding="utf-8")
    rule_sheet_path.write_text("# Rules\n", encoding="utf-8")

    enabled_blocks = build_cached_system_blocks(tmp_path)
    monkeypatch.setenv("PRE_PUSH_REVIEW_PROMPT_CACHE", "0")
    disabled_blocks = build_cached_system_blocks(tmp_path)

    assert "cache_control" in enabled_blocks[0]
    assert "cache_control" not in disabled_blocks[0]
    assert "cache_control" not in disabled_blocks[1]
    assert "cache_control" not in disabled_blocks[2]


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


def test_p1_blocking_report_warns_by_default_and_writes_artifact(
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
    assert rc == 0
    assert "P1 finding(s) found but push proceeds" in captured.out
    assert artifact_path.is_file()
    assert payload["p1_blocking"][0]["rule"] == "Tipo-I-fact-mismatch"
    assert payload["tool_calls"] == [{"name": "read_file", "ok": True}]


def test_p1_blocking_report_blocks_when_required(
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

    monkeypatch.setenv("PRE_PUSH_REVIEW_REQUIRED", "1")
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
    assert rc == 1
    assert "P1 finding(s) -push blocked" in captured.out
