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
    client,
    quantity_mt: float,
    commodity: str = "LME_AL",
    *,
    classification: str = "short",
) -> str:
    """Create a hedge contract for the linkage tests.

    Per constitution §2.3 + §2.4 (and the new direction-validation in
    LinkageService.create after PR-4), SO must be paired with a SHORT hedge
    (fixed_leg=sell) and PO with a LONG hedge (fixed_leg=buy). Default is
    short to match the SO-default order helpers below.
    """
    if classification == "short":
        legs = [
            {"side": "sell", "price_type": "fixed"},
            {"side": "buy", "price_type": "variable"},
        ]
    else:  # long
        legs = [
            {"side": "buy", "price_type": "fixed"},
            {"side": "sell", "price_type": "variable"},
        ]
    response = client.post(
        "/contracts/hedge",
        json={
            "commodity": commodity,
            "quantity_mt": quantity_mt,
            "legs": legs,
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


# ---------------------------------------------------------------------------
# §6.1 Direction validation (J-A1-OPUS-03)
# Per constitution §2.3 + §2.4:
#   SO ↔ short hedge (sell-forward hedges sales price exposure)
#   PO ↔ long  hedge (buy-forward hedges purchase price exposure)
# ---------------------------------------------------------------------------


def _create_purchase_order(
    client, quantity_mt: float, commodity: str | None = None
) -> str:
    payload = {"price_type": "variable", "quantity_mt": quantity_mt}
    if commodity is not None:
        payload["commodity"] = commodity
    response = client.post("/orders/purchase", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


def test_linkage_so_with_long_hedge_rejected_direction_mismatch(client) -> None:
    # SO requires SHORT hedge per §2.3/§2.4 — pairing with LONG must 422.
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0, classification="long")

    response = _create_linkage(client, order_id, contract_id, 5.0)
    assert response.status_code == 422
    assert "direction mismatch" in response.json()["detail"].lower()


def test_linkage_po_with_short_hedge_rejected_direction_mismatch(client) -> None:
    # PO requires LONG hedge per §2.3/§2.4 — pairing with SHORT must 422.
    order_id = _create_purchase_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0, classification="short")

    response = _create_linkage(client, order_id, contract_id, 5.0)
    assert response.status_code == 422
    assert "direction mismatch" in response.json()["detail"].lower()


def test_linkage_so_with_short_hedge_accepted(client) -> None:
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0, classification="short")

    response = _create_linkage(client, order_id, contract_id, 5.0)
    assert response.status_code == 201


def test_linkage_po_with_long_hedge_accepted(client) -> None:
    order_id = _create_purchase_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0, classification="long")

    response = _create_linkage(client, order_id, contract_id, 5.0)
    assert response.status_code == 201


def test_linkage_fixed_price_order_rejected(client) -> None:
    # Fixed-price orders carry no market exposure and cannot be hedged.
    # Mirrors DealEngineService._validate_hedge_direction precedent
    # (deal_engine.py:201-211).
    response = client.post(
        "/orders/sales",
        json={"price_type": "fixed", "quantity_mt": 10.0},
    )
    assert response.status_code == 201
    order_id = response.json()["id"]
    contract_id = _create_hedge_contract(client, 10.0, classification="short")

    response = _create_linkage(client, order_id, contract_id, 5.0)
    assert response.status_code == 422
    assert "fixed-price" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# §6.2 Atomicity / TOCTOU (J-A1-03) — sequential & invariant
# ---------------------------------------------------------------------------


def test_application_layer_blocks_overallocation_through_two_operators(client) -> None:
    """Sequential simulation of two operators racing on the same order/contract.

    The second linkage must be rejected by the application-layer capacity
    check (Layer 1+capacity), and the over-allocation must NOT be persisted.
    Per §2.4: SUM(linkages.quantity_mt) for an order must never exceed
    order.quantity_mt.
    """
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    first = _create_linkage(client, order_id, contract_id, 7.0)
    assert first.status_code == 201

    # Second 7 MT would push linked total to 14 > 10 — must reject.
    second = _create_linkage(client, order_id, contract_id, 7.0)
    assert second.status_code == 400
    assert "exceeds" in second.json()["detail"].lower()

    listing = client.get("/linkages", params={"order_id": order_id}).json()
    assert len(listing["items"]) == 1
    # Constitution §2.4: linked = 7, order qty = 10, residual = 3
    assert listing["items"][0]["quantity_mt"] == "7.000"


def test_application_layer_rejects_overallocation_no_partial_row(client) -> None:
    """Failed allocation must not leave any partial linkage row."""
    order_id = _create_sales_order(client, 5.0)
    contract_id = _create_hedge_contract(client, 5.0)

    response = _create_linkage(client, order_id, contract_id, 6.0)
    assert response.status_code == 400

    listing = client.get("/linkages", params={"order_id": order_id}).json()
    assert listing["items"] == []


def test_contract_quantity_cannot_be_lowered_below_linked_total(client) -> None:
    """Service-level invariant: lowering contract qty below SUM(linkages) → 422."""
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)
    first = _create_linkage(client, order_id, contract_id, 7.0)
    assert first.status_code == 201

    # Per §2.4: contract.quantity_mt ≥ SUM(linkages.contract_id).
    # Lowering to 5 with 7 linked would over-allocate the contract by 2.
    response = client.patch(
        f"/contracts/hedge/{contract_id}", json={"quantity_mt": 5.0}
    )
    assert response.status_code == 422
    assert "linkage" in response.json()["detail"].lower() or "allocate" in response.json()["detail"].lower()


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

