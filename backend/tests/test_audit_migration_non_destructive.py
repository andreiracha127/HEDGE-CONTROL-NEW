"""J-A5-04 — audit_events migration downgrade is non-destructive.

The Phase A5 jury verdict found that revision
``015_phase7_audit_events_table.py`` destroyed append-only audit history
on downgrade by calling ``op.drop_table("audit_events")``. Audit
history is institutional evidence; losing it on any rollback path —
even a deliberate one — violates the append-only invariant.

This regression locks the downgrade body to a non-destructive shape:

* no ``op.drop_table("audit_events")``;
* no SQL ``DROP TABLE audit_events`` or ``TRUNCATE``/``DELETE FROM``;
* no removal of the append-only enforcement triggers.

The chosen policy is "downgrade past this revision is a deliberate
no-op; operators must archive and drop by hand if they truly need it".
The test enforces that contract at the source level so future edits
cannot regress without tripping CI.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "015_phase7_audit_events_table.py"
)


def _migration_source() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _downgrade_function() -> ast.FunctionDef:
    tree = ast.parse(_migration_source(), filename=str(MIGRATION_PATH))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            return node
    pytest.fail("downgrade() function not found in migration 015")


def test_downgrade_does_not_drop_audit_events_table() -> None:
    func = _downgrade_function()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            callee = node.func
            attr = None
            if isinstance(callee, ast.Attribute):
                attr = callee.attr
            elif isinstance(callee, ast.Name):
                attr = callee.id
            if attr == "drop_table":
                first_arg = node.args[0] if node.args else None
                # Be conservative — fail on ANY drop_table call inside this
                # downgrade, since the table being dropped is unambiguously
                # audit_events.
                if isinstance(first_arg, ast.Constant) and first_arg.value == "audit_events":
                    pytest.fail(
                        "downgrade() must not drop audit_events — append-only "
                        "audit history is institutional evidence."
                    )
                pytest.fail(
                    "downgrade() must not call op.drop_table() in migration 015 — "
                    "this revision exists only to create audit_events, so any "
                    "drop_table() here would either remove audit_events itself "
                    "or a sibling object that was never introduced."
                )


def test_downgrade_does_not_emit_destructive_sql() -> None:
    """Defense-in-depth: catch raw SQL strings that would delete audit data
    even if op.drop_table() were not used."""
    source = _migration_source()
    func = _downgrade_function()
    # Only inspect the downgrade body, not the upgrade body.
    start = func.lineno - 1
    end = func.end_lineno or len(source.splitlines())
    body = "\n".join(source.splitlines()[start:end]).lower()
    for forbidden in ("drop table audit_events", "delete from audit_events", "truncate audit_events"):
        assert forbidden not in body, (
            f"downgrade() must not contain destructive SQL fragment {forbidden!r}"
        )


def test_downgrade_preserves_append_only_triggers() -> None:
    """The append-only triggers/functions defined in upgrade() must remain
    in place after downgrade — they ARE the invariant that prevents
    accidental row deletion, and they must outlive a schema rollback."""
    func = _downgrade_function()
    body = ast.get_source_segment(_migration_source(), func) or ""
    body_lower = body.lower()
    for forbidden in (
        "drop trigger if exists audit_events_no_update",
        "drop trigger if exists audit_events_no_delete",
        "drop trigger if exists audit_events_no_update_delete",
        "drop function if exists audit_events_no_update_delete",
    ):
        assert forbidden not in body_lower, (
            f"downgrade() must not drop append-only enforcement object: {forbidden!r}"
        )
