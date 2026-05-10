"""Anthropic tool definitions for the multi-turn dispatch review."""

from __future__ import annotations

from typing import Any

READ_FILE_TOOL: dict[str, Any] = {
    "name": "read_file",
    "description": (
        "Read a file in the repo (read-only). Use this to verify identifier "
        "definitions, schema field names, line numbers, or concrete code "
        "prescriptions against the actual codebase. Returns up to 500 lines per call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to repo root.",
            },
            "start_line": {
                "type": "integer",
                "minimum": 1,
                "description": "1-indexed start line. Default 1.",
            },
            "end_line": {
                "type": "integer",
                "minimum": 1,
                "description": "1-indexed inclusive end line. Default = start_line + 499.",
            },
        },
        "required": ["path"],
    },
}

FIND_SYMBOL_TOOL: dict[str, Any] = {
    "name": "find_symbol",
    "description": (
        "Find where a Python class, function, method, or module-level constant "
        "is defined. Searches backend/app/, backend/tests/, scripts/."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The Python identifier to locate.",
            },
        },
        "required": ["name"],
    },
}

GREP_PATTERN_TOOL: dict[str, Any] = {
    "name": "grep_pattern",
    "description": (
        "Search for a Python regex pattern within a directory or file. Returns "
        "up to 80 matches with file:line and context excerpt."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python re-compatible regex."},
            "search_path": {
                "type": "string",
                "description": (
                    "Directory or exact file path under repo root. No glob syntax. "
                    "Default 'backend/app'."
                ),
            },
            "context_lines": {
                "type": "integer",
                "minimum": 0,
                "maximum": 20,
                "description": "Lines of surrounding context. Default 0.",
            },
        },
        "required": ["pattern"],
    },
}


def build_review_tools() -> list[dict[str, Any]]:
    """Return investigation tools plus the report_findings termination tool."""
    from .schema import build_report_findings_tool

    return [
        READ_FILE_TOOL,
        FIND_SYMBOL_TOOL,
        GREP_PATTERN_TOOL,
        build_report_findings_tool(),
    ]
