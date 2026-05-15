import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SCHEDULER_DISABLED", "1")
os.environ.setdefault("APP_ENV", "test")
# Default audit signing key for tests — fail-closed audit emission requires
# AUDIT_SIGNING_KEY to be a non-empty value. Individual tests may override
# (or unset) this within their own fixtures to exercise the fail-closed path.
os.environ.setdefault("AUDIT_SIGNING_KEY", "test-signing-key-for-audit-hmac")
os.environ.setdefault(
    "JWT_ISSUER",
    "https://login.microsoftonline.com/e75d5f00-51bd-48c1-adb6-b5df988e2685/v2.0",
)
os.environ.setdefault("JWT_AUDIENCE", "api://1d998abb-bc8e-404c-8bec-727de859c8c4")
os.environ.setdefault(
    "JWKS_URL",
    "https://login.microsoftonline.com/e75d5f00-51bd-48c1-adb6-b5df988e2685/discovery/v2.0/keys",
)
# Low rate limits for testability (per-endpoint, reset between tests)
os.environ.setdefault("RATE_LIMIT_MUTATION", "5/minute")
os.environ.setdefault("RATE_LIMIT_SCRAPING", "5/minute")

from app.core.auth import _ANONYMOUS_USER, get_current_user
from app.core.database import engine, SessionLocal
from app.core.rate_limit import limiter
from app.main import app
from app.models.base import Base
from app import models as _models


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    """Clear all rate-limit counters between tests."""
    limiter.reset()
    yield


@pytest.fixture(autouse=True)
def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: _ANONYMOUS_USER
    return _DefaultCommodityTestClient(app)


class _DefaultCommodityTestClient(TestClient):
    """Preserve legacy order fixtures after commodity became required."""

    def post(self, url, *args, **kwargs):  # type: ignore[no-untyped-def]
        json_payload = kwargs.get("json")
        if (
            url in {"/orders/sales", "/orders/purchase"}
            and isinstance(json_payload, dict)
            and "commodity" not in json_payload
        ):
            json_payload = dict(json_payload)
            if json_payload.pop("__skip_default_commodity", False):
                kwargs["json"] = json_payload
            else:
                json_payload["commodity"] = "ALUMINUM"
                kwargs["json"] = json_payload
        return super().post(url, *args, **kwargs)


@pytest.fixture()
def session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _clear_webhook_dedup():
    """Clear webhook processor dedup state between tests.

    The module-level ``_seen_set`` and ``_seen_message_ids`` in
    ``webhook_processor`` persist across tests, causing false
    ``webhook_duplicate_skipped`` when tests reuse message IDs
    like ``wamid.test123``.
    """
    from app.services.webhook_processor import (
        _active_durable_message_ids,
        _message_queue,
        _seen_message_ids,
        _seen_set,
    )

    _active_durable_message_ids.clear()
    _seen_set.clear()
    _seen_message_ids.clear()
    _message_queue.clear()
    yield
    _active_durable_message_ids.clear()
    _seen_set.clear()
    _seen_message_ids.clear()
    _message_queue.clear()


@pytest.fixture(autouse=True)
def mock_whatsapp(request):
    """Mock WhatsApp service to always succeed in tests.

    Without this, WhatsApp sends fail (no access token) and RFQs
    stay in CREATED instead of transitioning to SENT.

    Tests that need the real WhatsApp service (e.g. unit tests for
    WhatsAppService itself) can opt out with:
        @pytest.mark.no_mock_whatsapp
    """
    if "no_mock_whatsapp" in {m.name for m in request.node.iter_markers()}:
        yield
        return

    from unittest.mock import patch
    from app.schemas.whatsapp import WhatsAppSendResult

    def _mock_send(phone: str, text: str) -> WhatsAppSendResult:
        return WhatsAppSendResult(
            success=True,
            provider_message_id=f"mock-{phone}",
        )

    with patch.object(
        __import__(
            "app.services.whatsapp_service", fromlist=["WhatsAppService"]
        ).WhatsAppService,
        "send_text_message",
        staticmethod(_mock_send),
    ):
        yield
