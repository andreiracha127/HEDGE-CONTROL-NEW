"""Pydantic schemas + Anthropic tool definition for the structured review report."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Finding(BaseModel):
    rule: str = Field(
        ...,
        description=(
            "The self-consistency sub-rule violated, e.g. "
            "'Tipo-I-fact-mismatch', 'Sibling-bullet-sweep-miss', "
            "'Concrete-code-identifier-verification'."
        ),
    )
    section: str = Field(
        ...,
        description=(
            "Dispatch section the violation lives in, e.g. '§3.7.5', '§6 acceptance', '§10 DO NOTs'."
        ),
    )
    snippet: str = Field(
        ...,
        max_length=1200,
        description="The exact dispatch excerpt that violates the rule.",
    )
    why: str = Field(
        ...,
        max_length=2500,
        description=(
            "Why this is wrong. Cite the file, symbol, or sibling bullet "
            "that contradicts the prescription."
        ),
    )
    fix_suggestion: str = Field(
        ...,
        max_length=2000,
        description="Concrete suggestion for resolving the catch.",
    )


class ReviewReport(BaseModel):
    p1_blocking: list[Finding] = Field(
        default_factory=list,
        description=(
            "Tier-1 blocking findings. Non-empty list halts the push. "
            "Reserved for: identifier doesn't exist (Tipo I), §3 contradicts "
            "§10 / §6 / §11 (Tipo II), governance §2.x violation."
        ),
    )
    p2_warn: list[Finding] = Field(
        default_factory=list,
        description=(
            "Tier-2 warnings. Printed but do not block. Reserved for: "
            "sibling-bullet sweep miss, missing concrete-code field "
            "enumeration, NULL-safety oversight, decimal-quantization "
            "boundary missing."
        ),
    )
    p3_info: list[Finding] = Field(
        default_factory=list,
        description=(
            "Informational. Stylistic inconsistencies or minor unverified "
            "claims that don't undermine the PR's purpose."
        ),
    )
    summary: str = Field(
        ...,
        max_length=2000,
        description=(
            "One-paragraph summary of the dispatch's overall self-consistency "
            "state. Mention key strengths and the most important catch if any."
        ),
    )


def build_report_findings_tool() -> dict[str, Any]:
    """Return the Anthropic tool definition forcing structured output.

    The Anthropic Messages API requires ``input_schema`` to have root
    ``type: "object"`` — which Pydantic ``model_json_schema()`` already
    produces for non-root-discriminated models.
    """
    schema = ReviewReport.model_json_schema()
    if schema.get("type") != "object":
        raise RuntimeError(
            "ReviewReport.model_json_schema() must produce a root-object schema; "
            f"got type={schema.get('type')!r}"
        )
    return {
        "name": "report_findings",
        "description": (
            "Report dispatch self-consistency review findings, partitioned "
            "into P1 (blocking), P2 (warning), P3 (info). Always call this "
            "tool exactly once with the full review report."
        ),
        "input_schema": schema,
    }
