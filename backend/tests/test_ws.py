"""Integration tests for the WebSocket endpoint at /ws."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from starlette.testclient import WebSocketDisconnect

from app.api.routes.ws import manager, _ConnState
import app.api.routes.ws as ws_module
from app.core.auth import AuthSettings, SESSION_COOKIE_NAME, get_auth_disabled_fallback_user
from tests.auth_token_helpers import (
    CLERK_ISSUER,
    generate_rsa_keypair,
    make_clerk_token,
    rsa_jwk,
)


# Synthetic authenticated subject; distinct from the auth-disabled "anonymous" fallback.
VALID_CLAIMS = {"sub": "test-user", "roles": ["risk_manager"]}


@pytest.fixture(autouse=True)
def _reset_ws_state():
    """Reset the WS manager and sequence counter between tests."""
    manager._connections.clear()
    ws_module._seq_counter = 0
    yield
    manager._connections.clear()
    ws_module._seq_counter = 0


def _patch_validate_token(return_value):
    """Patch _validate_token to return the given value."""
    return patch("app.api.routes.ws._validate_token", return_value=return_value)


def _authenticate(ws, token="fake-jwt"):
    """Send auth message and return the response."""
    ws.send_json({"action": "authenticate", "token": token})
    return ws.receive_json()


# ─── 1. Auth success ───────────────────────────────────────────────

def test_auth_success(client):
    with _patch_validate_token(VALID_CLAIMS):
        with client.websocket_connect("/ws") as ws:
            resp = _authenticate(ws)
            assert resp["type"] == "auth_ack"
            assert resp["user"] == "test-user"


def test_auth_uses_session_cookie_when_message_token_empty(client):
    client.cookies.set(SESSION_COOKIE_NAME, "cookie-jwt")
    with _patch_validate_token(VALID_CLAIMS) as validate_token:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "authenticate", "token": ""})
            resp = ws.receive_json()
            assert resp["type"] == "auth_ack"
            assert resp["user"] == "test-user"
    validate_token.assert_called_once_with("cookie-jwt")


# ─── 2. Auth failure → close 1008 ─────────────────────────────────

def test_auth_failure_closes_1008(client):
    with _patch_validate_token(None):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"action": "authenticate", "token": "bad-token"})
                ws.receive_json()  # should trigger disconnect
        assert exc_info.value.code == 1008


def test_auth_rejects_mixed_auditor_roles(client):
    with _patch_validate_token(
        {"sub": "bad-actor", "roles": ["auditor", "risk_manager"]}
    ):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"action": "authenticate", "token": "bad-token"})
                ws.receive_json()
        assert exc_info.value.code == 1008


# ─── 3. Non-auth first message → close 1008 ───────────────────────

def test_non_auth_first_message_closes_1008(client):
    with _patch_validate_token(VALID_CLAIMS):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"action": "subscribe", "topic": "rfq", "id": str(uuid4())})
                ws.receive_json()
        assert exc_info.value.code == 1008


# ─── 4. Subscribe → ack ───────────────────────────────────────────

def test_subscribe_ack(client):
    rfq_id = str(uuid4())
    with _patch_validate_token(VALID_CLAIMS):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_json({"action": "subscribe", "topic": "rfq", "id": rfq_id})
            resp = ws.receive_json()
            assert resp["type"] == "subscription_ack"
            assert resp["topic"] == "rfq"
            assert resp["id"] == rfq_id


def test_rfq_subscribe_forbidden_for_trader(client):
    rfq_id = str(uuid4())
    with _patch_validate_token({"sub": "trader-user", "roles": ["trader"]}):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_json({"action": "subscribe", "topic": "rfq", "id": rfq_id})
            resp = ws.receive_json()
            assert resp == {
                "type": "subscription_error",
                "reason": "forbidden",
                "topic": "rfq",
                "id": rfq_id,
            }


def test_rfq_subscribe_ack_for_auditor(client):
    rfq_id = str(uuid4())
    with _patch_validate_token({"sub": "auditor-user", "roles": ["auditor"]}):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_json({"action": "subscribe", "topic": "rfq", "id": rfq_id})
            resp = ws.receive_json()
            assert resp["type"] == "subscription_ack"
            assert resp["topic"] == "rfq"
            assert resp["id"] == rfq_id


def test_rfq_subscribe_ack_with_auth_disabled_fallback(client):
    rfq_id = str(uuid4())
    with patch("app.api.routes.ws.get_auth_settings", return_value=None):
        assert ws_module._validate_token("fake-jwt") is get_auth_disabled_fallback_user()
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_json({"action": "subscribe", "topic": "rfq", "id": rfq_id})
            resp = ws.receive_json()
            assert resp["type"] == "subscription_ack"


def test_ws_validate_token_disables_audience_check_when_clerk_audience_empty():
    private_pem, public_pem = generate_rsa_keypair()
    token = make_clerk_token(private_pem, audience="present-but-ignored")
    original_jwks = ws_module._jwks_cache._jwks
    original_expires = ws_module._jwks_cache._expires_at
    ws_module._jwks_cache._jwks = {"keys": [rsa_jwk(public_pem)]}
    ws_module._jwks_cache._expires_at = time.time() + 3600
    settings = AuthSettings(
        issuer=CLERK_ISSUER,
        audience="",
        jwks_url="https://clerk.example.test/.well-known/jwks.json",
    )
    try:
        with patch("app.api.routes.ws.get_auth_settings", return_value=settings):
            claims = ws_module._validate_token(token)
    finally:
        ws_module._jwks_cache._jwks = original_jwks
        ws_module._jwks_cache._expires_at = original_expires

    assert claims is not None
    assert claims["sub"] == "user_test"


def test_ws_rejects_clerk_token_with_service_role_claim(client):
    private_pem, public_pem = generate_rsa_keypair()
    token = make_clerk_token(
        private_pem,
        roles=["risk_manager", "service:westmetall_ingest"],
    )
    original_jwks = ws_module._jwks_cache._jwks
    original_expires = ws_module._jwks_cache._expires_at
    ws_module._jwks_cache._jwks = {"keys": [rsa_jwk(public_pem)]}
    ws_module._jwks_cache._expires_at = time.time() + 3600
    settings = AuthSettings(
        issuer=CLERK_ISSUER,
        audience="hedge-control-tests",
        jwks_url="https://clerk.example.test/.well-known/jwks.json",
    )
    try:
        with patch("app.api.routes.ws.get_auth_settings", return_value=settings):
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/ws") as ws:
                    ws.send_json({"action": "authenticate", "token": token})
                    ws.receive_json()
    finally:
        ws_module._jwks_cache._jwks = original_jwks
        ws_module._jwks_cache._expires_at = original_expires

    assert exc_info.value.code == 1008
    assert manager.active_count == 0
    assert all(not state.subscriptions for state in manager._connections.values())


# ─── 5. Subscribe with missing fields → error ─────────────────────

def test_subscribe_missing_topic(client):
    with _patch_validate_token(VALID_CLAIMS):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_json({"action": "subscribe", "id": str(uuid4())})
            resp = ws.receive_json()
            assert resp["type"] == "subscription_error"
            assert "missing" in resp["reason"].lower()


def test_subscribe_missing_id(client):
    with _patch_validate_token(VALID_CLAIMS):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_json({"action": "subscribe", "topic": "rfq"})
            resp = ws.receive_json()
            assert resp["type"] == "subscription_error"
            assert "missing" in resp["reason"].lower()


# ─── 6. Unsubscribe → ack ─────────────────────────────────────────

def test_unsubscribe_ack(client):
    rfq_id = str(uuid4())
    with _patch_validate_token(VALID_CLAIMS):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_json({"action": "subscribe", "topic": "rfq", "id": rfq_id})
            ws.receive_json()  # subscription_ack
            ws.send_json({"action": "unsubscribe", "topic": "rfq", "id": rfq_id})
            resp = ws.receive_json()
            assert resp["type"] == "unsubscription_ack"
            assert resp["topic"] == "rfq"
            assert resp["id"] == rfq_id


# ─── 7. Ping → pong ───────────────────────────────────────────────

def test_ping_pong(client):
    with _patch_validate_token(VALID_CLAIMS):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_json({"action": "ping"})
            resp = ws.receive_json()
            assert resp["type"] == "pong"


# ─── 8. Unknown action → error ────────────────────────────────────

def test_unknown_action(client):
    with _patch_validate_token(VALID_CLAIMS):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_json({"action": "foobar"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "unknown action" in resp["reason"]
            assert "foobar" in resp["reason"]


# ─── 9. Invalid JSON → error ──────────────────────────────────────

def test_invalid_json_before_auth(client):
    """Invalid JSON sent as the very first message (pre-auth) closes connection."""
    with _patch_validate_token(VALID_CLAIMS):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws") as ws:
                ws.send_text("not json at all{{{")
                resp = ws.receive_json()
                assert resp["type"] == "error"
                assert resp["reason"] == "invalid_json"
                # Connection is closed after error response
                ws.receive_json()  # triggers disconnect
        assert exc_info.value.code == 1008


def test_invalid_json_after_auth(client):
    """Invalid JSON sent after successful authentication."""
    with _patch_validate_token(VALID_CLAIMS):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_text("{bad json}")
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert resp["reason"] == "invalid_json"


# ─── 10. Broadcast to subscribed connection ────────────────────────

def test_broadcast_to_subscriber(client):
    rfq_id = str(uuid4())
    with _patch_validate_token(VALID_CLAIMS):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_json({"action": "subscribe", "topic": "rfq", "id": rfq_id})
            ws.receive_json()  # subscription_ack

            # Broadcast from the manager (simulating a service layer call).
            # We use send_json + receive_json to stay in the sync test client
            # event loop, but broadcast is async — call via the running loop.
            import asyncio

            loop = asyncio.get_event_loop()
            loop.run_until_complete(
                manager.broadcast("rfq", rfq_id, "quote_received", {"price": 2450.0})
            )

            resp = ws.receive_json()
            assert resp["event"] == "quote_received"
            assert resp["rfq_id"] == rfq_id
            assert resp["data"]["price"] == 2450.0
            assert "seq" in resp
            assert "timestamp" in resp


# ─── 11. Broadcast NOT received by unsubscribed connection ────────

def test_broadcast_not_received_by_unsubscribed(client):
    rfq_id = str(uuid4())
    other_rfq_id = str(uuid4())
    with _patch_validate_token(VALID_CLAIMS):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            # Subscribe to rfq_id, NOT other_rfq_id
            ws.send_json({"action": "subscribe", "topic": "rfq", "id": rfq_id})
            ws.receive_json()  # subscription_ack

            import asyncio

            # Broadcast to a different rfq — should NOT arrive
            asyncio.get_event_loop().run_until_complete(
                manager.broadcast("rfq", other_rfq_id, "quote_received", {"price": 99})
            )

            # Now broadcast to the subscribed rfq — this SHOULD arrive
            asyncio.get_event_loop().run_until_complete(
                manager.broadcast("rfq", rfq_id, "status_changed", {"status": "SENT"})
            )

            resp = ws.receive_json()
            # We should get the status_changed event, not the quote_received
            assert resp["event"] == "status_changed"
            assert resp["rfq_id"] == rfq_id


# ─── 12. Sequence numbers are monotonic ───────────────────────────

def test_sequence_numbers_monotonic(client):
    rfq_id = str(uuid4())
    with _patch_validate_token(VALID_CLAIMS):
        with client.websocket_connect("/ws") as ws:
            _authenticate(ws)
            ws.send_json({"action": "subscribe", "topic": "rfq", "id": rfq_id})
            ws.receive_json()  # subscription_ack

            import asyncio

            seqs = []
            for i in range(5):
                asyncio.get_event_loop().run_until_complete(
                    manager.broadcast("rfq", rfq_id, "quote_received", {"i": i})
                )
                resp = ws.receive_json()
                seqs.append(resp["seq"])

            # Verify strictly increasing
            assert seqs == sorted(seqs)
            assert len(set(seqs)) == 5  # all unique
            # First seq should be 1 (counter was reset in fixture)
            assert seqs[0] == 1
            assert seqs[-1] == 5


# ─── 13. Auth timeout → close 1008 ──────────────────────────────

def test_auth_timeout_closes_1008(client):
    """Connection closed with 1008 if first message not sent within timeout."""
    original_wait_for = asyncio.wait_for

    async def _mock_wait_for(coro, *, timeout=None):
        """Simulate timeout on the first receive_text call."""
        # Cancel the coroutine to avoid warnings
        coro.close()
        raise asyncio.TimeoutError()

    with _patch_validate_token(VALID_CLAIMS):
        with patch("asyncio.wait_for", side_effect=_mock_wait_for):
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/ws") as ws:
                    ws.receive_json()  # triggers disconnect
            assert exc_info.value.code == 1008
