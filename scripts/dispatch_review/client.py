"""Anthropic API call with retry/backoff and forced tool-use output."""

from __future__ import annotations

import os
import time
from typing import Any

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)

from .schema import ReviewReport, build_report_findings_tool

_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 4.0


def call_review(
    *,
    model: str,
    cached_system_blocks: list[dict[str, Any]],
    user_payload: str,
    max_tokens: int = 8192,
) -> ReviewReport:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Configure it in your environment "
            "(e.g. via the repo .env loaded before invoking the hook)."
        )

    client = Anthropic()
    tool = build_report_findings_tool()

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=cached_system_blocks,
                tools=[tool],
                tool_choice={"type": "tool", "name": "report_findings"},
                messages=[{"role": "user", "content": user_payload}],
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
        else:
            for block in response.content:
                if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "report_findings":
                    return ReviewReport.model_validate(block.input)
            raise RuntimeError(
                "Model response did not contain a `report_findings` tool_use block. "
                f"stop_reason={response.stop_reason!r}, content_types={[getattr(b, 'type', None) for b in response.content]}"
            )

    assert last_exc is not None
    raise RuntimeError(
        f"Anthropic API call failed after {_MAX_RETRIES} attempts: {type(last_exc).__name__}: {last_exc}"
    ) from last_exc
