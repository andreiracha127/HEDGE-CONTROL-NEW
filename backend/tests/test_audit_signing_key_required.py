"""Layer 2 of fail-closed audit signing — startup validation.

The application's Settings model MUST reject boot when ``AUDIT_SIGNING_KEY``
is missing in non-test environments (PR-7 / J-A1-02 §3.4).
"""

from __future__ import annotations

import os

import pytest


def test_settings_rejects_empty_key_in_postgres_environment(monkeypatch) -> None:
    """A non-test database URL with an empty AUDIT_SIGNING_KEY raises at
    Settings construction time when APP_ENV is production/staging."""
    # Reload-from-clean-env: simulate a production-like startup.
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://user:pw@host:5432/dbname",
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("AUDIT_SIGNING_KEY", raising=False)

    from app.core.config import Settings

    with pytest.raises(Exception) as excinfo:
        Settings()  # type: ignore[call-arg]

    assert "AUDIT_SIGNING_KEY" in str(excinfo.value)


def test_settings_rejects_empty_key_in_staging_environment(monkeypatch) -> None:
    """Staging is just as fail-closed as production."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://user:pw@host:5432/dbname",
    )
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("AUDIT_SIGNING_KEY", raising=False)

    from app.core.config import Settings

    with pytest.raises(Exception) as excinfo:
        Settings()  # type: ignore[call-arg]

    assert "AUDIT_SIGNING_KEY" in str(excinfo.value)


def test_settings_accepts_present_key_in_postgres_environment(monkeypatch) -> None:
    """A non-test environment with a present key boots cleanly."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://user:pw@host:5432/dbname",
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUDIT_SIGNING_KEY", "production-grade-secret")

    from app.core.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.audit_signing_key == "production-grade-secret"


def test_settings_allows_empty_key_in_dev_postgres_environment(monkeypatch) -> None:
    """Dev/local PostgreSQL stacks (e.g. default docker-compose) may boot
    with an empty AUDIT_SIGNING_KEY — Layer 1 (AuditTrailService.record)
    still fails-closed if a mutation is attempted without the key. This
    keeps the out-of-the-box ``docker-compose up`` flow working."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://user:pw@host:5432/dbname",
    )
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("AUDIT_SIGNING_KEY", raising=False)

    from app.core.config import Settings

    # Should NOT raise.
    s = Settings()  # type: ignore[call-arg]
    assert s.audit_signing_key == ""
    assert s.app_env == "development"


def test_settings_allows_empty_key_in_local_postgres_environment(monkeypatch) -> None:
    """APP_ENV=local is equivalent to development for boot-validator gating."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://user:pw@host:5432/dbname",
    )
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("AUDIT_SIGNING_KEY", raising=False)

    from app.core.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.audit_signing_key == ""


def test_settings_allows_empty_key_in_test_sqlite_environment(monkeypatch) -> None:
    """The test sqlite memory DB is exempt — pytest fixtures set the key
    dynamically per-test. The validator must not block boot in this case."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("AUDIT_SIGNING_KEY", raising=False)

    from app.core.config import Settings

    # Should NOT raise.
    s = Settings()  # type: ignore[call-arg]
    assert s.audit_signing_key == ""


def test_migration_028_imports_postgresql_uuid_explicitly() -> None:
    """Regression for Codex P1: migration 028 must reference UUID via an
    explicit ``from sqlalchemy.dialects import postgresql`` import. Bare
    ``sa.dialects.postgresql.UUID`` raises AttributeError at runtime when
    the dialect submodule is not separately imported, breaking Postgres
    production migrations even though SQLite tests skip the branch."""
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "028_reconciliation_run.py"
    )
    spec = importlib.util.spec_from_file_location(
        "reconciliation_run_migration", migration_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # If `sa.dialects.postgresql.UUID` were used without the dialect import,
    # exec_module() itself would still succeed (the offending attribute lives
    # inside upgrade()); the regression we care about is reachability of
    # postgresql.UUID via the module globals at upgrade()-time.
    spec.loader.exec_module(module)

    assert hasattr(module, "postgresql"), (
        "Migration 028 must import `from sqlalchemy.dialects import postgresql` "
        "so postgresql.UUID is reachable at upgrade() time."
    )
    # The UUID constructor must be reachable & callable.
    assert callable(getattr(module.postgresql, "UUID"))
    # Sanity: instantiating it as the migration does should not raise.
    module.postgresql.UUID(as_uuid=True)
