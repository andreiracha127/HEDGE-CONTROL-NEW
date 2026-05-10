"""Focused coverage for dispatch-review report parsing."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import pre_push_review
from dispatch_review import client as review_client


def _finding() -> dict[str, str]:
    return {
        "rule": "Tipo I",
        "section": "§3",
        "snippet": "missing identifier",
        "why": "verified mismatch",
        "fix_suggestion": "fix identifier",
    }


def _report_input(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": "stub summary",
        "p1_blocking": [],
        "p2_warn": [],
        "p3_info": [],
    }
    payload.update(overrides)
    return payload


class _ToolUse:
    def __init__(self, name: str, input: dict[str, Any], tool_use_id: str) -> None:
        self.type = "tool_use"
        self.name = name
        self.input = input
        self.id = tool_use_id


class _FakeMessages:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        if not self.responses:
            raise AssertionError("unexpected messages.create call")
        return self.responses.pop(0)


class _FakeAnthropic:
    last_messages: _FakeMessages | None = None

    def __init__(self, responses: list[Any]) -> None:
        self.messages = _FakeMessages(responses)
        _FakeAnthropic.last_messages = self.messages


def _response(block: _ToolUse) -> Any:
    return SimpleNamespace(
        content=[block],
        stop_reason="tool_use",
        usage=SimpleNamespace(output_tokens=10),
    )


def test_coerce_list_fields_accepts_p2_warn_json_string_list() -> None:
    payload = _report_input(p2_warn=json.dumps([_finding()]))

    normalized = review_client._coerce_list_fields(payload)

    assert normalized["p2_warn"] == [_finding()]


def test_call_review_accepts_p1_blocking_json_string_and_preserves_blocking_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "evidence.py").write_text("class Evidence:\n    pass\n", encoding="utf-8")
    responses = [
        _response(_ToolUse("read_file", {"path": "evidence.py"}, "read-1")),
        _response(
            _ToolUse(
                "report_findings",
                _report_input(p1_blocking=json.dumps([_finding()])),
                "report-1",
            )
        ),
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(review_client, "Anthropic", lambda: _FakeAnthropic(responses))

    report, _tool_log = review_client.call_review(
        model="claude-sonnet-4-6",
        cached_system_blocks=[],
        user_payload="payload",
        repo_root=tmp_path,
    )

    assert len(report.p1_blocking) == 1


def test_call_review_demotes_self_refuting_p1_from_fix_suggestion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    finding = _finding()
    finding["why"] = "The cited dispatch section is internally consistent."
    finding["fix_suggestion"] = "No change needed; remove this from P1."
    responses = [
        _response(_ToolUse("report_findings", _report_input(p1_blocking=[finding]), "report-1")),
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(review_client, "Anthropic", lambda: _FakeAnthropic(responses))

    report, tool_log = review_client.call_review(
        model="claude-sonnet-4-6",
        cached_system_blocks=[],
        user_payload="payload",
        repo_root=tmp_path,
    )

    assert report.p1_blocking == []
    assert len(report.p2_warn) == 1
    assert report.p2_warn[0].rule == "Demoted-P1-self-refuting: Tipo I"
    assert report.p2_warn[0].fix_suggestion.startswith(
        "[demoted from P1: self-refuting fix_suggestion]"
    )
    assert tool_log == []


def test_call_review_preserves_real_p1_with_no_change_text_when_protected_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "migration.py").write_text("revision = 'abc'\n", encoding="utf-8")
    finding = _finding()
    finding["why"] = "Migration blocker: schema mismatch leaves the ledger table invalid."
    finding["fix_suggestion"] = "No change needed is incorrect; add the migration fix."
    responses = [
        _response(_ToolUse("read_file", {"path": "migration.py"}, "read-1")),
        _response(_ToolUse("report_findings", _report_input(p1_blocking=[finding]), "report-1")),
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(review_client, "Anthropic", lambda: _FakeAnthropic(responses))

    report, tool_log = review_client.call_review(
        model="claude-sonnet-4-6",
        cached_system_blocks=[],
        user_payload="payload",
        repo_root=tmp_path,
    )

    assert len(report.p1_blocking) == 1
    assert report.p2_warn == []
    assert len(tool_log) == 1


def test_call_review_does_not_demote_when_self_refuting_text_is_only_in_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "evidence.py").write_text("class Evidence:\n    pass\n", encoding="utf-8")
    finding = _finding()
    finding["why"] = "No blocking issue was proven by this sentence alone."
    finding["fix_suggestion"] = "Fix the missing concrete-code identifier."
    responses = [
        _response(_ToolUse("read_file", {"path": "evidence.py"}, "read-1")),
        _response(_ToolUse("report_findings", _report_input(p1_blocking=[finding]), "report-1")),
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(review_client, "Anthropic", lambda: _FakeAnthropic(responses))

    report, tool_log = review_client.call_review(
        model="claude-sonnet-4-6",
        cached_system_blocks=[],
        user_payload="payload",
        repo_root=tmp_path,
    )

    assert len(report.p1_blocking) == 1
    assert report.p2_warn == []
    assert len(tool_log) == 1


def test_call_review_mixed_self_refuting_and_real_p1_still_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "evidence.py").write_text("class Evidence:\n    pass\n", encoding="utf-8")
    self_refuting = _finding()
    self_refuting["fix_suggestion"] = "No blocking issue; no change needed."
    real = _finding()
    real["rule"] = "Tipo-II-governance"
    real["why"] = "Governance violation: dispatch contradicts the mandatory fail-closed rule."
    real["fix_suggestion"] = "Remove the contradictory acceptance criterion."
    responses = [
        _response(_ToolUse("read_file", {"path": "evidence.py"}, "read-1")),
        _response(
            _ToolUse(
                "report_findings",
                _report_input(p1_blocking=[self_refuting, real]),
                "report-1",
            )
        ),
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(review_client, "Anthropic", lambda: _FakeAnthropic(responses))

    report, tool_log = review_client.call_review(
        model="claude-sonnet-4-6",
        cached_system_blocks=[],
        user_payload="payload",
        repo_root=tmp_path,
    )

    assert [finding.rule for finding in report.p1_blocking] == ["Tipo-II-governance"]
    assert len(report.p2_warn) == 1
    assert report.p2_warn[0].rule == "Demoted-P1-self-refuting: Tipo I"
    assert len(tool_log) == 1


def test_call_review_repairs_missing_summary_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid_report = _report_input()
    invalid_report.pop("summary")
    responses = [
        _response(_ToolUse("report_findings", invalid_report, "report-1")),
        _response(_ToolUse("report_findings", _report_input(), "report-2")),
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(review_client, "Anthropic", lambda: _FakeAnthropic(responses))

    report, tool_log = review_client.call_review(
        model="claude-sonnet-4-6",
        cached_system_blocks=[],
        user_payload="payload",
        repo_root=tmp_path,
    )

    assert report.summary == "stub summary"
    assert tool_log == []
    assert _FakeAnthropic.last_messages is not None
    calls = _FakeAnthropic.last_messages.calls
    assert len(calls) == 2
    repair_content = calls[1]["messages"][-1]["content"][0]["content"]
    assert "ReviewReport payload is invalid" in repair_content
    assert "summary" in repair_content


def test_call_review_repairs_invalid_p1_finding_and_still_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "evidence.py").write_text("class Evidence:\n    pass\n", encoding="utf-8")
    invalid_finding = _finding()
    invalid_finding.pop("why")
    responses = [
        _response(_ToolUse("read_file", {"path": "evidence.py"}, "read-1")),
        _response(_ToolUse("report_findings", _report_input(p1_blocking=[invalid_finding]), "report-1")),
        _response(_ToolUse("report_findings", _report_input(p1_blocking=[_finding()]), "report-2")),
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(review_client, "Anthropic", lambda: _FakeAnthropic(responses))

    report, tool_log = review_client.call_review(
        model="claude-sonnet-4-6",
        cached_system_blocks=[],
        user_payload="payload",
        repo_root=tmp_path,
    )

    assert len(report.p1_blocking) == 1
    assert len(tool_log) == 1
    assert _FakeAnthropic.last_messages is not None
    calls = _FakeAnthropic.last_messages.calls
    assert len(calls) == 3
    repair_content = calls[2]["messages"][-1]["content"][0]["content"]
    assert "p1_blocking.0.why" in repair_content


def test_call_review_fails_after_second_invalid_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid_report = _report_input()
    invalid_report.pop("summary")
    responses = [
        _response(_ToolUse("report_findings", invalid_report, "report-1")),
        _response(_ToolUse("report_findings", invalid_report, "report-2")),
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(review_client, "Anthropic", lambda: _FakeAnthropic(responses))

    with pytest.raises(review_client.ReviewReportParseError) as exc_info:
        review_client.call_review(
            model="claude-sonnet-4-6",
            cached_system_blocks=[],
            user_payload="payload",
            repo_root=tmp_path,
        )

    assert "summary" in str(exc_info.value)
    assert exc_info.value.raw_report_input == invalid_report
    assert _FakeAnthropic.last_messages is not None
    assert len(_FakeAnthropic.last_messages.calls) == 2


def test_coerce_list_fields_normalizes_empty_string_to_empty_p3_info() -> None:
    payload = _report_input(p3_info="")

    normalized = review_client._coerce_list_fields(payload)

    assert normalized["p3_info"] == []


def test_coerce_list_fields_keeps_native_lists_unchanged() -> None:
    native_p2 = [_finding()]
    payload = _report_input(p2_warn=native_p2, tool_calls=[])

    normalized = review_client._coerce_list_fields(payload)

    assert normalized["p2_warn"] is native_p2
    assert normalized["tool_calls"] == []


def test_coerce_list_fields_rejects_malformed_json_string_with_controlled_error() -> None:
    payload = _report_input(p2_warn='[{"rule": "Tipo I"}')

    with pytest.raises(review_client.ReviewReportParseError) as exc_info:
        review_client._coerce_list_fields(payload)

    assert "p2_warn" in str(exc_info.value)
    assert "JSON list" in str(exc_info.value)


def test_pre_push_review_parse_error_writes_artifact_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dispatch_path = tmp_path / "dispatch.md"
    dispatch_path.write_text("# Dispatch\n", encoding="utf-8")
    raw_input = _report_input(p2_warn="not-json")
    parse_error = review_client.ReviewReportParseError(
        "invalid ReviewReport list field p2_warn: expected JSON list",
        raw_report_input=raw_input,
        tool_calls=[{"name": "read_file", "ok": True}],
    )
    monkeypatch.setattr(pre_push_review, "build_cached_system_blocks", lambda _repo_root: [])
    monkeypatch.setattr(
        pre_push_review,
        "build_user_payload",
        lambda **_kwargs: "payload",
    )
    monkeypatch.setattr(pre_push_review, "call_review", lambda **_kwargs: (_ for _ in ()).throw(parse_error))

    rc = pre_push_review.main(
        [
            "--dispatch-paths",
            str(dispatch_path),
            "--branch",
            "test-branch",
            "--head-sha",
            "deadbeef123456",
            "--repo-root",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    artifact_path = tmp_path / ".cache" / "dispatch_review" / "test-branch-deadbeef1234.parse-error.json"
    assert rc == 1
    assert "review report parse failed" in captured.err
    assert "p2_warn" in captured.err
    assert "Traceback" not in captured.err
    assert f"artifact written: {artifact_path.relative_to(tmp_path)}" in captured.err
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["error"]["message"] == str(parse_error)
    assert payload["raw_report_input"] == raw_input
    assert payload["tool_calls"] == [{"name": "read_file", "ok": True}]
