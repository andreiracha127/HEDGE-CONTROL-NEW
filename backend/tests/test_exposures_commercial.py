def _create_sales_order(
    client, price_type: str, quantity_mt: float, commodity: str = "ALUMINUM"
) -> str:
    response = client.post(
        "/orders/sales",
        json={
            "commodity": commodity,
            "price_type": price_type,
            "quantity_mt": quantity_mt,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_purchase_order(
    client, price_type: str, quantity_mt: float, commodity: str = "ALUMINUM"
) -> str:
    response = client.post(
        "/orders/purchase",
        json={
            "commodity": commodity,
            "price_type": price_type,
            "quantity_mt": quantity_mt,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_hedge_contract(client, quantity_mt: float, commodity: str = "ALUMINUM") -> str:
    response = client.post(
        "/contracts/hedge",
        json={
            "commodity": commodity,
            "quantity_mt": quantity_mt,
            "legs": [
                {"side": "sell", "price_type": "fixed"},
                {"side": "buy", "price_type": "variable"},
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


def _row_by_commodity(rows: list[dict], commodity: str) -> dict:
    return next(row for row in rows if row["commodity"] == commodity)


def _mt(row: dict, key: str) -> float:
    return float(row[key])


def test_empty_orders_returns_zero_exposure(client) -> None:
    data = _get_exposure(client)

    assert data == []


def test_fixed_price_orders_do_not_affect_exposure(client) -> None:
    _create_sales_order(client, "fixed", 10.0)
    _create_purchase_order(client, "fixed", 7.0)

    data = _get_exposure(client)

    assert data == []


def test_exposure_reduces_by_linked_quantity(client) -> None:
    order_id = _create_sales_order(client, "variable", 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    _create_linkage(client, order_id, contract_id, 4.0)

    data = _get_exposure(client)
    row = _row_by_commodity(data, "ALUMINUM")

    assert _mt(row, "pre_reduction_commercial_active_mt") == 10.0
    assert _mt(row, "reduction_applied_active_mt") == 4.0
    assert _mt(row, "commercial_active_mt") == 6.0
    assert _mt(row, "commercial_passive_mt") == 0.0
    assert _mt(row, "commercial_net_mt") == 6.0


def test_exposure_never_negative(client) -> None:
    order_id = _create_sales_order(client, "variable", 5.0)
    contract_id = _create_hedge_contract(client, 5.0)

    _create_linkage(client, order_id, contract_id, 5.0)

    data = _get_exposure(client)
    row = _row_by_commodity(data, "ALUMINUM")

    assert _mt(row, "commercial_active_mt") == 0.0
    assert _mt(row, "commercial_net_mt") == 0.0


def test_removing_linkage_changes_exposure_deterministically(client) -> None:
    order_id = _create_purchase_order(client, "variable", 8.0)
    contract_id = _create_hedge_contract(client, 8.0)

    before = _get_exposure(client)

    _create_linkage(client, order_id, contract_id, 3.0)

    after = _get_exposure(client)
    before_row = _row_by_commodity(before, "ALUMINUM")
    after_row = _row_by_commodity(after, "ALUMINUM")

    assert _mt(before_row, "commercial_passive_mt") == 8.0
    assert _mt(after_row, "commercial_passive_mt") == 5.0
    assert _mt(after_row, "reduction_applied_passive_mt") == 3.0


def test_cross_commodity_orders_are_returned_as_isolated_rows(client) -> None:
    _create_sales_order(client, "variable", 100.0, commodity="ALUMINUM")
    _create_sales_order(client, "variable", 50.0, commodity="COPPER")

    data = _get_exposure(client)

    assert len(data) == 2
    aluminum = _row_by_commodity(data, "ALUMINUM")
    copper = _row_by_commodity(data, "COPPER")
    assert _mt(aluminum, "commercial_active_mt") == 100.0
    assert _mt(copper, "commercial_active_mt") == 50.0
    assert not any(_mt(row, "commercial_active_mt") == 150.0 for row in data)


def test_commercial_exposure_groups_supported_commodity_aliases(client) -> None:
    _create_sales_order(client, "variable", 100.0, commodity="ALUMINUM")
    _create_sales_order(client, "variable", 25.0, commodity="LME_AL")

    data = _get_exposure(client)

    assert len(data) == 1
    aluminum = _row_by_commodity(data, "ALUMINUM")
    assert _mt(aluminum, "commercial_active_mt") == 125.0
    assert not any(row["commodity"] == "LME_AL" for row in data)


def test_commercial_reductions_accumulate_supported_commodity_aliases(client) -> None:
    aluminum_order_id = _create_sales_order(
        client, "variable", 100.0, commodity="ALUMINUM"
    )
    lme_al_order_id = _create_sales_order(client, "variable", 50.0, commodity="LME_AL")
    aluminum_contract_id = _create_hedge_contract(
        client, 100.0, commodity="ALUMINUM"
    )
    lme_al_contract_id = _create_hedge_contract(client, 50.0, commodity="LME_AL")

    _create_linkage(client, aluminum_order_id, aluminum_contract_id, 40.0)
    _create_linkage(client, lme_al_order_id, lme_al_contract_id, 10.0)

    data = _get_exposure(client)
    aluminum = _row_by_commodity(data, "ALUMINUM")

    assert len(data) == 1
    assert _mt(aluminum, "pre_reduction_commercial_active_mt") == 150.0
    assert _mt(aluminum, "commercial_active_mt") == 100.0
    assert _mt(aluminum, "reduction_applied_active_mt") == 50.0


def test_linkage_reduction_is_scoped_to_order_commodity(client) -> None:
    aluminum_order_id = _create_sales_order(
        client, "variable", 100.0, commodity="ALUMINUM"
    )
    _create_sales_order(client, "variable", 50.0, commodity="COPPER")
    aluminum_contract_id = _create_hedge_contract(
        client, 100.0, commodity="ALUMINUM"
    )

    _create_linkage(client, aluminum_order_id, aluminum_contract_id, 100.0)

    data = _get_exposure(client)
    aluminum = _row_by_commodity(data, "ALUMINUM")
    copper = _row_by_commodity(data, "COPPER")
    assert _mt(aluminum, "commercial_active_mt") == 0.0
    assert _mt(copper, "commercial_active_mt") == 50.0


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
        assert _row_by_commodity(first, "ALUMINUM")[key] == _row_by_commodity(
            second, "ALUMINUM"
        )[key]
