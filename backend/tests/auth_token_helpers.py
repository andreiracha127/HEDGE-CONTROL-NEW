from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from jose.utils import base64url_encode

from app.core.auth import AuthSettings

CLERK_FAPI_HOST = "fitting-pug-55.clerk.accounts.dev"
CLERK_ISSUER = f"https://{CLERK_FAPI_HOST}"
CLERK_AUDIENCE = "hedge-control-tests"
SERVICE_ISSUER = "https://api.hedge-control.local"
SERVICE_AUDIENCE = "internal-services"


class _Missing:
    pass


_MISSING = _Missing()
_DEFAULT_ROLES = object()


def generate_rsa_keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def rsa_jwk(public_pem: str, kid: str = "test-key") -> dict[str, Any]:
    public_key = serialization.load_pem_public_key(public_pem.encode())
    assert isinstance(public_key, rsa.RSAPublicKey)
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "kid": kid,
        "alg": "RS256",
        "n": base64url_encode(
            numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
        ).decode(),
        "e": base64url_encode(
            numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
        ).decode(),
    }


def clerk_settings(audience: str = CLERK_AUDIENCE) -> AuthSettings:
    return AuthSettings(
        issuer=CLERK_ISSUER,
        audience=audience,
        jwks_url=f"https://{CLERK_FAPI_HOST}/.well-known/jwks.json",
    )


def make_clerk_token(
    private_pem: str,
    *,
    kid: str = "test-key",
    sub: str = "user_test",
    issuer: str = CLERK_ISSUER,
    audience: str | None = CLERK_AUDIENCE,
    roles: Any = _DEFAULT_ROLES,
    exp_delta: int = 300,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "iss": issuer,
        "iat": now,
        "nbf": now,
        "exp": now + exp_delta,
    }
    if audience is not None:
        payload["aud"] = audience
    if roles is _DEFAULT_ROLES:
        payload["roles"] = ["risk_manager"]
    elif roles is not _MISSING:
        payload["roles"] = roles
    return jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": kid})


def make_service_token(
    private_pem: str,
    *,
    kid: str = "service-key",
    sub: str = "service:westmetall_ingest",
    issuer: str = SERVICE_ISSUER,
    audience: str = SERVICE_AUDIENCE,
    exp_delta: int = 300,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "nbf": now,
            "exp": now + exp_delta,
        },
        private_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )


@contextmanager
def patched_jwks(auth_module, jwks: dict[str, Any]) -> Iterator[None]:
    original = auth_module._jwks_cache._jwks
    original_expires = auth_module._jwks_cache._expires_at
    auth_module._jwks_cache._jwks = jwks
    auth_module._jwks_cache._expires_at = time.time() + 3600
    try:
        yield
    finally:
        auth_module._jwks_cache._jwks = original
        auth_module._jwks_cache._expires_at = original_expires
