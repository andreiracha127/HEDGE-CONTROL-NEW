def _create_sales_order(client, price_type: str, quantity_mt: float) -> str:
    response = client.post(
        "/orders/sales",
        json={"price_type": price_type, "quantity_mt": quantity_mt},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_purchase_order(client, price_type: str, quantity_mt: float) -> str:
    response = client.post(
        "/orders/purchase",
        json={"price_type": price_type, "quantity_mt": quantity_mt},
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


def _create_linkage(client, order_id: str, contract_id: str, quantity_mt: float) -> None:
    response = client.post(
        "/linkages",
        json={
            "order_id": order_id,
            "contract_id": contract_id,
            "quantity_mt": quantity_mt,
        },
    )
    assert response.status_code == 201


def _get_exposure(client) -> dict:
    response = client.get("/exposures/commercial")
    assert response.status_code == 200
    return response.json()


def _mt(data: dict, key: str) -> float:
    return float(data[key])


def test_empty_orders_returns_zero_exposure(client) -> None:
    data = _get_exposure(client)

    assert _mt(data, "pre_reduction_commercial_active_mt") == 0.0
    assert _mt(data, "pre_reduction_commercial_passive_mt") == 0.0
    assert _mt(data, "reduction_applied_active_mt") == 0.0
    assert _mt(data, "reduction_applied_passive_mt") == 0.0
    assert _mt(data, "commercial_active_mt") == 0.0
    assert _mt(data, "commercial_passive_mt") == 0.0
    assert _mt(data, "commercial_net_mt") == 0.0
    assert data["order_count_considered"] == 0
    assert data["calculation_timestamp"]


def test_fixed_price_orders_do_not_affect_exposure(client) -> None:
    _create_sales_order(client, "fixed", 10.0)
    _create_purchase_order(client, "fixed", 7.0)

    data = _get_exposure(client)

    assert _mt(data, "pre_reduction_commercial_active_mt") == 0.0
    assert _mt(data, "pre_reduction_commercial_passive_mt") == 0.0
    assert _mt(data, "commercial_active_mt") == 0.0
    assert _mt(data, "commercial_passive_mt") == 0.0
    assert _mt(data, "commercial_net_mt") == 0.0
    assert data["order_count_considered"] == 0


def test_exposure_reduces_by_linked_quantity(client) -> None:
    order_id = _create_sales_order(client, "variable", 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    _create_linkage(client, order_id, contract_id, 4.0)

    data = _get_exposure(client)

    assert _mt(data, "pre_reduction_commercial_active_mt") == 10.0
    assert _mt(data, "reduction_applied_active_mt") == 4.0
    assert _mt(data, "commercial_active_mt") == 6.0
    assert _mt(data, "commercial_passive_mt") == 0.0
    assert _mt(data, "commercial_net_mt") == 6.0


def test_exposure_never_negative(client) -> None:
    order_id = _create_sales_order(client, "variable", 5.0)
    contract_id = _create_hedge_contract(client, 5.0)

    _create_linkage(client, order_id, contract_id, 5.0)

    data = _get_exposure(client)

    assert _mt(data, "commercial_active_mt") == 0.0
    assert _mt(data, "commercial_net_mt") == 0.0


def test_removing_linkage_changes_exposure_deterministically(client) -> None:
    order_id = _create_purchase_order(client, "variable", 8.0)
    contract_id = _create_hedge_contract(client, 8.0)

    before = _get_exposure(client)

    _create_linkage(client, order_id, contract_id, 3.0)

    after = _get_exposure(client)

    assert _mt(before, "commercial_passive_mt") == 8.0
    assert _mt(after, "commercial_passive_mt") == 5.0
    assert _mt(after, "reduction_applied_passive_mt") == 3.0


def test_insert_order_sequence_does_not_affect_result(client) -> None:
    from app.core.database import engine
    from app.models.base import Base

    order_id = _create_sales_order(client, "variable", 6.0)
    contract_id = _create_hedge_contract(client, 6.0)
    _create_linkage(client, order_id, contract_id, 2.0)

    first = _get_exposure(client)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    order_id = _create_sales_order(client, "variable", 6.0)
    contract_id = _create_hedge_contract(client, 6.0)
    _create_linkage(client, order_id, contract_id, 2.0)

    second = _get_exposure(client)

    for key in [
        "pre_reduction_commercial_active_mt",
        "pre_reduction_commercial_passive_mt",
        "reduction_applied_active_mt",
        "reduction_applied_passive_mt",
        "commercial_active_mt",
        "commercial_passive_mt",
        "commercial_net_mt",
        "order_count_considered",
    ]:
        assert first[key] == second[key]
