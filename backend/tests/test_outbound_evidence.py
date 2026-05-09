"""Phase A2 PR-4 — outbound evidence + canonical id (J-A2-05/07/08/OPUS-02).

Closes:

- J-A2-05: every RFQ outbound carries the canonical id ``RFQ#<rfq_number>``.
- J-A2-07: outbox rows are DURABLY committed before any WhatsApp send.
- J-A2-08: rejected quotes are preserved as evidence (state, not delete);
  rejected rows are excluded from ranking and latest-quote selection.
- J-A2-OPUS-02: action messages (refresh, reject_quote, notify_award,
  notify_reject) are persisted as ``RFQInvitation`` rows with the
  appropriate ``purpose``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from app.core.database import SessionLocal
from app.core.utils import now_utc
from app.models.counterparty import Counterparty, CounterpartyType
from app.models.quotes import QuoteState, RFQQuote
from app.models.rfqs import (
    RFQ,
    RFQDirection,
    RFQIntent,
    RFQInvitation,
    RFQInvitationChannel,
    RFQInvitationPurpose,
    RFQInvitationStatus,
    RFQState,
    RFQStateEvent,
)
from app.schemas.rfq import RFQRead
from app.schemas.whatsapp import WhatsAppSendResult
from app.services.rfq_orchestrator import RFQOrchestrator
from app.services.rfq_service import prefix_with_canonical_id


# ── helpers ──────────────────────────────────────────────────────────────


def _create_counterparty(
    client, name: str = "CP-A", phone: str = "+5511999990001"
) -> str:
    resp = client.post(
        "/counterparties",
        json={
            "type": "broker",
            "name": name,
            "country": "BRA",
            "whatsapp_phone": phone,
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _create_global_rfq(client, cp_ids: list[str]) -> dict:
    resp = client.post(
        "/rfqs",
        json={
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": "5.000",
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id} for cp_id in cp_ids],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_quote(client, rfq_id: str, cp_id: str, price: str = "100.000") -> dict:
    resp = client.post(
        f"/rfqs/{rfq_id}/quotes",
        json={
            "rfq_id": rfq_id,
            "counterparty_id": cp_id,
            "fixed_price_value": price,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── §3.1 prefix_with_canonical_id helper unit tests ──────────────────────


def test_prefix_with_canonical_id_prepends_when_missing() -> None:
    assert (
        prefix_with_canonical_id("Hello", "RFQ-2026-000001")
        == "RFQ#RFQ-2026-000001 — Hello"
    )


def test_prefix_with_canonical_id_idempotent() -> None:
    body = "RFQ#RFQ-2026-000001 — Hello"
    assert prefix_with_canonical_id(body, "RFQ-2026-000001") == body


def test_prefix_with_canonical_id_handles_existing_prefix_with_whitespace() -> None:
    body = "   RFQ#RFQ-2026-000001 — Hello"
    assert prefix_with_canonical_id(body, "RFQ-2026-000001") == body


# ── J-A2-05: every persisted RFQInvitation carries RFQ#<rfq_number> ─────


def test_create_rfq_invitation_body_contains_canonical_id(client) -> None:
    cp_a = _create_counterparty(client, "CP-A", "+5511999990001")
    cp_b = _create_counterparty(client, "CP-B", "+5511999990002")
    rfq = _create_global_rfq(client, [cp_a, cp_b])

    rfq_number = rfq["rfq_number"]
    expected_prefix = f"RFQ#{rfq_number}"
    assert len(rfq["invitations"]) == 2
    for inv in rfq["invitations"]:
        assert inv["message_body"].startswith(expected_prefix), inv["message_body"]
        assert inv["purpose"] == "rfq_invite"


def test_refresh_invitation_body_contains_canonical_id(client) -> None:
    cp_id = _create_counterparty(client)
    rfq = _create_global_rfq(client, [cp_id])
    rfq_number = rfq["rfq_number"]

    resp = client.post(
        f"/rfqs/{rfq['id']}/actions/refresh", json={"user_id": "U1"}
    )
    assert resp.status_code == 200
    refreshed = resp.json()
    refresh_invitations = [
        i for i in refreshed["invitations"] if i["purpose"] == "refresh"
    ]
    assert refresh_invitations, "refresh did not persist any RFQInvitation"
    for inv in refresh_invitations:
        assert inv["message_body"].startswith(f"RFQ#{rfq_number}")


def test_refresh_counterparty_invitation_body_contains_canonical_id(
    client,
) -> None:
    cp_id = _create_counterparty(client)
    rfq = _create_global_rfq(client, [cp_id])
    rfq_number = rfq["rfq_number"]

    resp = client.post(
        f"/rfqs/{rfq['id']}/actions/refresh-counterparty",
        json={"user_id": "U1", "counterparty_id": cp_id},
    )
    assert resp.status_code == 200, resp.text
    refreshed = resp.json()
    refresh_invitations = [
        i for i in refreshed["invitations"] if i["purpose"] == "refresh"
    ]
    assert refresh_invitations
    assert refresh_invitations[-1]["message_body"].startswith(f"RFQ#{rfq_number}")


# ── J-A2-07: durable outbox — failed send does NOT roll back the RFQ ───


def test_create_failed_send_does_not_rollback_rfq_and_persists_failure_reason(
    client,
) -> None:
    cp_id = _create_counterparty(client)

    failure_result = WhatsAppSendResult(
        success=False,
        provider_message_id="",
        error_code="429",
        error_message="rate limited",
    )

    # Replace the autouse mock_whatsapp success path with a failure
    # for this test only. The autouse fixture patches the static
    # method; re-patch on top.
    with patch(
        "app.services.rfq_service.WhatsAppService.send_text_message",
        return_value=failure_result,
    ):
        rfq = _create_global_rfq(client, [cp_id])

    # The RFQ must still exist (no rollback) and contain a `failed`
    # invitation row with the failure_reason populated.
    assert rfq["state"] == "CREATED"  # no successful send → no SENT transition
    assert len(rfq["invitations"]) == 1
    inv = rfq["invitations"][0]
    assert inv["send_status"] == "failed"
    assert inv["sent_at"] is None
    assert inv["provider_message_id"] is None
    assert inv["failure_reason"]
    assert "429" in inv["failure_reason"]


def test_outbox_row_durably_committed_before_whatsapp_send(client) -> None:
    """While ``send_text_message`` is being invoked, a FRESH session must
    already be able to find the queued ``RFQInvitation`` row by id.

    This is the §3.2 durability invariant: a flush-only pattern would
    fail this test because the row is rolled back if the enclosing
    transaction does not commit.
    """
    cp_id = _create_counterparty(client)

    captured_ids: list[uuid.UUID] = []

    def _capture(phone: str, text: str) -> WhatsAppSendResult:
        # At this moment a parallel SessionLocal() must already see the
        # queued row(s) for this RFQ.
        with SessionLocal() as readback:
            rows = (
                readback.query(RFQInvitation)
                .filter(RFQInvitation.recipient_phone == phone)
                .all()
            )
            assert rows, (
                "Outbox row not durable at moment of send_text_message — "
                "flush-only pattern detected"
            )
            captured_ids.extend(r.id for r in rows)
        return WhatsAppSendResult(success=True, provider_message_id=f"mock-{phone}")

    with patch(
        "app.services.rfq_service.WhatsAppService.send_text_message",
        side_effect=_capture,
    ):
        _create_global_rfq(client, [cp_id])

    assert captured_ids, "send_text_message was never invoked"


# ── J-A2-08: reject_quote preserves quote evidence + persists outbound ──


def test_reject_quote_preserves_evidence_via_state_not_delete(client) -> None:
    cp_id = _create_counterparty(client)
    rfq = _create_global_rfq(client, [cp_id])
    quote = _create_quote(client, rfq["id"], cp_id, "100.000")

    resp = client.post(
        f"/rfqs/{rfq['id']}/actions/reject-quote?quote_id={quote['id']}",
        json={"user_id": "trader-x"},
    )
    assert resp.status_code == 200, resp.text

    # Quote row still exists with state=rejected + provenance fields set.
    with SessionLocal() as session:
        q = session.get(RFQQuote, uuid.UUID(quote["id"]))
        assert q is not None, "quote was hard-deleted (J-A2-08 violation)"
        assert q.state == QuoteState.rejected
        assert q.rejected_at is not None
        assert q.rejected_reason == "manual_reject"
        assert q.rejected_by == "trader-x"


def test_reject_quote_outbound_persisted_with_canonical_id(client) -> None:
    cp_id = _create_counterparty(client)
    rfq = _create_global_rfq(client, [cp_id])
    quote = _create_quote(client, rfq["id"], cp_id, "100.000")

    resp = client.post(
        f"/rfqs/{rfq['id']}/actions/reject-quote?quote_id={quote['id']}",
        json={"user_id": "trader-x"},
    )
    assert resp.status_code == 200, resp.text
    refreshed = resp.json()

    reject_rows = [
        i for i in refreshed["invitations"] if i["purpose"] == "reject_quote"
    ]
    assert reject_rows, "reject_quote did not persist a purpose=reject_quote row"
    assert reject_rows[-1]["message_body"].startswith(f"RFQ#{rfq['rfq_number']}")


def test_ranking_excludes_rejected_quotes(client) -> None:
    """A rejected quote MUST NOT appear in the trade-ranking population
    even though the row remains in the DB for forensics (J-A2-08).
    """
    cp_a = _create_counterparty(client, "CP-A", "+5511999990001")
    cp_b = _create_counterparty(client, "CP-B", "+5511999990002")
    rfq = _create_global_rfq(client, [cp_a, cp_b])

    qa = _create_quote(client, rfq["id"], cp_a, "100.000")
    _create_quote(client, rfq["id"], cp_b, "110.000")

    # Reject CP-A's quote.
    rej = client.post(
        f"/rfqs/{rfq['id']}/actions/reject-quote?quote_id={qa['id']}",
        json={"user_id": "trader-x"},
    )
    assert rej.status_code == 200, rej.text

    ranking = client.get(f"/rfqs/{rfq['id']}/trade-ranking")
    assert ranking.status_code == 200
    payload = ranking.json()
    # Only CP-B's quote is eligible; ranker therefore sees one row and
    # ranks it position 1.
    assert payload["status"] == "SUCCESS", payload
    assert len(payload["ranking"]) == 1
    assert payload["ranking"][0]["quote"]["counterparty_id"] == cp_b


def test_reject_quote_revert_lands_in_same_checkpoint_as_outbox(client) -> None:
    """Codex P2: when rejecting the LAST active quote, the
    ``ALL_QUOTES_REJECTED`` revert + state event must land in the SAME
    ``session.commit()`` as the rejection + queued outbox row, BEFORE
    the WhatsApp send. A fresh session readback at the moment
    ``send_text_message`` is invoked must already see the RFQ in SENT
    state and the matching state event row.
    """
    cp_id = _create_counterparty(client)
    rfq = _create_global_rfq(client, [cp_id])
    quote = _create_quote(client, rfq["id"], cp_id, "100.000")
    rfq_uuid = uuid.UUID(rfq["id"])

    captured: list[tuple[str, int]] = []

    def _capture(phone: str, text: str) -> WhatsAppSendResult:
        # Recognize the reject body so we only sample the readback for
        # the reject_quote send (other sends, eg create-time invites,
        # would also hit this patch in the same test if any).
        if "Closed here" in text or "Fechamos aqui" in text:
            with SessionLocal() as readback:
                state_event_count = (
                    readback.query(RFQStateEvent)
                    .filter_by(rfq_id=rfq_uuid, reason="ALL_QUOTES_REJECTED")
                    .count()
                )
                rfq_row = readback.get(RFQ, rfq_uuid)
                rfq_state_value = rfq_row.state.value if rfq_row else None
                captured.append((rfq_state_value, state_event_count))
        return WhatsAppSendResult(success=True, provider_message_id=f"mock-{phone}")

    with patch(
        "app.services.rfq_service.WhatsAppService.send_text_message",
        side_effect=_capture,
    ):
        resp = client.post(
            f"/rfqs/{rfq['id']}/actions/reject-quote?quote_id={quote['id']}",
            json={"user_id": "trader-x"},
        )
    assert resp.status_code == 200, resp.text

    assert captured, "reject WhatsApp send was never invoked"
    rfq_state_at_send, event_count_at_send = captured[0]
    assert rfq_state_at_send == "SENT", (
        f"RFQ state at moment of send was {rfq_state_at_send!r}; the "
        "ALL_QUOTES_REJECTED revert must land in the pre-send checkpoint "
        "(Codex P2)."
    )
    assert event_count_at_send == 1, (
        f"Expected ALL_QUOTES_REJECTED state event to be durable at "
        f"moment of send, found {event_count_at_send}."
    )


def test_post_reject_remaining_count_filters_active(client) -> None:
    """When all surviving quotes are rejected, the RFQ must revert to SENT
    via the ``ALL_QUOTES_REJECTED`` state event. The remaining-count query
    must filter on ``state == active`` so a prior soft-rejected row does
    not inflate the count and silently block the revert.
    """
    cp_a = _create_counterparty(client, "CP-A", "+5511999990001")
    cp_b = _create_counterparty(client, "CP-B", "+5511999990002")
    rfq = _create_global_rfq(client, [cp_a, cp_b])

    qa = _create_quote(client, rfq["id"], cp_a, "100.000")
    qb = _create_quote(client, rfq["id"], cp_b, "110.000")

    # Reject CP-A first — there is still CP-B active, so RFQ stays QUOTED.
    r1 = client.post(
        f"/rfqs/{rfq['id']}/actions/reject-quote?quote_id={qa['id']}",
        json={"user_id": "trader-x"},
    )
    assert r1.status_code == 200
    assert r1.json()["state"] == "QUOTED"

    # Reject CP-B — every active quote is now rejected → revert to SENT.
    r2 = client.post(
        f"/rfqs/{rfq['id']}/actions/reject-quote?quote_id={qb['id']}",
        json={"user_id": "trader-x"},
    )
    assert r2.status_code == 200
    assert r2.json()["state"] == "SENT", (
        "All-quotes-rejected revert did not fire — remaining-count likely "
        "did not filter rejected rows."
    )


# ── §3.4 Pydantic read schema follow-through ────────────────────────────


def test_rfq_read_validates_with_queued_invitation_having_null_provider_message_id(
    client,
) -> None:
    """``RFQInvitationRead.provider_message_id`` is now optional; this
    guards against a Pydantic ValidationError on every queued/failed row
    (which is exactly what the durable outbox creates).
    """
    cp_id = _create_counterparty(client)
    rfq = _create_global_rfq(client, [cp_id])

    # Manually demote one invitation to queued + null provider id, then
    # re-validate the embed.
    with SessionLocal() as session:
        inv = (
            session.query(RFQInvitation)
            .filter(RFQInvitation.rfq_id == uuid.UUID(rfq["id"]))
            .first()
        )
        assert inv is not None
        inv.send_status = RFQInvitationStatus.queued
        inv.sent_at = None
        inv.provider_message_id = None
        session.commit()

    # Hit the read route — RFQRead embeds invitations and would 500 if
    # validation failed.
    resp = client.get(f"/rfqs/{rfq['id']}")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["invitations"][0]["provider_message_id"] is None
    # And the Pydantic schema accepts the dict round-trip.
    RFQRead.model_validate(payload)


# ── J-A2-OPUS-02: notify_award + notify_reject persist evidence ─────────


def _seed_rfq_with_invitation(
    session,
    *,
    cp_phone: str = "+5511999990010",
    rfq_number: str = "RFQ-NOTIFY-001",
) -> tuple[RFQ, Counterparty, RFQInvitation]:
    cp = Counterparty(
        type=CounterpartyType.broker,
        name=f"NotifyCP-{uuid.uuid4().hex[:6]}",
        country="BRA",
        whatsapp_phone=cp_phone,
    )
    session.add(cp)
    session.flush()
    rfq = RFQ(
        id=uuid.uuid4(),
        rfq_number=rfq_number,
        intent=RFQIntent.global_position,
        commodity="LME_AL",
        quantity_mt=Decimal("5.000"),
        delivery_window_start=date(2026, 3, 1),
        delivery_window_end=date(2026, 3, 31),
        direction=RFQDirection.buy,
        commercial_active_mt=Decimal("0.000"),
        commercial_passive_mt=Decimal("0.000"),
        commercial_net_mt=Decimal("0.000"),
        commercial_reduction_applied_mt=Decimal("0.000"),
        exposure_snapshot_timestamp=now_utc(),
        state=RFQState.awarded,
    )
    session.add(rfq)
    session.flush()
    inv = RFQInvitation(
        id=uuid.uuid4(),
        rfq_id=rfq.id,
        rfq_number=rfq.rfq_number,
        counterparty_id=cp.id,
        recipient_name=cp.name,
        recipient_phone=cp_phone,
        channel=RFQInvitationChannel.whatsapp,
        message_body="initial",
        provider_message_id="seed",
        send_status=RFQInvitationStatus.sent,
        sent_at=now_utc(),
        idempotency_key=f"seed-{uuid.uuid4()}",
    )
    session.add(inv)
    session.commit()
    return rfq, cp, inv


@patch("app.services.rfq_orchestrator.LLMAgent.generate_outbound_message")
def test_notify_award_persists_evidence_and_prefixes_id(mock_gen) -> None:
    mock_gen.return_value = "Award won."
    with SessionLocal() as session:
        rfq, cp, _ = _seed_rfq_with_invitation(session)
        rfq_id = rfq.id
        rfq_number = rfq.rfq_number

        RFQOrchestrator.notify_award(
            session, rfq, str(cp.id), price=2550.0, unit="USD/MT"
        )
        session.commit()

    with SessionLocal() as readback:
        rows = (
            readback.query(RFQInvitation)
            .filter(
                RFQInvitation.rfq_id == rfq_id,
                RFQInvitation.purpose == RFQInvitationPurpose.award_notify,
            )
            .all()
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.message_body.startswith(f"RFQ#{rfq_number}")
        assert row.send_status == RFQInvitationStatus.sent
        assert row.sent_at is not None


@patch("app.services.rfq_orchestrator.LLMAgent.generate_outbound_message")
def test_notify_reject_persists_one_row_per_recipient(mock_gen) -> None:
    mock_gen.return_value = "Reject."
    with SessionLocal() as session:
        rfq, _, _ = _seed_rfq_with_invitation(
            session, cp_phone="+5511999990011", rfq_number="RFQ-NOTIFY-002"
        )
        # Add a second counterparty + invitation
        cp2 = Counterparty(
            type=CounterpartyType.broker,
            name=f"CP-{uuid.uuid4().hex[:6]}",
            country="BRA",
            whatsapp_phone="+5511999990012",
        )
        session.add(cp2)
        session.flush()
        inv2 = RFQInvitation(
            id=uuid.uuid4(),
            rfq_id=rfq.id,
            rfq_number=rfq.rfq_number,
            counterparty_id=cp2.id,
            recipient_name=cp2.name,
            recipient_phone="+5511999990012",
            channel=RFQInvitationChannel.whatsapp,
            message_body="initial",
            provider_message_id="seed",
            send_status=RFQInvitationStatus.sent,
            sent_at=now_utc(),
            idempotency_key=f"seed-{uuid.uuid4()}",
        )
        session.add(inv2)
        session.commit()
        rfq_id = rfq.id
        rfq_number = rfq.rfq_number

        RFQOrchestrator.notify_reject(session, rfq)
        session.commit()

    with SessionLocal() as readback:
        rows = (
            readback.query(RFQInvitation)
            .filter(
                RFQInvitation.rfq_id == rfq_id,
                RFQInvitation.purpose == RFQInvitationPurpose.reject_notify,
            )
            .all()
        )
        assert len(rows) == 2, (
            f"expected one reject_notify row per recipient, got {len(rows)}"
        )
        for row in rows:
            assert row.message_body.startswith(f"RFQ#{rfq_number}")
            assert row.send_status == RFQInvitationStatus.sent


# ── Defensive: no remaining session.delete on RFQQuote in source tree ──


def test_no_session_delete_on_rfq_quote_in_source_tree() -> None:
    """A grep-style guard: PR-4 forbids hard-deletion of RFQQuote rows
    anywhere in the source tree (J-A2-08). New code must use the soft
    state transition added in §3.3.
    """
    import pathlib

    backend_app = pathlib.Path(__file__).resolve().parent.parent / "app"
    offenders: list[str] = []
    for path in backend_app.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        # Be permissive about whitespace; flag any session.delete on a
        # variable or attribute that is plausibly an RFQQuote row.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("session.delete(quote"):
                offenders.append(f"{path}: {stripped}")
            elif "session.delete" in stripped and "RFQQuote" in stripped:
                offenders.append(f"{path}: {stripped}")
    assert not offenders, "Found illegal RFQQuote deletes:\n" + "\n".join(offenders)
