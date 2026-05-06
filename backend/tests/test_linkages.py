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


def _create_hedge_contract(
    client, quantity_mt: float, commodity: str = "LME_AL"
) -> str:
    response = client.post(
        "/contracts/hedge",
        json={
            "commodity": commodity,
            "quantity_mt": quantity_mt,
            "legs": [
                {"side": "buy", "price_type": "fixed"},
                {"side": "sell", "price_type": "variable"},
            ],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_linkage(client, order_id: str, contract_id: str, quantity_mt: float):
    return client.post(
        "/linkages",
        json={
            "order_id": order_id,
            "contract_id": contract_id,
            "quantity_mt": quantity_mt,
        },
    )


def test_linkage_qty_exceeding_order_quantity_hard_fails(client) -> None:
    order_id = _create_sales_order(client, 5.0)
    contract_id = _create_hedge_contract(client, 10.0)

    response = _create_linkage(client, order_id, contract_id, 6.0)
    assert response.status_code == 400


def test_linkage_qty_exceeding_contract_quantity_hard_fails(client) -> None:
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 4.0)

    response = _create_linkage(client, order_id, contract_id, 5.0)
    assert response.status_code == 400


def test_cross_commodity_linkage_hard_fails(client) -> None:
    order_id = _create_sales_order(client, 10.0, commodity="COPPER")
    contract_id = _create_hedge_contract(client, 10.0, commodity="LME_AL")

    response = _create_linkage(client, order_id, contract_id, 5.0)

    assert response.status_code == 400
    assert "commodity" in response.json()["detail"].lower()


def test_linkage_accepts_supported_commodity_aliases(client) -> None:
    order_id = _create_sales_order(client, 10.0, commodity="ALUMINUM")
    contract_id = _create_hedge_contract(client, 10.0, commodity="LME_AL")

    response = _create_linkage(client, order_id, contract_id, 5.0)

    assert response.status_code == 201


def test_multiple_linkages_accumulate_correctly(client) -> None:
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    first = _create_linkage(client, order_id, contract_id, 4.0)
    assert first.status_code == 201

    second = _create_linkage(client, order_id, contract_id, 5.0)
    assert second.status_code == 201

    third = _create_linkage(client, order_id, contract_id, 2.0)
    assert third.status_code == 400


def test_decimal_boundary_allows_exact_full_allocation_and_rejects_next(client) -> None:
    order_id = _create_sales_order(client, "0.3")
    contract_id = _create_hedge_contract(client, "0.3")

    first = _create_linkage(client, order_id, contract_id, "0.1")
    assert first.status_code == 201

    second = _create_linkage(client, order_id, contract_id, "0.2")
    assert second.status_code == 201

    third = _create_linkage(client, order_id, contract_id, "0.001")
    assert third.status_code == 400


def test_insert_order_does_not_change_linkage_validity(client) -> None:
    from app.core.database import engine
    from app.models.base import Base

    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    first = _create_linkage(client, order_id, contract_id, 7.0)
    assert first.status_code == 201

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    second = _create_linkage(client, order_id, contract_id, 7.0)
    assert second.status_code == 201

