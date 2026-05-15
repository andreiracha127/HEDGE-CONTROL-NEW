from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.auth import get_current_user, mint_service_token
from tests.auth_token_helpers import (
    SERVICE_AUDIENCE,
    SERVICE_ISSUER,
    generate_rsa_keypair,
    make_service_token,
)

AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "


class _Request:
    def __init__(self, *, bearer: str | None = None, cookie: str | None = None) -> None:
        self.headers = {AUTHORIZATION_HEADER: BEARER_PREFIX + bearer} if bearer else {}
        self.cookies = {"__Session": cookie} if cookie else {}


@pytest.fixture()
def service_env(monkeypatch) -> tuple[str, str]:
    private_pem, public_pem = generate_rsa_keypair()
    monkeypatch.setenv("SERVICE_JWT_SIGNING_KEY", private_pem)
    monkeypatch.setenv("SERVICE_JWT_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("BACKEND_SERVICE_ISSUER", SERVICE_ISSUER)
    monkeypatch.setenv("BACKEND_SERVICE_AUDIENCE", SERVICE_AUDIENCE)
    monkeypatch.setenv("CLERK_FAPI_HOST", "fitting-pug-55.clerk.accounts.dev")
    return private_pem, public_pem


@pytest.mark.parametrize(
    ("identity", "subject"),
    [
        ("westmetall_ingest", "service:westmetall_ingest"),
        ("rfq_outbound", "service:rfq_outbound"),
        ("cashflow_pipeline", "service:cashflow_pipeline"),
    ],
)
def test_mint_service_token_for_internal_identity(service_env, identity, subject) -> None:
    _, public_pem = service_env

    token = mint_service_token(identity)
    payload = jwt.decode(
        token,
        public_pem,
        algorithms=["RS256"],
        issuer=SERVICE_ISSUER,
        audience=SERVICE_AUDIENCE,
    )

    assert payload["sub"] == subject
    assert int(payload["exp"]) - int(payload["iat"]) == 300
    assert abs(int(payload["exp"]) - (int(time.time()) + 300)) <= 5


def test_mint_service_token_unknown_raises(service_env) -> None:
    with pytest.raises(ValueError):
        mint_service_token("not_a_real_identity")


def test_get_current_user_routes_service_token_to_service_validator(service_env) -> None:
    private_pem, _ = service_env
    token = make_service_token(private_pem, sub="service:westmetall_ingest")

    user = get_current_user(_Request(bearer=token), settings=object())

    assert user["sub"] == "service:westmetall_ingest"


def test_service_token_cookie_transport_401(service_env) -> None:
    private_pem, _ = service_env
    token = make_service_token(private_pem, sub="service:westmetall_ingest")

    with pytest.raises(HTTPException) as excinfo:
        get_current_user(_Request(cookie=token), settings=object())

    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "Service token requires bearer transport"


def test_service_token_with_clerk_issuer_401(service_env) -> None:
    private_pem, _ = service_env
    token = make_service_token(
        private_pem,
        sub="service:westmetall_ingest",
        issuer="https://fitting-pug-55.clerk.accounts.dev",
    )

    with pytest.raises(HTTPException) as excinfo:
        get_current_user(_Request(bearer=token), settings=object())

    assert excinfo.value.status_code == 401


def test_mint_service_token_cli_entrypoint_exists() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "mint_service_token.py"
    spec = importlib.util.spec_from_file_location("mint_service_token_cli", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.main)
