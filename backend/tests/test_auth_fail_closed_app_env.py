"""J-A5-06 — auth startup validation reads canonical APP_ENV.

Before PR-A5-3, ``validate_auth_config`` consulted ``os.getenv("ENVIRONMENT")``
while the rest of the application gated on ``Settings.app_env`` (which is fed
by ``APP_ENV``). The mismatch meant that ``APP_ENV=production`` with
``ENVIRONMENT`` unset would NOT fail closed at startup, leaving audit
read/verify routes reachable via the anonymous fallback identity.

These tests pin the canonical-settings contract:

* production/staging-like ``APP_ENV`` values with missing JWT config fail boot;
* ``AUTH_DISABLED`` is not honored in production/staging;
* dev/local/test environments still allow the anonymous fallback;
* the audit list/verify routes reject anonymous callers when the canonical
  environment is production/staging.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core import config as config_module
from app.core.auth import (
    _ANONYMOUS_USER,
    get_auth_settings,
    get_current_user,
    validate_auth_config,
)
from app.main import app


@contextmanager
def _settings_override(**overrides) -> Iterator[None]:
    """Temporarily mutate the cached Settings singleton.

    Settings is a pydantic-settings ``BaseSettings`` instance built once at
    import time; runtime auth callers go through ``get_settings()`` which
    returns the cached object. Mutating the live attributes is the
    cheapest way to exercise environment-marker branches without
    re-importing the whole app graph.
    """
    s = config_module.get_settings()
    snapshot = {k: getattr(s, k) for k in overrides}
    try:
        for k, v in overrides.items():
            object.__setattr__(s, k, v)
        yield
    finally:
        for k, v in snapshot.items():
            object.__setattr__(s, k, v)


# ── validate_auth_config — production/staging fail-closed ──────────────────


def test_validate_auth_config_fails_when_production_app_env_and_no_jwt() -> None:
    with _settings_override(app_env="production", jwt_issuer="", jwt_audience="", jwks_url=""):
        with pytest.raises(RuntimeError) as excinfo:
            validate_auth_config()
    assert "production" in str(excinfo.value).lower()


def test_validate_auth_config_fails_when_staging_app_env_and_no_jwt() -> None:
    with _settings_override(app_env="staging", jwt_issuer="", jwt_audience="", jwks_url=""):
        with pytest.raises(RuntimeError) as excinfo:
            validate_auth_config()
    assert "staging" in str(excinfo.value).lower()


@pytest.mark.parametrize("env", ["prod", "stage", "preprod", "pre-prod"])
def test_validate_auth_config_fails_for_other_fail_closed_env_aliases(env) -> None:
    """Cover every alias enumerated in ``auth._FAIL_CLOSED_ENVS`` so that a
    typo in ``APP_ENV`` (e.g. ``prod`` instead of ``production``) cannot
    silently bypass the boot gate."""
    with _settings_override(app_env=env, jwt_issuer="", jwt_audience="", jwks_url=""):
        with pytest.raises(RuntimeError):
            validate_auth_config()


def test_validate_auth_config_does_not_consult_legacy_environment_var(monkeypatch) -> None:
    """Regression for the J-A5-06 mismatch: even with ENVIRONMENT unset (or
    set to a benign value), APP_ENV=production must still fail-closed."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with _settings_override(app_env="production", jwt_issuer="", jwt_audience="", jwks_url=""):
        with pytest.raises(RuntimeError):
            validate_auth_config()

    monkeypatch.setenv("ENVIRONMENT", "development")
    with _settings_override(app_env="production", jwt_issuer="", jwt_audience="", jwks_url=""):
        with pytest.raises(RuntimeError):
            validate_auth_config()


def test_validate_auth_config_rejects_auth_disabled_in_production(monkeypatch) -> None:
    """AUTH_DISABLED is not a production escape hatch."""
    monkeypatch.setenv("AUTH_DISABLED", "true")
    with _settings_override(app_env="production", jwt_issuer="", jwt_audience="", jwks_url=""):
        with pytest.raises(RuntimeError) as excinfo:
            validate_auth_config()
    assert "auth_disabled" in str(excinfo.value).lower()


def test_validate_auth_config_requires_full_jwt_triplet_when_issuer_set() -> None:
    """JWT_ISSUER alone is not enough — audience and JWKS_URL must also be
    configured, otherwise get_auth_settings() would 500 at runtime."""
    with _settings_override(app_env="production", jwt_issuer="issuer", jwt_audience="", jwks_url=""):
        with pytest.raises(RuntimeError):
            validate_auth_config()


# ── validate_auth_config — dev/local/test are explicitly allowed ───────────


@pytest.mark.parametrize("env", ["development", "local", "test", ""])
def test_validate_auth_config_allows_disabled_auth_in_nonprod_envs(env, monkeypatch) -> None:
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    with _settings_override(app_env=env, jwt_issuer="", jwt_audience="", jwks_url=""):
        # Must NOT raise.
        validate_auth_config()


def test_validate_auth_config_allows_full_jwt_config_in_production() -> None:
    with _settings_override(
        app_env="production",
        jwt_issuer="https://issuer.example",
        jwt_audience="api://aud",
        jwks_url="https://issuer.example/jwks",
    ):
        validate_auth_config()


# ── get_current_user — anonymous fallback gating ───────────────────────────


def _user_dep(request) -> dict:
    """Resolve get_current_user without a real FastAPI dependency stack."""
    settings = get_auth_settings()
    return get_current_user(request=request, settings=settings)


def test_get_current_user_rejects_anonymous_in_production() -> None:
    """Even if startup validation was somehow bypassed, request-time
    anonymous access must be refused in production-like environments."""

    class _Req:
        headers: dict[str, str] = {}

    with _settings_override(app_env="production", jwt_issuer="", jwt_audience="", jwks_url=""):
        with pytest.raises(HTTPException) as excinfo:
            _user_dep(_Req())
    assert excinfo.value.status_code == 401


def test_get_current_user_rejects_anonymous_in_staging() -> None:
    class _Req:
        headers: dict[str, str] = {}

    with _settings_override(app_env="staging", jwt_issuer="", jwt_audience="", jwks_url=""):
        with pytest.raises(HTTPException) as excinfo:
            _user_dep(_Req())
    assert excinfo.value.status_code == 401


def test_get_current_user_returns_anonymous_in_development() -> None:
    class _Req:
        headers: dict[str, str] = {}

    with _settings_override(app_env="development", jwt_issuer="", jwt_audience="", jwks_url=""):
        result = _user_dep(_Req())
    assert result == _ANONYMOUS_USER


# ── audit endpoints — anonymous rejection under production/staging ─────────


def test_audit_list_rejects_anonymous_in_production() -> None:
    """End-to-end: /audit/events must 401 when APP_ENV=production and auth
    is misconfigured/disabled. Bypassing the route auth dependency is the
    main risk J-A5-06 closes; this test exercises the real dependency
    stack with no overrides."""
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    try:
        with _settings_override(
            app_env="production", jwt_issuer="", jwt_audience="", jwks_url=""
        ):
            client = TestClient(app)
            resp = client.get("/audit/events")
        assert resp.status_code == 401, resp.text
    finally:
        app.dependency_overrides.update(overrides)


def test_audit_verify_rejects_anonymous_in_staging() -> None:
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    try:
        with _settings_override(
            app_env="staging", jwt_issuer="", jwt_audience="", jwks_url=""
        ):
            client = TestClient(app)
            resp = client.get(
                "/audit/events/00000000-0000-0000-0000-000000000000/verify"
            )
        assert resp.status_code == 401, resp.text
    finally:
        app.dependency_overrides.update(overrides)


# ── seed.py / local tooling — must self-declare APP_ENV ───────────────────


def _script_path(name: str):
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "scripts" / name


def _assert_script_declares_app_env_before_app_main(script_name: str) -> None:
    """Shared AST contract: every script that imports ``app.main`` must
    declare ``APP_ENV`` via ``os.environ.setdefault`` BEFORE the import,
    so the fail-closed boot gates (J-A5-06) do not refuse to boot."""
    import ast

    path = _script_path(script_name)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    app_main_import_line: int | None = None
    app_env_setdefault_line: int | None = None

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.main":
            if app_main_import_line is None or node.lineno < app_main_import_line:
                app_main_import_line = node.lineno
        if isinstance(node, ast.Call):
            func = node.func
            attr = func.attr if isinstance(func, ast.Attribute) else None
            value = func.value if isinstance(func, ast.Attribute) else None
            value_name = value.attr if isinstance(value, ast.Attribute) else None
            # match os.environ.setdefault("APP_ENV", ...)
            if (
                attr == "setdefault"
                and value_name == "environ"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "APP_ENV"
            ):
                if app_env_setdefault_line is None or node.lineno < app_env_setdefault_line:
                    app_env_setdefault_line = node.lineno

    assert app_main_import_line is not None, (
        f"{script_name} must import app.main; the contract this test pins "
        f"assumes that import exists."
    )
    assert app_env_setdefault_line is not None, (
        f"{script_name} must declare APP_ENV via "
        f"os.environ.setdefault(\"APP_ENV\", ...) before importing app.main, "
        f"so the fail-closed boot gates (J-A5-06) do not refuse to boot."
    )
    assert app_env_setdefault_line < app_main_import_line, (
        f"{script_name} must set APP_ENV BEFORE importing app.main "
        f"(setdefault at line {app_env_setdefault_line}, "
        f"import at line {app_main_import_line})."
    )


def test_seed_script_declares_app_env_before_importing_app() -> None:
    _assert_script_declares_app_env_before_app_main("seed.py")


def test_export_openapi_script_declares_app_env_before_importing_app() -> None:
    """Regression for the second Codex P2: standalone schema export must
    work without a wrapping CI step setting ``APP_ENV=test``. The script
    self-declares the env so local/documented regeneration paths boot."""
    _assert_script_declares_app_env_before_app_main("export_openapi.py")


def test_audit_list_allows_anonymous_in_development() -> None:
    """Sanity: dev environment continues to expose audit endpoints via the
    anonymous identity so local workflows keep working."""
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    try:
        with _settings_override(
            app_env="development", jwt_issuer="", jwt_audience="", jwks_url=""
        ):
            client = TestClient(app)
            resp = client.get("/audit/events")
        # 200 with empty list; no auth challenge.
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.update(overrides)
