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


def _create_hedge_contract(
    client,
    quantity_mt: float,
    legs: list[dict],
    commodity: str = "ALUMINUM",
) -> str:
    response = client.post(
        "/contracts/hedge",
        json={"commodity": commodity, "quantity_mt": quantity_mt, "legs": legs},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_linkage(client, order_id: str, contract_id: str, quantity_mt: float) -> None:
    response = client.post(
        "/linkages",
        json={"order_id": order_id, "contract_id": contract_id, "quantity_mt": quantity_mt},
    )
    assert response.status_code == 201


def _get_global_exposure(client) -> dict:
    response = client.get("/exposures/global")
    assert response.status_code == 200
    return response.json()


def _row_by_commodity(rows: list[dict], commodity: str) -> dict:
    return next(row for row in rows if row["commodity"] == commodity)


def _mt(row: dict, key: str) -> float:
    return float(row[key])


def test_global_exposure_reduces_when_linkages_exist(client) -> None:
    order_id = _create_sales_order(client, "variable", 10.0)
    contract_id = _create_hedge_contract(
        client,
        quantity_mt=5.0,
        legs=[
            {"side": "sell", "price_type": "fixed"},
            {"side": "buy", "price_type": "variable"},
        ],
    )
    _create_linkage(client, order_id, contract_id, 4.0)

    data = _get_global_exposure(client)
    row = _row_by_commodity(data, "ALUMINUM")

    assert _mt(row, "pre_reduction_global_active_mt") == 15.0
    assert _mt(row, "reduction_applied_active_mt") == 8.0
    assert _mt(row, "global_active_mt") == 7.0
    assert _mt(row, "hedge_short_mt") == 1.0


def test_no_double_counting_of_linked_hedge_quantities(client) -> None:
    order_id = _create_sales_order(client, "variable", 8.0)
    contract_id = _create_hedge_contract(
        client,
        quantity_mt=6.0,
        legs=[
            {"side": "sell", "price_type": "fixed"},
            {"side": "buy", "price_type": "variable"},
        ],
    )
    _create_linkage(client, order_id, contract_id, 2.5)

    data = _get_global_exposure(client)
    row = _row_by_commodity(data, "ALUMINUM")

    assert _mt(row, "hedge_short_mt") == 3.5
    assert _mt(row, "reduction_applied_active_mt") == 5.0


def test_unlinked_hedge_qty_still_affects_global_exposure(client) -> None:
    _create_sales_order(client, "variable", 2.0)
    _create_hedge_contract(
        client,
        quantity_mt=3.0,
        legs=[
            {"side": "sell", "price_type": "fixed"},
            {"side": "buy", "price_type": "variable"},
        ],
    )

    data = _get_global_exposure(client)
    row = _row_by_commodity(data, "ALUMINUM")

    assert _mt(row, "global_active_mt") == 5.0
    assert _mt(row, "hedge_short_mt") == 3.0


def test_exposure_never_negative(client) -> None:
    order_id = _create_sales_order(client, "variable", 5.0)
    contract_id = _create_hedge_contract(
        client,
        quantity_mt=5.0,
        legs=[
            {"side": "sell", "price_type": "fixed"},
            {"side": "buy", "price_type": "variable"},
        ],
    )
    _create_linkage(client, order_id, contract_id, 5.0)

    data = _get_global_exposure(client)
    row = _row_by_commodity(data, "ALUMINUM")

    assert _mt(row, "global_active_mt") >= 0.0
    assert _mt(row, "global_passive_mt") >= 0.0


def test_removing_linkage_changes_global_exposure_deterministically(client) -> None:
    order_id = _create_purchase_order(client, "variable", 9.0)
    contract_id = _create_hedge_contract(
        client,
        quantity_mt=4.0,
        legs=[
            {"side": "buy", "price_type": "fixed"},
            {"side": "sell", "price_type": "variable"},
        ],
    )

    before = _get_global_exposure(client)
    _create_linkage(client, order_id, contract_id, 3.0)
    after = _get_global_exposure(client)
    before_row = _row_by_commodity(before, "ALUMINUM")
    after_row = _row_by_commodity(after, "ALUMINUM")

    assert _mt(before_row, "global_passive_mt") == 13.0
    assert _mt(after_row, "global_passive_mt") == 7.0
    assert _mt(after_row, "reduction_applied_passive_mt") == 6.0


def test_cross_commodity_orders_and_hedges_are_returned_as_isolated_rows(client) -> None:
    _create_sales_order(client, "variable", 100.0, commodity="ALUMINUM")
    _create_sales_order(client, "variable", 50.0, commodity="COPPER")
    _create_hedge_contract(
        client,
        quantity_mt=80.0,
        commodity="ALUMINUM",
        legs=[
            {"side": "sell", "price_type": "fixed"},
            {"side": "buy", "price_type": "variable"},
        ],
    )
    _create_hedge_contract(
        client,
        quantity_mt=30.0,
        commodity="COPPER",
        legs=[
            {"side": "sell", "price_type": "fixed"},
            {"side": "buy", "price_type": "variable"},
        ],
    )

    data = _get_global_exposure(client)

    assert len(data) == 2
    aluminum = _row_by_commodity(data, "ALUMINUM")
    copper = _row_by_commodity(data, "COPPER")
    assert _mt(aluminum, "global_active_mt") == 180.0
    assert _mt(copper, "global_active_mt") == 80.0
    assert not any(_mt(row, "global_active_mt") == 260.0 for row in data)


def test_global_exposure_groups_supported_commodity_aliases(client) -> None:
    _create_sales_order(client, "variable", 100.0, commodity="ALUMINUM")
    _create_hedge_contract(
        client,
        quantity_mt=80.0,
        commodity="LME_AL",
        legs=[
            {"side": "sell", "price_type": "fixed"},
            {"side": "buy", "price_type": "variable"},
        ],
    )

    data = _get_global_exposure(client)

    assert len(data) == 1
    aluminum = _row_by_commodity(data, "ALUMINUM")
    assert _mt(aluminum, "global_active_mt") == 180.0
    assert _mt(aluminum, "hedge_short_mt") == 80.0
    assert not any(row["commodity"] == "LME_AL" for row in data)


def test_order_insertion_sequence_does_not_affect_result(client) -> None:
    from app.core.database import engine
    from app.models.base import Base

    order_id = _create_sales_order(client, "variable", 6.0)
    contract_id = _create_hedge_contract(
        client,
        quantity_mt=6.0,
        legs=[
            {"side": "sell", "price_type": "fixed"},
            {"side": "buy", "price_type": "variable"},
        ],
    )
    _create_linkage(client, order_id, contract_id, 2.0)

    first = _get_global_exposure(client)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    order_id = _create_sales_order(client, "variable", 6.0)
    contract_id = _create_hedge_contract(
        client,
        quantity_mt=6.0,
        legs=[
            {"side": "sell", "price_type": "fixed"},
            {"side": "buy", "price_type": "variable"},
        ],
    )
    _create_linkage(client, order_id, contract_id, 2.0)

    second = _get_global_exposure(client)

    for key in [
        "pre_reduction_global_active_mt",
        "pre_reduction_global_passive_mt",
        "reduction_applied_active_mt",
        "reduction_applied_passive_mt",
        "global_active_mt",
        "global_passive_mt",
        "global_net_mt",
        "commercial_active_mt",
        "commercial_passive_mt",
        "hedge_long_mt",
        "hedge_short_mt",
        "entities_count_considered",
    ]:
        assert _row_by_commodity(first, "ALUMINUM")[key] == _row_by_commodity(
            second, "ALUMINUM"
        )[key]


def test_recomputing_twice_yields_identical_result(client) -> None:
    _create_sales_order(client, "variable", 7.0)
    _create_purchase_order(client, "variable", 2.0)

    first = _get_global_exposure(client)
    second = _get_global_exposure(client)

    for key in [
        "pre_reduction_global_active_mt",
        "pre_reduction_global_passive_mt",
        "reduction_applied_active_mt",
        "reduction_applied_passive_mt",
        "global_active_mt",
        "global_passive_mt",
        "global_net_mt",
        "commercial_active_mt",
        "commercial_passive_mt",
        "hedge_long_mt",
        "hedge_short_mt",
        "entities_count_considered",
    ]:
        assert _row_by_commodity(first, "ALUMINUM")[key] == _row_by_commodity(
            second, "ALUMINUM"
        )[key]
