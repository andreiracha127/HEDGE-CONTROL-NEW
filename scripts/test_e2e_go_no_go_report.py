"""Unit tests for the E2E go/no-go report generator."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().with_name("e2e_go_no_go_report.py")
_SPEC = importlib.util.spec_from_file_location("e2e_go_no_go_report", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
main = _MODULE.main


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_go_verdict_when_pytest_and_playwright_pass(tmp_path: Path) -> None:
    pytest_json = _write_json(tmp_path / "pytest.json", {"summary": {"failed": 0}})
    playwright_json = _write_json(
        tmp_path / "playwright.json",
        {"stats": {"unexpected": 0, "expected": 3}},
    )
    output = tmp_path / "go.md"
    assert main([
        "--pytest-json",
        str(pytest_json),
        "--playwright-json",
        str(playwright_json),
        "--output",
        str(output),
    ]) == 0
    assert "Verdict: GO" in output.read_text(encoding="utf-8")


def test_no_go_on_critical_failure(tmp_path: Path) -> None:
    pytest_json = _write_json(
        tmp_path / "pytest.json",
        {
            "summary": {"failed": 1},
            "tests": [{"nodeid": "tests/e2e/test_rbac_matrix.py::test_x", "outcome": "failed"}],
        },
    )
    playwright_json = _write_json(tmp_path / "playwright.json", {"stats": {"unexpected": 0}})
    output = tmp_path / "no.md"
    assert main([
        "--pytest-json",
        str(pytest_json),
        "--playwright-json",
        str(playwright_json),
        "--output",
        str(output),
    ]) == 1
    assert "Verdict: NO-GO" in output.read_text(encoding="utf-8")


def test_override_only_for_scenario_isolation_failures(tmp_path: Path) -> None:
    pytest_json = _write_json(
        tmp_path / "pytest.json",
        {
            "summary": {"failed": 1},
            "tests": [
                {
                    "nodeid": "tests/e2e/test_scenario_isolation.py::test_overrideable",
                    "outcome": "failed",
                }
            ],
        },
    )
    playwright_json = _write_json(tmp_path / "playwright.json", {"stats": {"unexpected": 0}})
    output = tmp_path / "override.md"
    assert main([
        "--pytest-json",
        str(pytest_json),
        "--playwright-json",
        str(playwright_json),
        "--output",
        str(output),
        "--override-rationale",
        "accepted temporary scenario isolation variance",
    ]) == 0
    report = output.read_text(encoding="utf-8")
    assert "Verdict: GO" in report
    assert "Override:" in report
