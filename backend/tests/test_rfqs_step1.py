from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.core.database import SessionLocal
from app.models.quotes import RFQQuote
from app.schemas.rfq import FloatPricingConvention, RFQQuoteCreate
from app.services.rfq_service import RFQService


def _create_counterparty(
    client, name: str = "Counterparty 1", phone: str = "+5511999990001"
) -> str:
    """Create a counterparty with whatsapp_phone and return its UUID."""
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


def _create_sales_order(
    client, quantity_mt: float, commodity: str | None = None
) -> str:
    payload = {"price_type": "variable", "quantity_mt": quantity_mt}
    if commodity is not None:
        payload["commodity"] = commodity
    response = client.post(
        "/orders/sales",
        json=payload,
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_hedge_contract(client, quantity_mt: float) -> str:
    # SHORT hedge (fixed leg = sell) — direction-correct for the SO-paired
    # tests below per constitution §2.3 + §2.4 (PR-4 J-A1-OPUS-03).
    response = client.post(
        "/contracts/hedge",
        json={
            "commodity": "LME_AL",
            "quantity_mt": quantity_mt,
            "legs": [
                {"side": "sell", "price_type": "fixed"},
                {"side": "buy", "price_type": "variable"},
            ],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_linkage(
    client, order_id: str, contract_id: str, quantity_mt: float
) -> None:
    response = client.post(
        "/linkages",
        json={
            "order_id": order_id,
            "contract_id": contract_id,
            "quantity_mt": quantity_mt,
        },
    )
    assert response.status_code == 201


def _create_rfq(client, payload: dict):
    return client.post("/rfqs", json=payload)


def _create_global_rfq(client, cp_id: str | None = None) -> str:
    if cp_id is None:
        cp_id = _create_counterparty(client)
    response = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": "5.000",
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id}],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _quote_payload(rfq_id: str, cp_id: str, price: str, unit: str = "USD/MT") -> dict:
    return {
        "rfq_id": rfq_id,
        "counterparty_id": cp_id,
        "fixed_price_value": price,
        "fixed_price_unit": unit,
        "float_pricing_convention": "avg",
        "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
    }


def _get_commercial_exposure(client) -> dict:
    response = client.get("/exposures/commercial")
    assert response.status_code == 200
    rows = response.json()
    return next(row for row in rows if row["commodity"] == "ALUMINUM")


def test_rfq_qty_exceeding_residual_exposure_hard_fails(client) -> None:
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)
    _create_linkage(client, order_id, contract_id, 4.0)

    response = _create_rfq(
        client,
        {
            "intent": "COMMERCIAL_HEDGE",
            "commodity": "ALUMINUM",
            "quantity_mt": 7.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "SELL",
            "order_id": order_id,
            "invitations": [],
        },
    )
    assert response.status_code == 400


def test_commercial_hedge_rejects_order_commodity_mismatch(client) -> None:
    order_id = _create_sales_order(client, 10.0)

    response = _create_rfq(
        client,
        {
            "intent": "COMMERCIAL_HEDGE",
            "commodity": "COPPER",
            "quantity_mt": 5.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "SELL",
            "order_id": order_id,
            "invitations": [],
        },
    )

    assert response.status_code == 400
    assert "commodity" in response.json()["detail"].lower()


def test_commercial_hedge_accepts_supported_order_commodity_alias(client) -> None:
    order_id = _create_sales_order(client, 10.0)

    response = _create_rfq(
        client,
        {
            "intent": "COMMERCIAL_HEDGE",
            "commodity": "LME_AL",
            "quantity_mt": 5.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "SELL",
            "order_id": order_id,
            "invitations": [],
        },
    )

    assert response.status_code == 201
    assert response.json()["commodity"] == "LME_AL"


def test_commercial_hedge_uses_canonical_snapshot_for_order_alias(client) -> None:
    order_id = _create_sales_order(client, 10.0, commodity="LME_AL")

    response = _create_rfq(
        client,
        {
            "intent": "COMMERCIAL_HEDGE",
            "commodity": "LME_AL",
            "quantity_mt": 5.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "SELL",
            "order_id": order_id,
            "invitations": [],
        },
    )

    assert response.status_code == 201
    assert response.json()["commercial_active_mt"] == "10.000"


def test_global_rfq_uses_canonical_snapshot_for_payload_alias(client) -> None:
    _create_sales_order(client, 10.0, commodity="ALUMINUM")

    response = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": 2.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [],
        },
    )

    assert response.status_code == 201
    assert response.json()["commercial_active_mt"] == "10.000"


def test_rfq_number_is_deterministic_and_server_generated(client) -> None:
    payload = {
        "intent": "GLOBAL_POSITION",
        "commodity": "LME_AL",
        "quantity_mt": 5.0,
        "delivery_window_start": "2026-03-01",
        "delivery_window_end": "2026-03-31",
        "direction": "BUY",
        "order_id": None,
        "invitations": [],
    }

    first = _create_rfq(client, payload)
    assert first.status_code == 201
    second = _create_rfq(client, payload)
    assert second.status_code == 201

    first_number = first.json()["rfq_number"]
    second_number = second.json()["rfq_number"]
    year = datetime.now(timezone.utc).year

    assert first_number.startswith(f"RFQ-{year}-")
    assert second_number.startswith(f"RFQ-{year}-")

    first_seq = int(first_number.split("-")[-1])
    second_seq = int(second_number.split("-")[-1])
    assert second_seq == first_seq + 1


def test_rfq_state_transitions_valid(client) -> None:
    cp_id = _create_counterparty(client)

    response = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": 3.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id}],
        },
    )
    assert response.status_code == 201
    assert response.json()["state"] == "SENT"

    # No invitations → stays in CREATED
    response = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": 3.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [],
        },
    )
    assert response.status_code == 201
    assert response.json()["state"] == "CREATED"


def test_rfq_residual_exposure_check_at_exact_boundary(client) -> None:
    """Boundary: ``quantity_mt == residual_side`` must NOT off-by-epsilon.

    Decimal equality at the boundary should accept; only strictly above
    residual should hard-fail. Pre-PR-1 the comparison ran in float64 which
    could spuriously reject at the boundary depending on representation.
    """
    order_id = _create_sales_order(client, "10.000", commodity="LME_AL")
    contract_id = _create_hedge_contract(client, "4.000")
    _create_linkage(client, order_id, contract_id, "4.000")

    # Residual on sales side = post_active = 10 - 4 = 6 (after linkage applied).
    # Exact boundary RFQ qty == residual → must succeed.
    response = _create_rfq(
        client,
        {
            "intent": "COMMERCIAL_HEDGE",
            "commodity": "LME_AL",
            "quantity_mt": "6.000",
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "SELL",
            "order_id": order_id,
            "invitations": [],
        },
    )
    assert response.status_code == 201, response.text


def test_rfq_creation_accepts_string_decimal_quantity(client) -> None:
    response = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": "1.234",
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [],
        },
    )
    assert response.status_code == 201
    assert response.json()["quantity_mt"] == "1.234"


def test_rfq_creation_does_not_change_exposure(client) -> None:
    _create_sales_order(client, 10.0)
    before = _get_commercial_exposure(client)

    response = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": 2.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [],
        },
    )
    assert response.status_code == 201

    after = _get_commercial_exposure(client)
    before.pop("calculation_timestamp")
    after.pop("calculation_timestamp")
    assert before == after


def test_submit_quote_rejects_zero_price(client) -> None:
    cp_id = _create_counterparty(client)
    rfq_id = _create_global_rfq(client, cp_id)

    response = client.post(
        f"/rfqs/{rfq_id}/quotes", json=_quote_payload(rfq_id, cp_id, "0.000000")
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "fixed_price_value must be > 0"


def test_submit_quote_rejects_negative_price(client) -> None:
    cp_id = _create_counterparty(client)
    rfq_id = _create_global_rfq(client, cp_id)

    response = client.post(
        f"/rfqs/{rfq_id}/quotes", json=_quote_payload(rfq_id, cp_id, "-1.000000")
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "fixed_price_value must be > 0"


def test_submit_quote_rejects_non_canonical_unit(client) -> None:
    cp_id = _create_counterparty(client)
    rfq_id = _create_global_rfq(client, cp_id)

    response = client.post(
        f"/rfqs/{rfq_id}/quotes",
        json=_quote_payload(rfq_id, cp_id, "100.000000", unit="usd-mt"),
    )

    assert response.status_code == 400
    assert "not canonical" in response.json()["detail"]


def test_submit_quote_quantizes_price_before_persist(client) -> None:
    cp_id = _create_counterparty(client)
    rfq_id = _create_global_rfq(client, cp_id)
    received_at = datetime(2026, 2, 1, tzinfo=timezone.utc)

    with SessionLocal() as session:
        quote = RFQService.submit_quote(
            session,
            UUID(rfq_id),
            RFQQuoteCreate.model_construct(
                rfq_id=UUID(rfq_id),
                counterparty_id=UUID(cp_id),
                fixed_price_value=Decimal("100.1234564"),
                fixed_price_unit="USD/MT",
                float_pricing_convention=FloatPricingConvention.avg,
                received_at=received_at,
            ),
        )
        session.commit()
        quote_id = quote.id

    with SessionLocal() as session:
        persisted = session.get(RFQQuote, quote_id)
        assert persisted.fixed_price_value == Decimal("100.123456")


# ── Archive lifecycle (Phase A2 PR-3, J-A2-OPUS-06) ─────────────────────


class TestRFQArchiveLifecycle:
    """``RFQService.archive`` requires ``RFQState.closed`` and emits a
    ``RFQStateEvent`` with ``trigger='archive'`` plus an explicit
    ``event_timestamp`` and ``user_id`` (J-A2-OPUS-06, J-A2-OPUS-07).
    """

    @staticmethod
    def _create_archivable_rfq(client) -> str:
        """Create + cancel an RFQ so it sits in ``CLOSED``."""
        cp_id = _create_counterparty(client)
        order_id = _create_sales_order(client, 50.0, commodity="ALUMINUM")
        rfq_resp = _create_rfq(
            client,
            {
                "intent": "COMMERCIAL_HEDGE",
                "commodity": "ALUMINUM",
                "quantity_mt": 5.0,
                "delivery_window_start": "2026-03-01",
                "delivery_window_end": "2026-03-31",
                "direction": "SELL",
                "order_id": order_id,
                "invitations": [{"counterparty_id": cp_id}],
            },
        )
        assert rfq_resp.status_code == 201
        rfq_id = rfq_resp.json()["id"]
        cancel_resp = client.post(
            f"/rfqs/{rfq_id}/actions/cancel",
            json={},
        )
        assert cancel_resp.status_code == 200
        return rfq_id

    def test_archive_rejects_active_rfq(self, client) -> None:
        """An RFQ in ``SENT`` (or any non-CLOSED state) must not archive."""
        cp_id = _create_counterparty(client)
        order_id = _create_sales_order(client, 50.0, commodity="ALUMINUM")
        rfq_resp = _create_rfq(
            client,
            {
                "intent": "COMMERCIAL_HEDGE",
                "commodity": "ALUMINUM",
                "quantity_mt": 5.0,
                "delivery_window_start": "2026-03-01",
                "delivery_window_end": "2026-03-31",
                "direction": "SELL",
                "order_id": order_id,
                "invitations": [{"counterparty_id": cp_id}],
            },
        )
        assert rfq_resp.status_code == 201
        rfq_id = rfq_resp.json()["id"]
        # RFQ is in SENT (mocked WhatsApp succeeds in conftest)
        resp = client.patch(
            f"/rfqs/{rfq_id}/archive",
            json={},
        )
        assert resp.status_code == 409
        assert "CLOSED" in resp.json()["detail"]

    def test_archive_emits_state_event_with_timestamp_and_user(self, client) -> None:
        rfq_id = self._create_archivable_rfq(client)
        resp = client.patch(
            f"/rfqs/{rfq_id}/archive",
            json={},
        )
        assert resp.status_code == 200, resp.text

        events = client.get(f"/rfqs/{rfq_id}/state-events").json()
        archive_events = [e for e in events if e.get("trigger") == "archive"]
        assert len(archive_events) == 1
        evt = archive_events[0]
        assert evt["user_id"] == "test-user"
        assert evt["event_timestamp"] is not None
        # Lifecycle marker is ``deleted_at``; ``RFQState`` itself does not
        # change on archive (the row is already CLOSED).
        assert evt["from_state"] == evt["to_state"]

    def test_archive_idempotent_409_on_already_archived(self, client) -> None:
        rfq_id = self._create_archivable_rfq(client)
        first = client.patch(
            f"/rfqs/{rfq_id}/archive",
            json={},
        )
        assert first.status_code == 200
        second = client.patch(
            f"/rfqs/{rfq_id}/archive",
            json={},
        )
        assert second.status_code == 409
        assert "already archived" in second.json()["detail"].lower()
