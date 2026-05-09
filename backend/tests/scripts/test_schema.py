"""Tests for ``scripts/dispatch_review/schema.py``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dispatch_review.schema import Finding, ReviewReport, build_report_findings_tool


def test_review_report_validates_well_formed_payload() -> None:
    payload = {
        "p1_blocking": [
            {
                "rule": "Tipo-I-fact-mismatch",
                "section": "§3.7.5",
                "snippet": "result.contracts[<id>].price_quote.symbol",
                "why": "ScenarioWhatIfRunResponse exposes mtm_snapshot, not contracts.",
                "fix_suggestion": "Use mtm_snapshot[i].price_quote.symbol.",
            }
        ],
        "p2_warn": [],
        "p3_info": [],
        "summary": "One P1 fact mismatch in §7 test prescription.",
    }
    report = ReviewReport.model_validate(payload)
    assert len(report.p1_blocking) == 1
    assert isinstance(report.p1_blocking[0], Finding)
    assert report.p1_blocking[0].rule == "Tipo-I-fact-mismatch"


def test_review_report_rejects_missing_summary() -> None:
    payload = {"p1_blocking": [], "p2_warn": [], "p3_info": []}
    with pytest.raises(ValidationError):
        ReviewReport.model_validate(payload)


def test_report_findings_tool_schema_has_object_root() -> None:
    tool = build_report_findings_tool()
    assert tool["name"] == "report_findings"
    assert tool["input_schema"]["type"] == "object"
    assert "p1_blocking" in tool["input_schema"]["properties"]
    assert "p2_warn" in tool["input_schema"]["properties"]
    assert "p3_info" in tool["input_schema"]["properties"]
    assert "summary" in tool["input_schema"]["required"]
