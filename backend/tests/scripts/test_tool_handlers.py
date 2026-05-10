"""Mechanical coverage for pre-push hook v2 investigation tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dispatch_review import client as review_client
from dispatch_review.schema import ReviewReport
from dispatch_review.tool_handlers import (
    _MAX_BYTES_PER_READ,
    handle_find_symbol,
    handle_grep_pattern,
    handle_read_file,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _minimal_report_input(*, p1: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "summary": "stub summary",
        "p1_blocking": p1 or [],
        "p2_warn": [],
        "p3_info": [],
    }


def _finding() -> dict[str, str]:
    return {
        "rule": "Tipo I",
        "section": "§3",
        "snippet": "missing identifier",
        "why": "verified mismatch",
        "fix_suggestion": "fix identifier",
    }


@dataclass
class _ToolUse:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


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


def _response(block: _ToolUse, *, output_tokens: int = 10) -> Any:
    return SimpleNamespace(
        content=[block],
        stop_reason="tool_use",
        usage=SimpleNamespace(output_tokens=output_tokens),
    )


def test_handle_read_file_returns_excerpt(tmp_path: Path) -> None:
    _write(tmp_path / "sample.py", "one\ntwo\nthree\n")

    result = handle_read_file(
        {"path": "sample.py", "start_line": 2, "end_line": 3},
        repo_root=tmp_path,
    )

    assert result["ok"] is True
    assert result["excerpt"] == "two\nthree"
    assert result["total_lines"] == 3


def test_handle_read_file_caps_at_500_lines(tmp_path: Path) -> None:
    _write(tmp_path / "many.py", "\n".join(f"line {i}" for i in range(1, 1001)))

    result = handle_read_file({"path": "many.py"}, repo_root=tmp_path)

    assert result["ok"] is True
    assert len(result["excerpt"].splitlines()) <= 500
    assert result["end_line"] == 500


def test_handle_read_file_rejects_secret_bearing_path_dotenv(tmp_path: Path) -> None:
    _write(tmp_path / ".env", "ANTHROPIC_API_KEY=sk-fake-test-key")

    result = handle_read_file({"path": ".env"}, repo_root=tmp_path)

    assert result["ok"] is False
    assert "secret-bearing denylist" in result["error"]
    assert "sk-fake-test-key" not in str(result)


def test_handle_read_file_rejects_secret_bearing_path_env_local(tmp_path: Path) -> None:
    _write(tmp_path / ".env.local", "ANTHROPIC_API_KEY=sk-fake-test-key")

    result = handle_read_file({"path": ".env.local"}, repo_root=tmp_path)

    assert result["ok"] is False
    assert "secret-bearing denylist" in result["error"]
    assert "sk-fake-test-key" not in str(result)


def test_handle_read_file_rejects_oversized_file(tmp_path: Path) -> None:
    _write(tmp_path / "huge.py", "x" * (3 * 1024 * 1024))

    result = handle_read_file({"path": "huge.py"}, repo_root=tmp_path)

    assert result["ok"] is False
    assert "likely a generated artifact" in result["error"]


def test_handle_read_file_caps_excerpt_at_byte_limit(tmp_path: Path) -> None:
    _write(tmp_path / "long_line.py", "x" * 100_000)

    result = handle_read_file({"path": "long_line.py"}, repo_root=tmp_path)

    assert result["ok"] is True
    assert result["excerpt_truncated"] is True
    assert len(result["excerpt"]) <= _MAX_BYTES_PER_READ


def test_handle_read_file_rejects_path_traversal(tmp_path: Path) -> None:
    result = handle_read_file({"path": "../../etc/passwd"}, repo_root=tmp_path)

    assert result["ok"] is False
    assert "outside repo root" in result["error"]


def test_handle_read_file_rejects_sibling_prefix_escape(tmp_path: Path) -> None:
    parent = tmp_path
    repo_root = parent / "HEDGE-CONTROL-NEW"
    secrets = parent / "HEDGE-CONTROL-NEW-secrets"
    _write(repo_root / "README.md", "repo")
    _write(secrets / "leak.txt", "secret")

    result = handle_read_file(
        {"path": "../HEDGE-CONTROL-NEW-secrets/leak.txt"},
        repo_root=repo_root,
    )

    assert result["ok"] is False
    assert "outside repo root" in result["error"]


def test_handle_grep_pattern_rejects_outside_repo_search_path(tmp_path: Path) -> None:
    result = handle_grep_pattern(
        {"pattern": "anything", "search_path": "../"},
        repo_root=tmp_path,
    )

    assert result["ok"] is False
    assert result["matches"] == []
    assert result["searched_count"] == 0
    assert result["inspected_files"] == 0
    assert "no requested search root could be inspected" in result["error"]


def test_handle_grep_pattern_returns_ok_false_when_all_files_skipped(tmp_path: Path) -> None:
    root = tmp_path / "backend" / "app"
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    _write(outside, "needle = True\n")
    root.mkdir(parents=True)
    (root / "leaked.py").symlink_to(outside)
    _write(root / ".env", "ANTHROPIC_API_KEY=sk-fake")

    result = handle_grep_pattern(
        {"pattern": "needle", "search_path": "backend/app"},
        repo_root=tmp_path,
    )

    assert result["ok"] is False
    assert result["searched_count"] == 1
    assert result["inspected_files"] == 0
    assert "all candidate files" in result["error"]
    assert "were skipped" in result["error"]


def test_handle_grep_pattern_skips_oversized_file(tmp_path: Path) -> None:
    root = tmp_path / "backend" / "app"
    _write(root / "legitimate.py", "target = True\n")
    _write(root / "huge.py", "target = True\n" + ("x" * (3 * 1024 * 1024)))

    result = handle_grep_pattern(
        {"pattern": "target", "search_path": "backend/app"},
        repo_root=tmp_path,
    )

    assert result["ok"] is True
    assert [match["file"] for match in result["matches"]] == [
        "backend/app/legitimate.py"
    ]
    assert result["inspected_files"] == 1


def test_handle_grep_pattern_truncates_first_match_on_byte_cap_overflow(tmp_path: Path) -> None:
    root = tmp_path / "backend" / "app"
    _write(root / "long_match.py", "needle " + ("x" * 30_000))

    result = handle_grep_pattern(
        {"pattern": "needle", "search_path": "backend/app", "context_lines": 0},
        repo_root=tmp_path,
    )

    assert result["ok"] is True
    assert len(result["matches"]) == 1
    assert result["matches"][0]["excerpt"].endswith("# ...[truncated]")
    assert result["truncated"] is True


def test_handle_read_file_rejects_out_of_range_start_line(tmp_path: Path) -> None:
    _write(tmp_path / "short.py", "\n".join(str(i) for i in range(10)))

    result = handle_read_file(
        {"path": "short.py", "start_line": 20},
        repo_root=tmp_path,
    )

    assert result["ok"] is False
    assert "past EOF" in result["error"]


def test_handle_read_file_rejects_inverted_end_line(tmp_path: Path) -> None:
    _write(tmp_path / "short.py", "\n".join(str(i) for i in range(10)))

    result = handle_read_file(
        {"path": "short.py", "start_line": 5, "end_line": 3},
        repo_root=tmp_path,
    )

    assert result["ok"] is False
    assert "end_line=3 < start_line=5" in result["error"]


def test_handle_read_file_accepts_empty_file_at_line_1(tmp_path: Path) -> None:
    _write(tmp_path / "empty.py", "")

    result = handle_read_file({"path": "empty.py"}, repo_root=tmp_path)

    assert result["ok"] is True
    assert result["excerpt"] == ""
    assert result["total_lines"] == 0


def test_handle_grep_pattern_skips_symlink_outside_repo(tmp_path: Path) -> None:
    root = tmp_path / "backend" / "app"
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    _write(root / "legitimate.py", "needle = 'inside'\n")
    _write(outside, "needle = 'outside'\n")
    (root / "leaked.py").symlink_to(outside)

    result = handle_grep_pattern(
        {"pattern": "needle", "search_path": "backend/app"},
        repo_root=tmp_path,
    )

    assert result["ok"] is True
    assert [match["file"] for match in result["matches"]] == [
        "backend/app/legitimate.py"
    ]


def test_call_review_rejects_unverified_p1_on_turn_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "evidence.py", "class Evidence:\n    pass\n")
    responses = [
        _response(_ToolUse("report-1", "report_findings", _minimal_report_input(p1=[_finding()]))),
        _response(_ToolUse("read-1", "read_file", {"path": "evidence.py"})),
        _response(_ToolUse("report-2", "report_findings", _minimal_report_input(p1=[_finding()]))),
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(review_client, "Anthropic", lambda: _FakeAnthropic(responses))

    report, tool_log = review_client.call_review(
        model="claude-sonnet-4-6",
        cached_system_blocks=[],
        user_payload="payload",
        repo_root=tmp_path,
    )

    assert isinstance(report, ReviewReport)
    assert len(report.p1_blocking) == 1
    assert len(tool_log) == 1
    assert tool_log[0]["ok"] is True
    assert _FakeAnthropic.last_messages is not None
    calls = _FakeAnthropic.last_messages.calls
    assert len(calls) == 3
    assert "no investigation tool returned ok=True" in calls[1]["messages"][-1]["content"][0]["content"]


def test_call_review_accepts_clean_p1_empty_report_on_turn_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = [_response(_ToolUse("report-1", "report_findings", _minimal_report_input()))]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(review_client, "Anthropic", lambda: _FakeAnthropic(responses))

    report, tool_log = review_client.call_review(
        model="claude-sonnet-4-6",
        cached_system_blocks=[],
        user_payload="payload",
        repo_root=tmp_path,
    )

    assert report.p1_blocking == []
    assert tool_log == []
    assert _FakeAnthropic.last_messages is not None
    assert len(_FakeAnthropic.last_messages.calls) == 1


def test_call_review_rejects_p1_with_only_failed_investigations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "evidence.py", "x = 1\n")
    responses = [
        _response(_ToolUse("read-bad", "read_file", {"path": "missing.py"})),
        _response(_ToolUse("symbol-bad", "find_symbol", {"name": "not a thing!"})),
        _response(_ToolUse("report-1", "report_findings", _minimal_report_input(p1=[_finding()]))),
        _response(_ToolUse("read-good", "read_file", {"path": "evidence.py"})),
        _response(_ToolUse("report-2", "report_findings", _minimal_report_input(p1=[_finding()]))),
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
    assert [entry["ok"] for entry in tool_log] == [False, False, True]
    assert _FakeAnthropic.last_messages is not None
    assert len(_FakeAnthropic.last_messages.calls) == 5


def test_handle_read_file_returns_error_on_missing(tmp_path: Path) -> None:
    result = handle_read_file({"path": "missing.py"}, repo_root=tmp_path)

    assert result["ok"] is False
    assert "not a file" in result["error"]


def test_handle_find_symbol_locates_class_definition(tmp_path: Path) -> None:
    _write(tmp_path / "backend" / "app" / "models.py", "class Foo:\n    pass\n")

    result = handle_find_symbol({"name": "Foo"}, repo_root=tmp_path)

    assert result["ok"] is True
    assert result["matches"][0]["file"] == "backend/app/models.py"
    assert result["matches"][0]["line"] == 1


def test_handle_find_symbol_locates_async_function_definition(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend" / "app" / "routes.py",
        "async def cancel_rfq(rfq_id: str):\n    return None\n",
    )

    result = handle_find_symbol({"name": "cancel_rfq"}, repo_root=tmp_path)

    assert result["ok"] is True
    assert result["matches"][0]["line"] == 1


def test_handle_find_symbol_locates_indented_method_definition(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend" / "app" / "service.py",
        "class DealEngine:\n    def create_deal(self):\n        return None\n",
    )

    result = handle_find_symbol({"name": "create_deal"}, repo_root=tmp_path)

    assert result["ok"] is True
    assert result["matches"][0]["line"] == 2


def test_handle_find_symbol_rejects_invalid_identifier(tmp_path: Path) -> None:
    result = handle_find_symbol({"name": "not a thing!"}, repo_root=tmp_path)

    assert result["ok"] is False
    assert "invalid Python identifier" in result["error"]


def test_handle_grep_pattern_returns_matches_with_context(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend" / "app" / "module.py",
        "before\nneedle = True\nafter\n",
    )

    result = handle_grep_pattern(
        {"pattern": "needle", "search_path": "backend/app", "context_lines": 1},
        repo_root=tmp_path,
    )

    assert result["ok"] is True
    assert result["matches"][0]["file"] == "backend/app/module.py"
    assert "1: before" in result["matches"][0]["excerpt"]
    assert "2: needle = True" in result["matches"][0]["excerpt"]
    assert "3: after" in result["matches"][0]["excerpt"]


def test_handle_grep_pattern_truncates_at_80_results(tmp_path: Path) -> None:
    lines = "\n".join(f"needle_{i} = True" for i in range(200))
    _write(tmp_path / "backend" / "app" / "many.py", lines)

    result = handle_grep_pattern(
        {"pattern": "needle_", "search_path": "backend/app"},
        repo_root=tmp_path,
    )

    assert result["ok"] is True
    assert result["truncated"] is True
    assert len(result["matches"]) <= 80
