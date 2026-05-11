"""Tests for audit trail HMAC signature (Item 2.4).

Validates:
* With AUDIT_SIGNING_KEY set, recorded events include a valid HMAC-SHA256 signature.
* Without the key, ``AuditTrailService.record`` raises ``MissingAuditSigningKey``
  (fail-closed) — see PR-7 / J-A1-02.
* GET /audit/events/{id}/verify validates signatures correctly.
* Tampered checksums are detected.
"""

from __future__ import annotations

import hashlib
import os
import uuid

import pytest
from fastapi import status

from app.models.audit import AuditEvent
from app.services.audit_trail_service import (
    AuditTrailService,
    MissingAuditSigningKey,
    _get_signing_key,
    _reset_signing_key_cache,
    compute_signature,
    verify_signature,
)

TEST_KEY = "test-signing-key-for-audit-hmac"


@pytest.fixture(autouse=True)
def _reset_key_cache():
    """Reset the module-level signing-key cache before and after each test."""
    _reset_signing_key_cache()
    # Restore the default test key (conftest sets this via os.environ.setdefault)
    os.environ["AUDIT_SIGNING_KEY"] = TEST_KEY
    yield
    _reset_signing_key_cache()
    # Restore key (don't leak an unset state to other tests).
    os.environ["AUDIT_SIGNING_KEY"] = TEST_KEY


# ── Unit tests for HMAC helpers ───────────────────────────────────────
class TestHMACHelpers:
    def test_compute_and_verify_roundtrip(self) -> None:
        key = TEST_KEY.encode("utf-8")
        checksum = hashlib.sha256(b"some payload").hexdigest()
        sig = compute_signature(checksum, key)
        assert isinstance(sig, bytes)
        assert len(sig) == 32  # SHA-256 → 32 bytes
        assert verify_signature(checksum, sig, key)

    def test_wrong_key_fails_verification(self) -> None:
        key = TEST_KEY.encode("utf-8")
        checksum = hashlib.sha256(b"payload").hexdigest()
        sig = compute_signature(checksum, key)
        assert not verify_signature(checksum, sig, b"wrong-key")

    def test_tampered_checksum_fails_verification(self) -> None:
        key = TEST_KEY.encode("utf-8")
        checksum = hashlib.sha256(b"original").hexdigest()
        sig = compute_signature(checksum, key)
        tampered = hashlib.sha256(b"tampered").hexdigest()
        assert not verify_signature(tampered, sig, key)


# ── Service-level tests ──────────────────────────────────────────────
class TestAuditSignatureService:
    def test_record_with_key_populates_signature(self, session) -> None:
        os.environ["AUDIT_SIGNING_KEY"] = TEST_KEY
        event = AuditTrailService.record(
            session,
            event_id=uuid.uuid4(),
            entity_type="order",
            entity_id=uuid.uuid4(),
            event_type="created",
            payload_raw="{}",
            payload_obj={},
        )
        assert event.signature is not None
        assert len(event.signature) == 32
        # Verify the signature matches the checksum
        key = _get_signing_key()
        assert key is not None
        assert verify_signature(event.checksum, event.signature, key)

    def test_record_without_key_raises_fail_closed(self, session) -> None:
        """Fail-closed: refuse to persist unsigned audit evidence."""
        os.environ.pop("AUDIT_SIGNING_KEY", None)
        _reset_signing_key_cache()
        with pytest.raises(MissingAuditSigningKey):
            AuditTrailService.record(
                session,
                event_id=uuid.uuid4(),
                entity_type="order",
                entity_id=uuid.uuid4(),
                event_type="created",
                payload_raw="{}",
                payload_obj={},
            )

    def test_record_canonicalizes_semantically_identical_json(self, session) -> None:
        os.environ["AUDIT_SIGNING_KEY"] = TEST_KEY

        event_a = AuditTrailService.record(
            session,
            event_id=uuid.uuid4(),
            entity_type="order",
            entity_id=uuid.uuid4(),
            event_type="created",
            payload_raw='{"b":1,"nested":{"y":2,"x":1},"a":2}',
            payload_obj={"b": 1, "nested": {"y": 2, "x": 1}, "a": 2},
        )
        event_b = AuditTrailService.record(
            session,
            event_id=uuid.uuid4(),
            entity_type="order",
            entity_id=uuid.uuid4(),
            event_type="created",
            payload_raw='{\n  "a": 2,\n  "nested": {"x": 1, "y": 2},\n  "b": 1\n}',
            payload_obj={"a": 2, "nested": {"x": 1, "y": 2}, "b": 1},
        )

        assert event_a.checksum == event_b.checksum
        assert event_a.payload_canonical == event_b.payload_canonical
        assert (
            event_a.payload_canonical
            == '{"a":2,"b":1,"nested":{"x":1,"y":2}}'
        )


# ── Endpoint tests ────────────────────────────────────────────────────
class TestAuditVerifyEndpoint:
    def test_verify_valid_signature(self, client) -> None:
        os.environ["AUDIT_SIGNING_KEY"] = TEST_KEY
        # Create an order to trigger an audit event
        resp = client.post(
            "/orders/sales", json={"price_type": "variable", "quantity_mt": 5.0}
        )
        assert resp.status_code == status.HTTP_201_CREATED
        order_id = resp.json()["id"]

        # Fetch the audit event
        events_resp = client.get(
            "/audit/events", params={"entity_type": "order", "entity_id": order_id}
        )
        assert events_resp.status_code == 200
        events = events_resp.json()["events"]
        assert len(events) >= 1
        event_id = events[0]["id"]

        # Verify
        verify_resp = client.get(f"/audit/events/{event_id}/verify")
        assert verify_resp.status_code == 200
        body = verify_resp.json()
        assert body["valid"] is True
        assert body["event_id"] == event_id

    def test_verify_nonexistent_event_404(self, client) -> None:
        os.environ["AUDIT_SIGNING_KEY"] = TEST_KEY
        resp = client.get(f"/audit/events/{uuid.uuid4()}/verify")
        assert resp.status_code == 404

    def test_verify_payload_tamper_fails(self, client, session) -> None:
        os.environ["AUDIT_SIGNING_KEY"] = TEST_KEY
        event = AuditTrailService.record(
            session,
            event_id=uuid.uuid4(),
            entity_type="order",
            entity_id=uuid.uuid4(),
            event_type="created",
            payload_raw='{"a":1}',
            payload_obj={"a": 1},
        )
        event.payload = {"a": 999}
        session.commit()

        verify_resp = client.get(f"/audit/events/{event.id}/verify")
        assert verify_resp.status_code == 200
        body = verify_resp.json()
        assert body["valid"] is False
        assert "payload" in body["detail"].lower()

    def test_verify_checksum_tamper_fails(self, client, session) -> None:
        os.environ["AUDIT_SIGNING_KEY"] = TEST_KEY
        event = AuditTrailService.record(
            session,
            event_id=uuid.uuid4(),
            entity_type="order",
            entity_id=uuid.uuid4(),
            event_type="created",
            payload_raw='{"a":1}',
            payload_obj={"a": 1},
        )
        event.checksum = hashlib.sha256(b"tampered").hexdigest()
        session.commit()

        verify_resp = client.get(f"/audit/events/{event.id}/verify")
        assert verify_resp.status_code == 200
        body = verify_resp.json()
        assert body["valid"] is False
        assert "checksum" in body["detail"].lower()

    def test_verify_signature_tamper_fails(self, client, session) -> None:
        os.environ["AUDIT_SIGNING_KEY"] = TEST_KEY
        event = AuditTrailService.record(
            session,
            event_id=uuid.uuid4(),
            entity_type="order",
            entity_id=uuid.uuid4(),
            event_type="created",
            payload_raw='{"a":1}',
            payload_obj={"a": 1},
        )
        event.signature = b"\x00" * 32
        session.commit()

        verify_resp = client.get(f"/audit/events/{event.id}/verify")
        assert verify_resp.status_code == 200
        body = verify_resp.json()
        assert body["valid"] is False
        assert "signature" in body["detail"].lower()

    def test_verify_legacy_row_without_canonical_payload_is_unverifiable(
        self, client, session
    ) -> None:
        os.environ["AUDIT_SIGNING_KEY"] = TEST_KEY
        key = _get_signing_key()
        assert key is not None
        legacy_checksum = hashlib.sha256(b'{\n  "a": 1\n}').hexdigest()
        legacy_event = AuditEvent(
            id=uuid.uuid4(),
            entity_type="order",
            entity_id=uuid.uuid4(),
            event_type="created",
            payload={"a": 1},
            payload_canonical=None,
            checksum=legacy_checksum,
            signature=compute_signature(legacy_checksum, key),
        )
        session.add(legacy_event)
        session.commit()

        verify_resp = client.get(f"/audit/events/{legacy_event.id}/verify")
        assert verify_resp.status_code == 200
        body = verify_resp.json()
        assert body["valid"] is False
        assert "legacy" in body["detail"].lower()

    def test_mutation_without_key_fails_closed(self, client) -> None:
        """Fail-closed: a mutation with no signing key returns 5xx
        (server-side ``MissingAuditSigningKey``) and persists no audit row."""
        os.environ.pop("AUDIT_SIGNING_KEY", None)
        _reset_signing_key_cache()
        resp = client.post(
            "/orders/sales", json={"price_type": "variable", "quantity_mt": 5.0}
        )
        # Without a signing key, the audit emission raises and the mutation
        # is rolled back; route surfaces a 5xx.
        assert resp.status_code >= 500
