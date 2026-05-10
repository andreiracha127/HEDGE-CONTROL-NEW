from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.services.webhook_processor import drain_queue


MIGRATION_040_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "040_a4_inbound_webhook_delivery.py"
)
MIGRATION_041_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "041_a4_inbound_webhook_messages.py"
)


def _meta_payload(
    *,
    message_id: str = "wamid.a4",
    from_phone: str = "+5511999990001",
    text: str = "RFQ#123 2450 USD/MT",
) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {"wa_id": from_phone, "profile": {"name": "Trader"}}
                            ],
                            "messages": [
                                {
                                    "from": from_phone,
                                    "id": message_id,
                                    "timestamp": "1760000000",
                                    "text": {"body": text},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ]
            }
        ],
    }


def _sign_meta(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _twilio_signature(token: str, url: str, params: dict[str, str]) -> str:
    data = url + "".join(key + params[key] for key in sorted(params))
    digest = hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()
    return b64encode(digest).decode()


def _load_migration_040():
    spec = importlib.util.spec_from_file_location("migration_040", MIGRATION_040_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _run_migration_040(connection: sa.Connection, direction: str) -> None:
    migration = _load_migration_040()
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(migration, direction)()


def _load_migration_041():
    spec = importlib.util.spec_from_file_location("migration_041", MIGRATION_041_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _run_migration_041(connection: sa.Connection, direction: str) -> None:
    migration = _load_migration_041()
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(migration, direction)()


def _latest_delivery():
    from app.models.inbound_webhook_delivery import InboundWebhookDelivery

    with SessionLocal() as session:
        return (
            session.query(InboundWebhookDelivery)
            .order_by(InboundWebhookDelivery.received_at.desc())
            .first()
        )


def _latest_message():
    from app.models.inbound_webhook_message import InboundWebhookMessage

    with SessionLocal() as session:
        return (
            session.query(InboundWebhookMessage)
            .order_by(InboundWebhookMessage.created_at.desc())
            .first()
        )


def test_model_rejects_provider_raw_and_signature_base_url_invariants() -> None:
    from app.models.inbound_webhook_delivery import InboundWebhookDelivery

    with pytest.raises(ValueError, match="Meta deliveries require raw_body"):
        InboundWebhookDelivery(
            provider="meta",
            raw_body=None,
            raw_form=None,
            headers={},
            signature_present=False,
            signature_verified=False,
            signature_status="bypassed",
            parse_status="received",
        )

    with pytest.raises(
        ValueError,
        match="Twilio deliveries require raw_form and must not set raw_body",
    ):
        InboundWebhookDelivery(
            provider="twilio",
            raw_body="{}",
            raw_form={},
            headers={},
            signature_base_url="https://example.com/webhooks/whatsapp",
            signature_present=True,
            signature_verified=True,
            signature_status="verified",
            parse_status="received",
        )

    with pytest.raises(ValueError, match="Twilio deliveries require signature_base_url"):
        InboundWebhookDelivery(
            provider="twilio",
            raw_body=None,
            raw_form={"Body": "hi"},
            headers={},
            signature_present=True,
            signature_verified=True,
            signature_status="verified",
            parse_status="received",
        )

    with pytest.raises(ValueError, match="Meta deliveries must not set signature_base_url"):
        InboundWebhookDelivery(
            provider="meta",
            raw_body="{}",
            raw_form=None,
            headers={},
            signature_base_url="https://example.com/webhooks/whatsapp",
            signature_present=True,
            signature_verified=True,
            signature_status="verified",
            parse_status="received",
        )


def test_model_rejects_parse_status_message_count_invariants() -> None:
    from app.models.inbound_webhook_delivery import InboundWebhookDelivery

    with pytest.raises(ValueError, match="messages_extracted must be NULL"):
        InboundWebhookDelivery(
            provider="meta",
            raw_body="{}",
            raw_form=None,
            headers={},
            signature_present=False,
            signature_verified=False,
            signature_status="bypassed",
            parse_status="received",
            messages_extracted=0,
        )

    with pytest.raises(ValueError, match="parsed deliveries require messages_extracted"):
        InboundWebhookDelivery(
            provider="meta",
            raw_body="{}",
            raw_form=None,
            headers={},
            signature_present=False,
            signature_verified=False,
            signature_status="bypassed",
            parse_status="parsed",
            messages_extracted=None,
        )


@patch("app.api.routes.webhooks._process_queue_in_background")
def test_meta_production_without_secret_fails_closed_even_on_sqlite(
    _mock_bg: MagicMock, client: TestClient
) -> None:
    drain_queue()
    with patch.dict(
        "os.environ",
        {
            "APP_ENV": "production",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "WHATSAPP_PROVIDER": "meta",
            "WHATSAPP_APP_SECRET": "",
        },
    ):
        resp = client.post("/webhooks/whatsapp", json=_meta_payload())

    assert resp.status_code == 403
    assert drain_queue() == []


@patch("app.api.routes.webhooks._process_queue_in_background")
def test_meta_test_env_without_secret_persists_bypassed_delivery_before_enqueue(
    _mock_bg: MagicMock, client: TestClient
) -> None:
    drain_queue()
    payload = _meta_payload(message_id="wamid.bypass")
    with patch.dict(
        "os.environ",
        {"APP_ENV": "test", "WHATSAPP_PROVIDER": "meta", "WHATSAPP_APP_SECRET": ""},
    ):
        resp = client.post("/webhooks/whatsapp", json=payload)

    assert resp.status_code == 200
    delivery = _latest_delivery()
    assert delivery is not None
    assert delivery.provider == "meta"
    assert delivery.signature_status == "bypassed"
    assert delivery.parse_status == "parsed"
    assert delivery.messages_extracted == 1
    assert delivery.provider_message_id == "wamid.bypass"
    assert delivery.raw_body is not None
    assert delivery.raw_form is None
    assert delivery.acknowledged_at is not None
    queued = drain_queue()
    assert len(queued) == 1
    message = _latest_message()
    assert message is not None
    assert message.delivery_id == delivery.id
    assert message.provider == "meta"
    assert message.provider_message_id == "wamid.bypass"
    assert message.processing_status == "received"
    assert queued[0].delivery_message_id == message.id


@patch("app.api.routes.webhooks._process_queue_in_background")
def test_valid_signed_meta_delivery_is_persisted_before_enqueue(
    _mock_bg: MagicMock, client: TestClient
) -> None:
    drain_queue()
    payload = _meta_payload(message_id="wamid.signed")
    body = json.dumps(payload).encode()
    signature = _sign_meta(body, "meta-secret")

    with patch.dict(
        "os.environ",
        {
            "APP_ENV": "production",
            "WHATSAPP_PROVIDER": "meta",
            "WHATSAPP_APP_SECRET": "meta-secret",
        },
    ):
        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        )

    assert resp.status_code == 200
    delivery = _latest_delivery()
    assert delivery is not None
    assert delivery.signature_present is True
    assert delivery.signature_verified is True
    assert delivery.signature_status == "verified"
    assert delivery.provider_message_id == "wamid.signed"
    queued = drain_queue()
    assert len(queued) == 1
    message = _latest_message()
    assert message is not None
    assert message.provider_message_id == "wamid.signed"
    assert queued[0].delivery_message_id == message.id


@patch("app.api.routes.webhooks._process_queue_in_background")
def test_valid_signed_twilio_delivery_persists_signature_base_url_override(
    _mock_bg: MagicMock, client: TestClient
) -> None:
    drain_queue()
    form = {
        "MessageSid": "SMa4",
        "From": "whatsapp:+5511999990001",
        "To": "whatsapp:+14155238886",
        "Body": "RFQ#123 2450 USD/MT",
        "ProfileName": "Trader",
    }
    base_url = "https://hooks.example.com/twilio/whatsapp"
    signature = _twilio_signature("twilio-secret", base_url, form)

    with patch.dict(
        "os.environ",
        {
            "APP_ENV": "production",
            "WHATSAPP_PROVIDER": "twilio",
            "TWILIO_AUTH_TOKEN": "twilio-secret",
            "TWILIO_WEBHOOK_URL": base_url,
        },
    ):
        resp = client.post(
            "/webhooks/whatsapp",
            data=form,
            headers={"X-Twilio-Signature": signature},
        )

    assert resp.status_code == 200
    delivery = _latest_delivery()
    assert delivery is not None
    assert delivery.provider == "twilio"
    assert delivery.raw_body is None
    assert delivery.raw_form == form
    assert delivery.signature_base_url == base_url
    assert delivery.signature_status == "verified"
    assert delivery.provider_message_id == "SMa4"
    assert delivery.sender_phone == "+5511999990001"
    queued = drain_queue()
    assert len(queued) == 1
    message = _latest_message()
    assert message is not None
    assert message.provider == "twilio"
    assert message.provider_message_id == "SMa4"
    assert queued[0].delivery_message_id == message.id


@patch("app.api.routes.webhooks._process_queue_in_background")
def test_twilio_production_without_token_fails_closed(
    _mock_bg: MagicMock, client: TestClient
) -> None:
    drain_queue()
    with patch.dict(
        "os.environ",
        {
            "APP_ENV": "production",
            "WHATSAPP_PROVIDER": "twilio",
            "TWILIO_AUTH_TOKEN": "",
        },
    ):
        resp = client.post(
            "/webhooks/whatsapp",
            data={"MessageSid": "SMmissing", "From": "whatsapp:+55", "Body": "hi"},
        )

    assert resp.status_code == 403
    assert drain_queue() == []


@patch("app.api.routes.webhooks._process_queue_in_background")
def test_missing_and_invalid_configured_signatures_do_not_enqueue(
    _mock_bg: MagicMock, client: TestClient
) -> None:
    drain_queue()
    with patch.dict(
        "os.environ",
        {
            "APP_ENV": "production",
            "WHATSAPP_PROVIDER": "meta",
            "WHATSAPP_APP_SECRET": "secret",
        },
    ):
        assert client.post("/webhooks/whatsapp", json=_meta_payload()).status_code == 403
        assert (
            client.post(
                "/webhooks/whatsapp",
                content=json.dumps(_meta_payload()).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": "sha256=bad",
                },
            ).status_code
            == 403
        )

    with patch.dict(
        "os.environ",
        {
            "APP_ENV": "production",
            "WHATSAPP_PROVIDER": "twilio",
            "TWILIO_AUTH_TOKEN": "secret",
        },
    ):
        assert (
            client.post(
                "/webhooks/whatsapp",
                data={"MessageSid": "SMbad", "From": "whatsapp:+55", "Body": "hi"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/webhooks/whatsapp",
                data={"MessageSid": "SMbad", "From": "whatsapp:+55", "Body": "hi"},
                headers={"X-Twilio-Signature": "bad"},
            ).status_code
            == 403
        )

    assert drain_queue() == []


def test_malformed_meta_json_preserves_parse_failed_delivery(client: TestClient) -> None:
    body = b'{"entry": ['
    signature = _sign_meta(body, "meta-secret")
    with patch.dict(
        "os.environ",
        {
            "APP_ENV": "production",
            "WHATSAPP_PROVIDER": "meta",
            "WHATSAPP_APP_SECRET": "meta-secret",
        },
    ):
        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        )

    assert resp.status_code == 400
    delivery = _latest_delivery()
    assert delivery is not None
    assert delivery.parse_status == "parse_failed"
    assert delivery.messages_extracted is None
    assert delivery.acknowledged_at is None


def test_040_migration_roundtrip_creates_and_drops_delivery_table() -> None:
    migration = _load_migration_040()
    assert migration.revision == "040_a4_inbound_webhook_delivery"
    assert migration.down_revision == "039_a3_cashflow_baseline_archive"

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _run_migration_040(connection, "upgrade")
        inspector = sa.inspect(connection)
        assert "inbound_webhook_deliveries" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("inbound_webhook_deliveries")}
        assert {
            "id",
            "provider",
            "provider_message_id",
            "sender_phone",
            "raw_body",
            "raw_form",
            "headers",
            "signature_base_url",
            "signature_present",
            "signature_verified",
            "signature_status",
            "parse_status",
            "messages_extracted",
            "received_at",
            "acknowledged_at",
        }.issubset(columns)

        _run_migration_040(connection, "downgrade")
        assert "inbound_webhook_deliveries" not in sa.inspect(connection).get_table_names()


def test_041_migration_roundtrip_creates_unique_message_table() -> None:
    migration = _load_migration_041()
    assert migration.revision == "041_a4_inbound_webhook_messages"
    assert migration.down_revision == "040_a4_inbound_webhook_delivery"

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _run_migration_040(connection, "upgrade")
        _run_migration_041(connection, "upgrade")
        inspector = sa.inspect(connection)
        assert "inbound_webhook_messages" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("inbound_webhook_messages")}
        assert {
            "id",
            "delivery_id",
            "provider",
            "provider_message_id",
            "sender_phone",
            "sender_name",
            "timestamp",
            "text",
            "processing_status",
            "processing_started_at",
            "processing_completed_at",
            "processing_result",
            "rfq_number",
            "rfq_id",
            "quote_id",
            "created_at",
        }.issubset(columns)
        uniques = inspector.get_unique_constraints("inbound_webhook_messages")
        assert any(
            set(unique["column_names"]) == {"provider", "provider_message_id"}
            for unique in uniques
        )

        _run_migration_041(connection, "downgrade")
        assert "inbound_webhook_messages" not in sa.inspect(connection).get_table_names()


def test_message_model_enforces_processing_status_and_provider_message_id() -> None:
    from app.models.inbound_webhook_delivery import InboundWebhookDelivery
    from app.models.inbound_webhook_message import InboundWebhookMessage

    with SessionLocal() as session:
        delivery = InboundWebhookDelivery(
            provider="meta",
            raw_body="{}",
            raw_form=None,
            headers={},
            signature_present=False,
            signature_verified=False,
            signature_status="bypassed",
            parse_status="parsed",
            messages_extracted=1,
        )
        session.add(delivery)
        session.flush()

        with pytest.raises(ValueError, match="processing_status must be one of"):
            InboundWebhookMessage(
                delivery_id=delivery.id,
                provider="meta",
                provider_message_id="wamid.status",
                sender_phone="+5511999990001",
                timestamp=None,
                text="RFQ#RFQ-2026-000001 2550 USD/MT",
                processing_status="bad",
            )


def test_message_unique_provider_message_id_is_database_enforced() -> None:
    from sqlalchemy.exc import IntegrityError

    from app.models.inbound_webhook_delivery import InboundWebhookDelivery
    from app.models.inbound_webhook_message import InboundWebhookMessage

    with SessionLocal() as session:
        delivery = InboundWebhookDelivery(
            provider="meta",
            raw_body="{}",
            raw_form=None,
            headers={},
            signature_present=False,
            signature_verified=False,
            signature_status="bypassed",
            parse_status="parsed",
            messages_extracted=1,
        )
        session.add(delivery)
        session.flush()

        for _ in range(2):
            session.add(
                InboundWebhookMessage(
                    delivery_id=delivery.id,
                    provider="meta",
                    provider_message_id="wamid.unique",
                    sender_phone="+5511999990001",
                    sender_name="Trader",
                    timestamp=datetime.now(timezone.utc),
                    text="RFQ#RFQ-2026-000001 2550 USD/MT",
                    processing_status="received",
                )
            )

        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        with pytest.raises(ValueError, match="provider_message_id must be non-empty"):
            InboundWebhookMessage(
                delivery_id=delivery.id,
                provider="meta",
                provider_message_id="",
                sender_phone="+5511999990001",
                timestamp=None,
                text="RFQ#RFQ-2026-000001 2550 USD/MT",
                processing_status="received",
            )


@patch("app.api.routes.webhooks._process_queue_in_background")
def test_terminal_consumed_redelivery_does_not_enqueue(
    _mock_bg: MagicMock, client: TestClient
) -> None:
    from app.models.inbound_webhook_message import InboundWebhookMessage

    drain_queue()
    payload = _meta_payload(message_id="wamid.consumed")
    with patch.dict(
        "os.environ",
        {"APP_ENV": "test", "WHATSAPP_PROVIDER": "meta", "WHATSAPP_APP_SECRET": ""},
    ):
        assert client.post("/webhooks/whatsapp", json=payload).status_code == 200

    first = _latest_message()
    assert first is not None
    with SessionLocal() as session:
        durable = session.get(InboundWebhookMessage, first.id)
        assert durable is not None
        durable.processing_status = "processed"
        durable.processing_result = {"status": "auto_quote_created"}
        session.commit()

    drain_queue()
    with patch.dict(
        "os.environ",
        {"APP_ENV": "test", "WHATSAPP_PROVIDER": "meta", "WHATSAPP_APP_SECRET": ""},
    ):
        assert client.post("/webhooks/whatsapp", json=payload).status_code == 200

    # Background processing is mocked in this test, so any queued item would
    # remain observable here.
    assert drain_queue() == []
    with SessionLocal() as session:
        rows = (
            session.query(InboundWebhookMessage)
            .filter(InboundWebhookMessage.provider_message_id == "wamid.consumed")
            .all()
        )
    assert len(rows) == 1


@patch("app.api.routes.webhooks._process_queue_in_background")
def test_unconsumed_redelivery_recovers_existing_durable_message(
    _mock_bg: MagicMock, client: TestClient
) -> None:
    from app.models.inbound_webhook_message import InboundWebhookMessage

    drain_queue()
    payload = _meta_payload(message_id="wamid.retry")
    with patch.dict(
        "os.environ",
        {"APP_ENV": "test", "WHATSAPP_PROVIDER": "meta", "WHATSAPP_APP_SECRET": ""},
    ):
        assert client.post("/webhooks/whatsapp", json=payload).status_code == 200

    first = _latest_message()
    assert first is not None
    drain_queue()
    with SessionLocal() as session:
        durable = session.get(InboundWebhookMessage, first.id)
        assert durable is not None
        durable.processing_status = "failed"
        durable.processing_result = {"status": "llm_unavailable"}
        session.commit()

    with patch.dict(
        "os.environ",
        {"APP_ENV": "test", "WHATSAPP_PROVIDER": "meta", "WHATSAPP_APP_SECRET": ""},
    ):
        assert client.post("/webhooks/whatsapp", json=payload).status_code == 200

    queued = drain_queue()
    assert len(queued) == 1
    assert queued[0].delivery_message_id == first.id
    with SessionLocal() as session:
        assert (
            session.query(InboundWebhookMessage)
            .filter(InboundWebhookMessage.provider_message_id == "wamid.retry")
            .count()
            == 1
        )


@patch("app.api.routes.webhooks._process_queue_in_background")
def test_stale_processing_redelivery_recovers_existing_durable_message(
    _mock_bg: MagicMock, client: TestClient
) -> None:
    from app.models.inbound_webhook_message import InboundWebhookMessage

    drain_queue()
    payload = _meta_payload(message_id="wamid.stale")
    with patch.dict(
        "os.environ",
        {"APP_ENV": "test", "WHATSAPP_PROVIDER": "meta", "WHATSAPP_APP_SECRET": ""},
    ):
        assert client.post("/webhooks/whatsapp", json=payload).status_code == 200

    first = _latest_message()
    assert first is not None
    drain_queue()
    with SessionLocal() as session:
        durable = session.get(InboundWebhookMessage, first.id)
        assert durable is not None
        durable.processing_status = "processing"
        durable.processing_started_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.commit()

    with patch.dict(
        "os.environ",
        {"APP_ENV": "test", "WHATSAPP_PROVIDER": "meta", "WHATSAPP_APP_SECRET": ""},
    ):
        assert client.post("/webhooks/whatsapp", json=payload).status_code == 200

    queued = drain_queue()
    assert len(queued) == 1
    assert queued[0].delivery_message_id == first.id
    with SessionLocal() as session:
        durable = session.get(InboundWebhookMessage, first.id)
        assert durable is not None
        assert durable.processing_status == "received"
        assert durable.processing_started_at is None


@patch("app.api.routes.webhooks._process_queue_in_background")
def test_completed_processing_redelivery_is_not_reopened(
    _mock_bg: MagicMock, client: TestClient
) -> None:
    from app.models.inbound_webhook_message import InboundWebhookMessage

    drain_queue()
    payload = _meta_payload(message_id="wamid.completed")
    with patch.dict(
        "os.environ",
        {"APP_ENV": "test", "WHATSAPP_PROVIDER": "meta", "WHATSAPP_APP_SECRET": ""},
    ):
        assert client.post("/webhooks/whatsapp", json=payload).status_code == 200

    first = _latest_message()
    assert first is not None
    drain_queue()
    completed_at = datetime.now(timezone.utc)
    with SessionLocal() as session:
        durable = session.get(InboundWebhookMessage, first.id)
        assert durable is not None
        durable.processing_status = "processing"
        durable.processing_started_at = completed_at - timedelta(hours=1)
        durable.processing_completed_at = completed_at
        session.commit()

    with patch.dict(
        "os.environ",
        {"APP_ENV": "test", "WHATSAPP_PROVIDER": "meta", "WHATSAPP_APP_SECRET": ""},
    ):
        assert client.post("/webhooks/whatsapp", json=payload).status_code == 200

    # Background processing is mocked in this test, so any queued item would
    # remain observable here.
    assert drain_queue() == []
    with SessionLocal() as session:
        durable = session.get(InboundWebhookMessage, first.id)
        assert durable is not None
        assert durable.processing_status == "processing"
        assert durable.processing_completed_at is not None
