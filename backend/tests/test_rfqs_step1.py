from datetime import datetime, timezone


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


def _create_sales_order(client, quantity_mt: float) -> str:
    response = client.post(
        "/orders/sales",
        json={"price_type": "variable", "quantity_mt": quantity_mt},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_hedge_contract(client, quantity_mt: float) -> str:
    response = client.post(
        "/contracts/hedge",
        json={
            "commodity": "LME_AL",
            "quantity_mt": quantity_mt,
            "legs": [
                {"side": "buy", "price_type": "fixed"},
                {"side": "sell", "price_type": "variable"},
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
