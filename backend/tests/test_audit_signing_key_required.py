"""Layer 2 of fail-closed audit signing — startup validation.

The application's Settings model MUST reject boot when ``AUDIT_SIGNING_KEY``
is missing in non-test environments (PR-7 / J-A1-02 §3.4).
"""

from __future__ import annotations

import os

import pytest


def test_settings_rejects_empty_key_in_postgres_environment(monkeypatch) -> None:
    """A non-test database URL with an empty AUDIT_SIGNING_KEY raises at
    Settings construction time."""
    # Reload-from-clean-env: simulate a production-like startup.
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://user:pw@host:5432/dbname",
    )
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
    monkeypatch.setenv("AUDIT_SIGNING_KEY", "production-grade-secret")

    from app.core.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.audit_signing_key == "production-grade-secret"


def test_settings_allows_empty_key_in_test_sqlite_environment(monkeypatch) -> None:
    """The test sqlite memory DB is exempt — pytest fixtures set the key
    dynamically per-test. The validator must not block boot in this case."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.delenv("AUDIT_SIGNING_KEY", raising=False)

    from app.core.config import Settings

    # Should NOT raise.
    s = Settings()  # type: ignore[call-arg]
    assert s.audit_signing_key == ""
