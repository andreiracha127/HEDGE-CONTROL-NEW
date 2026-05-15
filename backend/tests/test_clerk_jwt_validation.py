from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core import auth as auth_module
from app.core.auth import get_current_user
from tests.auth_token_helpers import (
    CLERK_ISSUER,
    _MISSING,
    clerk_settings,
    generate_rsa_keypair,
    make_clerk_token,
    patched_jwks,
    rsa_jwk,
)

AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "


class _Request:
    def __init__(self, *, cookie: str | None = None, bearer: str | None = None) -> None:
        self.cookies = {"__Session": cookie} if cookie else {}
        self.headers = {AUTHORIZATION_HEADER: BEARER_PREFIX + bearer} if bearer else {}


@pytest.fixture()
def clerk_keys() -> tuple[str, str, dict]:
    private_pem, public_pem = generate_rsa_keypair()
    return private_pem, public_pem, {"keys": [rsa_jwk(public_pem)]}


def _resolve_user(token: str, jwks: dict, *, audience: str = "hedge-control-tests"):
    with patched_jwks(auth_module, jwks):
        return get_current_user(_Request(cookie=token), settings=clerk_settings(audience))


def test_clerk_jwt_valid_returns_user(clerk_keys) -> None:
    private_pem, _, jwks = clerk_keys
    token = make_clerk_token(private_pem, roles=["risk_manager"])

    user = _resolve_user(token, jwks)

    assert user["sub"] == "user_test"
    assert user["roles"] == ["risk_manager"]


def test_clerk_jwt_invalid_signature_401(clerk_keys) -> None:
    _, _, jwks = clerk_keys
    wrong_private, _ = generate_rsa_keypair()
    token = make_clerk_token(wrong_private, roles=["risk_manager"])

    with pytest.raises(HTTPException) as excinfo:
        _resolve_user(token, jwks)

    assert excinfo.value.status_code == 401


def test_clerk_jwt_expired_401(clerk_keys) -> None:
    private_pem, _, jwks = clerk_keys
    token = make_clerk_token(private_pem, roles=["risk_manager"], exp_delta=-1)

    with pytest.raises(HTTPException) as excinfo:
        _resolve_user(token, jwks)

    assert excinfo.value.status_code == 401


def test_clerk_jwt_wrong_audience_401(clerk_keys) -> None:
    private_pem, _, jwks = clerk_keys
    token = make_clerk_token(private_pem, roles=["risk_manager"], audience="wrong")

    with pytest.raises(HTTPException) as excinfo:
        _resolve_user(token, jwks)

    assert excinfo.value.status_code == 401


def test_clerk_jwt_wrong_issuer_401(clerk_keys) -> None:
    private_pem, _, jwks = clerk_keys
    token = make_clerk_token(
        private_pem,
        roles=["risk_manager"],
        issuer="https://wrong.example",
    )

    with pytest.raises(HTTPException) as excinfo:
        _resolve_user(token, jwks)

    assert excinfo.value.status_code == 401


def test_clerk_jwt_auditor_with_trader_roles_returns_401(clerk_keys) -> None:
    private_pem, _, jwks = clerk_keys
    token = make_clerk_token(private_pem, roles=["auditor", "trader"])

    with pytest.raises(HTTPException) as excinfo:
        _resolve_user(token, jwks)

    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "Invalid role combination: auditor must be exclusive"


def test_clerk_jwt_auditor_alone_succeeds_user_dict(clerk_keys) -> None:
    private_pem, _, jwks = clerk_keys
    token = make_clerk_token(private_pem, roles=["auditor"])

    user = _resolve_user(token, jwks)

    assert user["roles"] == ["auditor"]


def test_clerk_jwt_trader_plus_risk_manager_passes(clerk_keys) -> None:
    private_pem, _, jwks = clerk_keys
    token = make_clerk_token(private_pem, roles=["trader", "risk_manager"])

    user = _resolve_user(token, jwks)

    assert set(user["roles"]) == {"trader", "risk_manager"}


def test_clerk_jwt_rejects_service_roles_on_human_token(clerk_keys) -> None:
    private_pem, _, jwks = clerk_keys
    token = make_clerk_token(private_pem, roles=["service:westmetall_ingest"])

    with pytest.raises(HTTPException) as excinfo:
        _resolve_user(token, jwks)

    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "Invalid roles claim"


@pytest.mark.parametrize("roles", [_MISSING, "auditor", {"role": "auditor"}, None, ["auditor", 3]])
def test_clerk_jwt_malformed_roles_claim_401(clerk_keys, roles) -> None:
    private_pem, _, jwks = clerk_keys
    token = make_clerk_token(private_pem, roles=roles)

    with pytest.raises(HTTPException) as excinfo:
        _resolve_user(token, jwks)

    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "Invalid roles claim"


def test_clerk_audience_can_be_disabled_in_dev_when_empty(clerk_keys) -> None:
    private_pem, _, jwks = clerk_keys
    token = make_clerk_token(private_pem, roles=["risk_manager"], audience=None)

    user = _resolve_user(token, jwks, audience="")

    assert user["sub"] == "user_test"
