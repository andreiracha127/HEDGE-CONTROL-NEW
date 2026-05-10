"""Anthropic API call with retry/backoff and multi-turn tool use."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)
from pydantic import ValidationError

from .schema import ReviewReport
from .tool_handlers import HANDLERS
from .tools import build_review_tools


class ReviewReportParseError(RuntimeError):
    """Controlled failure for malformed report_findings payloads."""

    def __init__(
        self,
        message: str,
        *,
        raw_report_input: dict[str, Any] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.raw_report_input = raw_report_input
        self.tool_calls = tool_calls or []
        self.retryable = retryable


def _coerce_list_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Sonnet sometimes emits a list-typed finding field as a JSON-encoded string.

    Forced tool_use should produce typed structures, but in practice the
    model occasionally inlines an array as a string when the array is
    long. Be permissive on inbound shape: if a field expected to be a
    list arrives as a string that parses as JSON list, accept it. Empty
    strings, nulls, and missing fields normalize to [].
    """
    raw_payload = dict(payload)
    for key in ("p1_blocking", "p2_warn", "p3_info", "tool_calls"):
        value = payload.get(key)
        if value is None or value == "":
            payload[key] = []
            continue
        if not isinstance(value, str):
            continue
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            raise ReviewReportParseError(
                f"invalid ReviewReport list field {key}: expected JSON list string",
                raw_report_input=raw_payload,
            ) from None
        if not isinstance(parsed, list):
            raise ReviewReportParseError(
                f"invalid ReviewReport list field {key}: expected JSON list string",
                raw_report_input=raw_payload,
            )
        payload[key] = parsed
    return payload


def _parse_review_report(
    raw_input: dict[str, Any],
    *,
    tool_call_log: list[dict[str, Any]],
) -> ReviewReport:
    raw_payload = dict(raw_input)
    try:
        normalized = _coerce_list_fields(dict(raw_payload))
        return ReviewReport.model_validate(normalized)
    except ReviewReportParseError as exc:
        exc.raw_report_input = exc.raw_report_input or raw_payload
        exc.tool_calls = tool_call_log
        raise
    except ValidationError as exc:
        raise ReviewReportParseError(
            "invalid ReviewReport payload after list-field normalization: "
            f"{_format_validation_errors(exc)}",
            raw_report_input=raw_payload,
            tool_calls=tool_call_log,
            retryable=True,
        ) from None


def _format_validation_errors(exc: ValidationError) -> str:
    errors: list[str] = []
    for error in exc.errors(include_url=False):
        loc = ".".join(str(part) for part in error.get("loc", ())) or "<root>"
        errors.append(f"{loc}: {error.get('msg', 'invalid value')}")
    return "; ".join(errors)


def _build_report_repair_message(exc: ReviewReportParseError) -> str:
    return (
        f"ReviewReport payload is invalid: {exc}. Call `report_findings` again "
        "exactly once with a complete ReviewReport. Preserve every valid "
        "P1/P2/P3 finding from the invalid payload; fill missing fields from "
        "verified evidence; do not downgrade, bypass, or suppress findings."
    )


_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 4.0
_MAX_ITERATIONS = 12
_MAX_CUMULATIVE_OUTPUT_TOKENS = 60_000
_PER_TURN_MAX_TOKENS = 8192
_SOFT_TOOL_BUDGET = 8


def _summarize_for_log(result: dict[str, Any]) -> str:
    """Return a redaction-safe structural summary of a tool result."""
    ok = result.get("ok")
    keys = sorted(k for k in result if k != "ok")
    excerpt_chars = len(str(result.get("excerpt", "")))
    matches_count = len(result.get("matches") or [])
    truncated = result.get("truncated", result.get("excerpt_truncated", False))
    return (
        f"ok={ok} keys={keys} excerpt_chars={excerpt_chars} "
        f"matches_count={matches_count} truncated={truncated}"
    )


def _summarize_input_for_log(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """Return a redaction-safe summary of tool input."""
    sensitive_fields_by_tool = {"grep_pattern": {"pattern"}}
    sensitive_fields = sensitive_fields_by_tool.get(tool_name, set())
    safe: dict[str, Any] = {}
    for key, value in tool_input.items():
        if key in sensitive_fields:
            value_str = str(value)
            safe[key] = f"<redacted len={len(value_str)}>"
        else:
            safe[key] = value
    return safe


def _create_with_retry(
    client: Anthropic,
    *,
    model: str,
    max_tokens: int,
    cached_system_blocks: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
):
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=cached_system_blocks,
                tools=tools,
                tool_choice={"type": "any", "disable_parallel_tool_use": True},
                messages=messages,
            )
        except AuthenticationError:
            raise
        except (RateLimitError, APIConnectionError, APIStatusError) as exc:
            last_exc = exc
            if attempt == _MAX_RETRIES - 1:
                break
            sleep_for = _BACKOFF_BASE_SECONDS ** attempt
            time.sleep(sleep_for)
            continue

    assert last_exc is not None
    raise RuntimeError(
        f"Anthropic API call failed after {_MAX_RETRIES} attempts: "
        f"{type(last_exc).__name__}: {last_exc}"
    ) from last_exc


def _tool_budget_nudge(iteration: int, tool_call_log: list[dict[str, Any]]) -> str | None:
    """Return a concise convergence nudge for the next model turn."""
    successful_calls = sum(1 for entry in tool_call_log if entry.get("ok"))
    if iteration >= _MAX_ITERATIONS - 2:
        return (
            "Tool budget warning: the next assistant turn is the final allowed "
            "turn before the hard cap. Call `report_findings` now with your "
            "best verified ReviewReport unless the current tool result proves "
            "a single P1-critical unknown that cannot be classified without one "
            "more read."
        )
    if successful_calls >= _SOFT_TOOL_BUDGET:
        return (
            f"Tool budget guidance: {successful_calls} investigation tools have "
            "already returned ok=True. Stop broad exploration. If no single "
            "P1-critical unknown remains, call `report_findings` now."
        )
    return None


def call_review(
    *,
    model: str,
    cached_system_blocks: list[dict[str, Any]],
    user_payload: str,
    repo_root: Path,
) -> tuple[ReviewReport, list[dict[str, Any]]]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Configure it in your environment "
            "(e.g. via the repo .env loaded before invoking the hook)."
        )

    client = Anthropic()
    tools = build_review_tools()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_payload}]
    tool_call_log: list[dict[str, Any]] = []
    cumulative_output_tokens = 0
    report_repair_requested = False

    for iteration in range(_MAX_ITERATIONS):
        response = _create_with_retry(
            client,
            model=model,
            max_tokens=_PER_TURN_MAX_TOKENS,
            cached_system_blocks=cached_system_blocks,
            tools=tools,
            messages=messages,
        )
        output_tokens = int(getattr(getattr(response, "usage", None), "output_tokens", 0) or 0)
        cumulative_output_tokens += output_tokens
        if cumulative_output_tokens > _MAX_CUMULATIVE_OUTPUT_TOKENS:
            raise RuntimeError(
                f"cumulative output exceeded {_MAX_CUMULATIVE_OUTPUT_TOKENS} tokens; "
                "loop terminated to prevent runaway cost"
            )

        report_was_rejected = False
        report_was_present = False
        for block in response.content:
            if getattr(block, "type", None) != "tool_use" or getattr(block, "name", None) != "report_findings":
                continue
            report_was_present = True
            try:
                candidate_report = _parse_review_report(
                    dict(block.input),
                    tool_call_log=tool_call_log,
                )
            except ReviewReportParseError as exc:
                if exc.retryable and not report_repair_requested:
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": _build_report_repair_message(exc),
                                }
                            ],
                        }
                    )
                    report_repair_requested = True
                    report_was_rejected = True
                    break
                raise
            successful_investigations = sum(
                1
                for entry in tool_call_log
                if entry.get("ok") and entry.get("name") in HANDLERS
            )
            if candidate_report.p1_blocking and successful_investigations == 0:
                rejection = (
                    "Your report_findings call contains "
                    f"{len(candidate_report.p1_blocking)} P1 finding(s) but no "
                    "investigation tool returned ok=True this review. Tool failures "
                    "are absence of evidence, not proof. Use read_file, find_symbol, "
                    "or grep_pattern successfully before emitting P1 Tipo-I findings."
                )
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": rejection,
                            }
                        ],
                    }
                )
                report_was_rejected = True
                break
            return candidate_report, tool_call_log

        if report_was_rejected:
            continue
        if report_was_present:
            continue

        tool_results: list[dict[str, Any]] = []
        executed_any = False
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            executed_any = True
            tool_name = getattr(block, "name", "")
            tool_input = dict(getattr(block, "input", {}) or {})
            handler = HANDLERS.get(tool_name)
            if handler is None:
                result = {"ok": False, "error": f"unknown tool: {tool_name}"}
            else:
                try:
                    result = handler(tool_input, repo_root=repo_root)
                except Exception as exc:  # noqa: BLE001 - model needs structured failure
                    result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

            tool_call_log.append(
                {
                    "iteration": iteration,
                    "name": tool_name,
                    "input": _summarize_input_for_log(tool_name, tool_input),
                    "ok": bool(result.get("ok")),
                    "result_summary": _summarize_for_log(result),
                    "response_output_tokens": output_tokens,
                    "cumulative_output_tokens": cumulative_output_tokens,
                }
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        if not executed_any:
            raise RuntimeError(
                f"iteration {iteration}: model emitted no tool_use block and no report_findings; "
                f"stop_reason={getattr(response, 'stop_reason', None)!r}"
            )

        nudge = _tool_budget_nudge(iteration, tool_call_log)
        if nudge:
            tool_results.append({"type": "text", "text": nudge})

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"review did not converge after {_MAX_ITERATIONS} iterations")
