"""WebSocket endpoint for real-time RFQ updates.

Protocol:
  1. Client connects to /ws (no token in URL)
  2. Client sends: {"action": "authenticate", "token": "<jwt>"}
  3. Server validates JWT → ack or close(1008)
  4. Client sends: {"action": "subscribe", "topic": "rfq", "id": "<rfq_id>"}
  5. Server pushes events filtered by subscription
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from starlette.websockets import WebSocketState

from app.core.auth import (
    JWKSCache,
    SESSION_COOKIE_NAME,
    extract_actor_roles_from_payload,
    get_auth_disabled_fallback_user,
    get_auth_settings,
)

logger = logging.getLogger(__name__)

# Re-use the same JWKS cache as HTTP auth
_jwks_cache = JWKSCache()

# Monotonic sequence counter for gap detection
_seq_counter = 0
_seq_lock = asyncio.Lock()


async def _next_seq() -> int:
    global _seq_counter
    async with _seq_lock:
        _seq_counter += 1
        return _seq_counter


def _validate_token(token: str) -> dict[str, Any] | None:
    """Validate JWT token, return claims or None."""
    settings = get_auth_settings()
    if settings is None:
        return get_auth_disabled_fallback_user()
    try:
        header = jwt.get_unverified_header(token)
        jwks = _jwks_cache.get(settings)
        keys = jwks.get("keys", [])
        kid = header.get("kid")
        jwk = None
        for key in keys:
            if kid is None or key.get("kid") == kid:
                jwk = key
                break
        if jwk is None:
            return None
        decode_kwargs: dict[str, Any] = {
            "key": jwk,
            "algorithms": ["RS256"],
            "issuer": settings.issuer,
        }
        if settings.audience:
            decode_kwargs["audience"] = settings.audience
        else:
            decode_kwargs["options"] = {"verify_aud": False}
        payload = jwt.decode(token, **decode_kwargs)
        return payload
    except (JWTError, Exception):
        return None


class ConnectionManager:
    """Manages WebSocket connections, authentication, and subscriptions."""

    def __init__(self) -> None:
        self._connections: dict[WebSocket, _ConnState] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections[ws] = _ConnState()

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.pop(ws, None)

    async def authenticate(self, ws: WebSocket, token: str) -> bool:
        claims = _validate_token(token)
        if claims is None:
            return False
        try:
            extract_actor_roles_from_payload(claims)
        except Exception:
            return False
        async with self._lock:
            state = self._connections.get(ws)
            if state:
                state.authenticated = True
                state.user = claims
        return True

    def is_authenticated(self, ws: WebSocket) -> bool:
        state = self._connections.get(ws)
        return state.authenticated if state else False

    def get_user(self, ws: WebSocket) -> dict[str, Any] | None:
        state = self._connections.get(ws)
        return state.user if state else None

    def get_state(self, ws: WebSocket) -> "_ConnState | None":
        return self._connections.get(ws)

    async def subscribe(self, ws: WebSocket, topic: str, topic_id: str) -> None:
        async with self._lock:
            state = self._connections.get(ws)
            if state:
                state.subscriptions.add((topic, topic_id))

    async def unsubscribe(self, ws: WebSocket, topic: str, topic_id: str) -> None:
        async with self._lock:
            state = self._connections.get(ws)
            if state:
                state.subscriptions.discard((topic, topic_id))

    async def broadcast(
        self, topic: str, topic_id: str, event: str, data: dict[str, Any]
    ) -> None:
        """Broadcast an event to all connections subscribed to (topic, topic_id)."""
        seq = await _next_seq()
        message = json.dumps(
            {
                "event": event,
                "rfq_id": topic_id,
                "data": data,
                "timestamp": _iso_now(),
                "seq": seq,
            }
        )
        async with self._lock:
            targets = [
                ws
                for ws, state in self._connections.items()
                if state.authenticated and (topic, topic_id) in state.subscriptions
            ]
        for ws in targets:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(message)
            except Exception:
                logger.debug("ws_send_failed", exc_info=True)

    @property
    def active_count(self) -> int:
        return len(self._connections)


class _ConnState:
    __slots__ = ("authenticated", "user", "subscriptions")

    def __init__(self) -> None:
        self.authenticated = False
        self.user: dict[str, Any] | None = None
        self.subscriptions: set[tuple[str, str]] = set()


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# Singleton — import this from services to broadcast events
manager = ConnectionManager()


async def websocket_endpoint(ws: WebSocket) -> None:
    """Main WebSocket handler with first-message authentication."""
    await manager.connect(ws)
    try:
        # First message must arrive within 10 seconds to prevent
        # unauthenticated clients from holding connections open.
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
        except asyncio.TimeoutError:
            await ws.close(code=1008, reason="Authentication timeout")
            await manager.disconnect(ws)
            return

        # Process the first message — must be a valid authenticate action
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_text(json.dumps({"type": "error", "reason": "invalid_json"}))
            await ws.close(code=1008, reason="Authentication required")
            await manager.disconnect(ws)
            return

        action = msg.get("action")
        if action != "authenticate":
            await ws.close(code=1008, reason="Authentication required")
            await manager.disconnect(ws)
            return

        token = msg.get("token", "") or ws.cookies.get(SESSION_COOKIE_NAME, "")
        if await manager.authenticate(ws, token):
            user = manager.get_user(ws)
            await ws.send_text(
                json.dumps({"type": "auth_ack", "user": user.get("sub", "") if user else ""})
            )
        else:
            await ws.close(code=1008, reason="Invalid token")
            await manager.disconnect(ws)
            return

        # Authenticated — enter the main message loop
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "reason": "invalid_json"}))
                continue

            action = msg.get("action")

            # Authenticated — handle actions
            if action == "subscribe":
                topic = msg.get("topic", "")
                topic_id = msg.get("id", "")
                if topic and topic_id:
                    if topic == "rfq":
                        try:
                            actor_roles = extract_actor_roles_from_payload(
                                manager.get_user(ws) or {}
                            )
                        except Exception:
                            actor_roles = []
                        if not (
                            "risk_manager" in actor_roles or "auditor" in actor_roles
                        ):
                            await ws.send_text(
                                json.dumps(
                                    {
                                        "type": "subscription_error",
                                        "reason": "forbidden",
                                        "topic": topic,
                                        "id": topic_id,
                                    }
                                )
                            )
                            continue
                    await manager.subscribe(ws, topic, topic_id)
                    await ws.send_text(
                        json.dumps({"type": "subscription_ack", "topic": topic, "id": topic_id})
                    )
                else:
                    await ws.send_text(
                        json.dumps({"type": "subscription_error", "reason": "missing topic or id"})
                    )

            elif action == "unsubscribe":
                topic = msg.get("topic", "")
                topic_id = msg.get("id", "")
                await manager.unsubscribe(ws, topic, topic_id)
                await ws.send_text(
                    json.dumps({"type": "unsubscription_ack", "topic": topic, "id": topic_id})
                )

            elif action == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

            else:
                await ws.send_text(
                    json.dumps({"type": "error", "reason": f"unknown action: {action}"})
                )

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_handler_error")
    finally:
        await manager.disconnect(ws)
