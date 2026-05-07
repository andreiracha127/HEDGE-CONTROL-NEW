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


def test_contract_quantity_can_be_lowered_when_only_archived_order_linkages(
    client,
) -> None:
    """Per Codex P2 + migration 032: ContractService.update's precheck must
    sum only linkages whose order is live. A 100 MT contract linked 80 MT
    only to an archived order has 0 MT live capacity consumed — reducing
    the contract to 50 MT is valid under the live-side invariant and
    must NOT 422.

    Pre-fix: precheck sums all 80 MT, returns 422 even though the trigger
    (post-032) would accept the change.
    Post-fix: precheck filters Order.deleted_at IS NULL → live total = 0,
    so 50 MT ≥ 0 MT passes.
    """
    order_id = _create_sales_order(client, 100.0)
    contract_id = _create_hedge_contract(client, 100.0)
    linked = _create_linkage(client, order_id, contract_id, 80.0)
    assert linked.status_code == 201

    # Archive the order — linkage's live-order side becomes dead.
    archive = client.patch(f"/orders/{order_id}/archive")
    assert archive.status_code == 200

    # Reduce contract qty: now valid because no LIVE linkages exist.
    response = client.patch(
        f"/contracts/hedge/{contract_id}", json={"quantity_mt": 50.0}
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}. Body: {response.json()}"
    )
    assert response.json()["quantity_mt"] == "50.000"


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


# ======================================================================
# PR-5 codex P2 — write-side lifecycle gate on LinkageService.create
# Per §3.5 / §3.9 read-side dual-filter: linkages whose order is soft-
# deleted or whose hedge contract is settled / cancelled / soft-deleted
# are invisible to all downstream consumers (snapshots, reconcile, net
# exposure). Reject the linkage on the write path so a 201 cannot create
# a phantom linkage that every read silently ignores.
# ======================================================================


def test_linkage_to_archived_order_rejected(client) -> None:
    """Per Codex P2: archived (soft-deleted) order cannot accept new
    linkages — the read path filters them out, so a 201 here would
    create a phantom linkage. Expect 422.
    """
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    # Archive the order first.
    archive = client.patch(f"/orders/{order_id}/archive")
    assert archive.status_code == 200

    resp = _create_linkage(client, order_id, contract_id, 5.0)
    assert resp.status_code == 422
    assert "archived order" in resp.json()["detail"].lower()


def test_linkage_to_archived_hedge_contract_rejected(client) -> None:
    """Per Codex P2: archived (soft-deleted) hedge contract cannot accept
    new linkages — same downstream-invisibility rationale. Expect 422.
    """
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    archive = client.patch(f"/contracts/hedge/{contract_id}/archive")
    assert archive.status_code == 200

    resp = _create_linkage(client, order_id, contract_id, 5.0)
    assert resp.status_code == 422
    assert "archived hedge contract" in resp.json()["detail"].lower()


def test_linkage_to_settled_hedge_rejected(client, session) -> None:
    """Per Codex P2: settled hedge contract cannot accept new linkages.
    Read path: §3.5 / §3.9 filter HedgeContract.status in (active,
    partially_settled). A linkage to a settled hedge is invisible to
    every downstream consumer — reject 422.
    """
    from app.models.contracts import HedgeContract, HedgeContractStatus

    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    from uuid import UUID

    contract = (
        session.query(HedgeContract)
        .filter(HedgeContract.id == UUID(contract_id))
        .one()
    )
    contract.status = HedgeContractStatus.settled
    session.commit()

    resp = _create_linkage(client, order_id, contract_id, 5.0)
    assert resp.status_code == 422
    assert "settled" in resp.json()["detail"].lower()


def test_linkage_to_cancelled_hedge_rejected(client, session) -> None:
    """Per Codex P2: cancelled hedge contract cannot accept new linkages.
    Same read-side filter rationale as settled — both are excluded from
    HedgeContract.status.in_(active, partially_settled). Expect 422.
    """
    from app.models.contracts import HedgeContract, HedgeContractStatus

    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    from uuid import UUID

    contract = (
        session.query(HedgeContract)
        .filter(HedgeContract.id == UUID(contract_id))
        .one()
    )
    contract.status = HedgeContractStatus.cancelled
    session.commit()

    resp = _create_linkage(client, order_id, contract_id, 5.0)
    assert resp.status_code == 422
    assert "cancelled" in resp.json()["detail"].lower()


def test_linkage_capacity_freed_when_other_hedge_settled(client, session) -> None:
    """Per Codex P2: capacity sums must mirror the §3.5 / §3.9 read-side
    filter. A 100 MT order linked 100 MT to a hedge that is later
    settled has its capacity logically freed — the read path drops the
    dead linkage and shows the order with full residual exposure. The
    writer must accept a re-link of that freed capacity to a NEW live
    hedge.

    Pre-fix: order_linked_qty sums every historical linkage → the
    re-link is rejected with "Linkage exceeds order quantity" even
    though the read path has freed the capacity.
    Post-fix: capacity sum filters dead-side linkages, allowing
    re-link of the recovered residual.
    """
    from uuid import UUID

    from app.models.contracts import HedgeContract, HedgeContractStatus

    order_id = _create_sales_order(client, 100.0)
    dead_hedge_id = _create_hedge_contract(client, 100.0)
    live_hedge_id = _create_hedge_contract(client, 100.0)

    # Initial: order fully linked to dead_hedge.
    first = _create_linkage(client, order_id, dead_hedge_id, 100.0)
    assert first.status_code == 201

    # Settle dead_hedge — read path now treats the linkage as invisible.
    contract = (
        session.query(HedgeContract)
        .filter(HedgeContract.id == UUID(dead_hedge_id))
        .one()
    )
    contract.status = HedgeContractStatus.settled
    session.commit()

    # Re-link the now-freed 100 MT to a live hedge: must succeed.
    second = _create_linkage(client, order_id, live_hedge_id, 100.0)
    assert second.status_code == 201, (
        "After settle of the previous hedge, the order's 100 MT "
        f"capacity is freed per §3.5 / §3.9. Got: {second.json()}"
    )


def test_linkage_capacity_freed_when_other_order_archived(client, session) -> None:
    """Per Codex P2: contract-side mirror of the order-side test. A
    100 MT contract linked 100 MT to an order that is later archived
    has its capacity logically freed — the read path drops the linkage
    and shows the contract with full residual. The writer must accept
    a re-link of the freed capacity to a NEW live order.
    """
    order_a_id = _create_sales_order(client, 100.0)
    order_b_id = _create_sales_order(client, 100.0)
    contract_id = _create_hedge_contract(client, 100.0)

    # Initial: contract fully linked to order_a.
    first = _create_linkage(client, order_a_id, contract_id, 100.0)
    assert first.status_code == 201

    # Archive order_a — read path drops the linkage.
    archive = client.patch(f"/orders/{order_a_id}/archive")
    assert archive.status_code == 200

    # Re-link the freed 100 MT to a new live order: must succeed.
    second = _create_linkage(client, order_b_id, contract_id, 100.0)
    assert second.status_code == 201, (
        "After archive of the previous order, the contract's 100 MT "
        f"capacity is freed per §3.5 / §3.9. Got: {second.json()}"
    )


def test_linkage_to_partially_settled_hedge_accepted(client, session) -> None:
    """Per Codex P2 + §3.5 / §3.9 dual-filter: partially_settled is a
    LIVE status (it still has open quantity). Linkage must be accepted.
    """
    from app.models.contracts import HedgeContract, HedgeContractStatus

    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    from uuid import UUID

    contract = (
        session.query(HedgeContract)
        .filter(HedgeContract.id == UUID(contract_id))
        .one()
    )
    contract.status = HedgeContractStatus.partially_settled
    session.commit()

    resp = _create_linkage(client, order_id, contract_id, 5.0)
    assert resp.status_code == 201

