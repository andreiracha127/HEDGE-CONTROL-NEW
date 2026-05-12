"""J-A5-04 — audit_events migration downgrade is non-destructive
and the upgrade path tolerates the preserved objects.

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


MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions"
)
MIGRATION_PATH = MIGRATIONS_DIR / "015_phase7_audit_events_table.py"
MIGRATION_043_PATH = MIGRATIONS_DIR / "043_a5_audit_payload_input.py"


def _migration_source() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _downgrade_function(path: Path = MIGRATION_PATH) -> ast.FunctionDef:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            return node
    pytest.fail(f"downgrade() function not found in {path.name}")


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


# ── Idempotent upgrade (Codex P2 on PR #61) ───────────────────────────────


def _load_migration_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "phase7_audit_events_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_then_downgrade_then_upgrade_is_idempotent(tmp_path) -> None:
    """Operator flow Codex flagged: ``alembic upgrade`` past 015, then
    ``alembic downgrade <pre-015>`` (no-op), then ``alembic upgrade head``
    again. With a bare CREATE TABLE/CREATE TRIGGER, the second upgrade
    would fail on duplicate objects and force the operator to drop the
    audit history the downgrade preserved. The upgrade body must
    therefore tolerate the preserved table and triggers."""
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    db_path = tmp_path / "audit.sqlite"
    engine = sa.create_engine(f"sqlite:///{db_path}", future=True)
    migration = _load_migration_module()

    def _run(callable_name: str) -> None:
        with engine.begin() as connection:
            ctx = MigrationContext.configure(connection)
            ops = Operations(ctx)
            # The migration uses the module-level ``op`` proxy; rebind it
            # to our ad-hoc Operations so we don't need a full alembic.ini.
            original_op = migration.op
            migration.op = ops
            try:
                getattr(migration, callable_name)()
            finally:
                migration.op = original_op

    # 1) Fresh upgrade — creates table + triggers.
    _run("upgrade")
    inspector = sa.inspect(engine)
    assert "audit_events" in inspector.get_table_names()

    # Seed a row so we can verify it survives the round-trip.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO audit_events (id, entity_type, entity_id, event_type, "
            "payload, checksum) VALUES ('00000000-0000-0000-0000-000000000001', "
            "'order', '00000000-0000-0000-0000-000000000002', 'created', "
            "'{}', 'deadbeef')"
        )

    # 2) Downgrade — must preserve table + row + triggers (no-op policy).
    _run("downgrade")
    inspector = sa.inspect(engine)
    assert "audit_events" in inspector.get_table_names()
    with engine.connect() as connection:
        count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM audit_events"
        ).scalar_one()
    assert count == 1

    # 3) Re-upgrade — must NOT raise on duplicate table/trigger.
    _run("upgrade")
    inspector = sa.inspect(engine)
    assert "audit_events" in inspector.get_table_names()
    with engine.connect() as connection:
        count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM audit_events"
        ).scalar_one()
    assert count == 1, "re-upgrade must not destroy preserved audit history"

    # 4) Append-only trigger must still fire after the round-trip.
    with engine.begin() as connection:
        with pytest.raises(Exception) as excinfo:
            connection.exec_driver_sql(
                "DELETE FROM audit_events WHERE id = "
                "'00000000-0000-0000-0000-000000000001'"
            )
        assert "append-only" in str(excinfo.value).lower()


# ── Migration 043 — payload_canonical preservation (Codex P2 follow-up) ───


def test_043_downgrade_does_not_drop_payload_canonical_column() -> None:
    """``payload_canonical`` stores the canonical JSON payload that
    ``AuditTrailService.verify_event`` needs to recompute the HMAC. A
    full rollback that drops this column would leave the preserved audit
    rows (per migration 015's no-op downgrade) without verification
    evidence, silently breaking the append-only invariant. Mirror the
    015 policy: 043's downgrade must not drop the column."""
    func = _downgrade_function(MIGRATION_043_PATH)
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            callee = node.func
            attr = callee.attr if isinstance(callee, ast.Attribute) else None
            name = callee.id if isinstance(callee, ast.Name) else None
            if attr == "drop_column" or name == "drop_column":
                pytest.fail(
                    "043 downgrade() must not drop audit_events.payload_canonical "
                    "— that column carries the canonical payload used for "
                    "audit signature verification (J-A5-04 extended)."
                )


def test_043_round_trip_preserves_payload_canonical_data(tmp_path) -> None:
    """Operator flow: upgrade(015) → upgrade(043) → seed row with
    payload_canonical → downgrade(043) → upgrade(043). The preserved
    column and the row's canonical payload must survive intact, and the
    re-upgrade must not raise on the existing column."""
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    db_path = tmp_path / "audit043.sqlite"
    engine = sa.create_engine(f"sqlite:///{db_path}", future=True)
    migration_015 = _load_migration_module()

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "phase_a5_audit_payload_input", MIGRATION_043_PATH
    )
    assert spec is not None and spec.loader is not None
    migration_043 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_043)

    def _run(module, callable_name: str) -> None:
        with engine.begin() as connection:
            ctx = MigrationContext.configure(connection)
            ops = Operations(ctx)
            original_op = module.op
            module.op = ops
            try:
                getattr(module, callable_name)()
            finally:
                module.op = original_op

    _run(migration_015, "upgrade")
    _run(migration_043, "upgrade")

    columns = {c["name"] for c in sa.inspect(engine).get_columns("audit_events")}
    assert "payload_canonical" in columns

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO audit_events (id, entity_type, entity_id, event_type, "
            "payload, payload_canonical, checksum) VALUES "
            "('00000000-0000-0000-0000-0000000000aa', 'order', "
            "'00000000-0000-0000-0000-0000000000bb', 'created', '{}', "
            "'{\"canonical\":true}', 'cafef00d')"
        )

    _run(migration_043, "downgrade")
    columns = {c["name"] for c in sa.inspect(engine).get_columns("audit_events")}
    assert "payload_canonical" in columns, (
        "043 downgrade dropped payload_canonical — verification evidence lost"
    )

    with engine.connect() as connection:
        canonical = connection.exec_driver_sql(
            "SELECT payload_canonical FROM audit_events WHERE id = "
            "'00000000-0000-0000-0000-0000000000aa'"
        ).scalar_one()
    assert canonical == '{"canonical":true}'

    # Re-upgrade must NOT raise on duplicate column.
    _run(migration_043, "upgrade")
    with engine.connect() as connection:
        canonical = connection.exec_driver_sql(
            "SELECT payload_canonical FROM audit_events WHERE id = "
            "'00000000-0000-0000-0000-0000000000aa'"
        ).scalar_one()
    assert canonical == '{"canonical":true}'
