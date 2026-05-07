"""Tests for Component 1.3 — Exposure Engine."""

from decimal import Decimal
from uuid import uuid4

import pytest


def _mt(value):
    return float(value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_order(
    client,
    order_type="SO",
    quantity=100.0,
    price_type="variable",
    commodity="ALUMINUM",
):
    if order_type == "SO":
        url = "/orders/sales"
    else:
        url = "/orders/purchase"
    return client.post(
        url,
        json={
            "commodity": commodity,
            "order_type": order_type,
            "price_type": price_type,
            "quantity_mt": quantity,
        },
    )


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


class TestReconcileExposures:
    def test_reconcile_creates_exposures_from_orders(self, client):
        """Reconcile should create one exposure per order."""
        _create_order(client, "SO", 500.0)
        _create_order(client, "PO", 300.0)

        resp = client.post("/exposures/reconcile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 2
        assert data["updated"] == 0

    def test_reconcile_copies_order_commodity_to_exposure(self, client):
        _create_order(client, "SO", 125.0, commodity="COPPER")

        resp = client.post("/exposures/reconcile")
        assert resp.status_code == 200

        items = client.get("/exposures/list").json()["items"]
        assert len(items) == 1
        assert items[0]["commodity"] == "COPPER"

    def test_reconcile_idempotent(self, client):
        """Running reconcile twice should not duplicate exposures."""
        _create_order(client, "SO", 500.0)

        resp1 = client.post("/exposures/reconcile")
        assert resp1.json()["created"] == 1

        resp2 = client.post("/exposures/reconcile")
        assert resp2.json()["created"] == 0
        assert resp2.json()["updated"] == 0

    def test_reconcile_no_orders(self, client):
        """Reconcile with no orders should create nothing."""
        resp = client.post("/exposures/reconcile")
        assert resp.status_code == 200
        assert resp.json()["created"] == 0

    def test_reconcile_exact_decimal_full_hedge_status(self, client):
        order = _create_order(client, "SO", "0.3")
        order_id = order.json()["id"]

        contract_resp = client.post(
            "/contracts/hedge",
            json={
                "commodity": "LME_AL",
                "quantity_mt": "0.3",
                "legs": [
                    {"side": "sell", "price_type": "fixed"},
                    {"side": "buy", "price_type": "variable"},
                ],
            },
        )
        assert contract_resp.status_code == 201
        contract_id = contract_resp.json()["id"]

        assert client.post(
            "/linkages",
            json={
                "order_id": order_id,
                "contract_id": contract_id,
                "quantity_mt": "0.1",
            },
        ).status_code == 201
        assert client.post(
            "/linkages",
            json={
                "order_id": order_id,
                "contract_id": contract_id,
                "quantity_mt": "0.2",
            },
        ).status_code == 201

        resp = client.post("/exposures/reconcile")
        assert resp.status_code == 200

        exposures = client.get("/exposures/list").json()["items"]
        assert len(exposures) == 1
        assert exposures[0]["status"] == "fully_hedged"
        assert exposures[0]["open_tons"] == "0.000"


# ---------------------------------------------------------------------------
# §6.3 Reconcile hard-fail (J-A1-OPUS-01)
#
# The previous behavior silently mapped a negative residual (linked > order qty)
# to ``open_qty=0`` → ``fully_hedged`` via ``max(...,0)`` clamp. Constitution
# §2.6 forbids this: "Exposure would be over-allocated" is a hard-fail.
# ---------------------------------------------------------------------------


class TestReconcileOverAllocationHardFail:
    @staticmethod
    def _seed_overallocated_linkage(session) -> tuple[str, Decimal, Decimal]:
        """Seed an order + linkage where SUM(linkages) > order.quantity_mt.

        We bypass ``LinkageService.create`` (which now blocks this) by using
        the ORM directly; this simulates a stale row that drifted past the
        invariant before PR-4 landed (the very over-allocation §2.6 forbids).

        Per PR-5 §3.9, ``_get_linked_qty_map`` now joins ``HedgeContract``
        and filters live (deleted_at IS NULL, status active/partially_settled).
        The fixture must therefore back the linkages with real, live hedge
        contracts; otherwise the join drops them and no over-allocation is
        detected — masking the §2.6 hard-fail this test exercises.
        """
        from app.models.contracts import (
            HedgeClassification,
            HedgeContract,
            HedgeContractStatus,
            HedgeLegSide,
        )
        from app.models.linkages import HedgeOrderLinkage
        from app.models.orders import Order, OrderType, PriceType

        order = Order(
            order_type=OrderType.sales,
            price_type=PriceType.variable,
            commodity="ALUMINUM",
            quantity_mt=Decimal("10.000"),
        )
        session.add(order)
        session.flush()

        # Two live hedge contracts so the §3.9 join survives — the test's
        # subject is the over-allocation hard-fail, not the lifecycle filter.
        contracts = []
        for qty in (Decimal("7.000"), Decimal("5.000")):
            contract = HedgeContract(
                commodity="ALUMINUM",
                classification=HedgeClassification.short,
                quantity_mt=qty,
                status=HedgeContractStatus.active,
                fixed_leg_side=HedgeLegSide.sell,
                variable_leg_side=HedgeLegSide.buy,
            )
            session.add(contract)
            contracts.append(contract)
        session.flush()

        # Two linkages summing to 12 against an order quantity of 10
        # (constitutional violation: linked = 12 > order = 10, residual = -2)
        for contract, qty in zip(contracts, (Decimal("7.000"), Decimal("5.000"))):
            session.add(
                HedgeOrderLinkage(
                    order_id=order.id,
                    contract_id=contract.id,
                    quantity_mt=qty,
                )
            )
        session.flush()
        return str(order.id), Decimal("12.000"), Decimal("10.000")

    def test_reconcile_hard_fails_on_over_allocation(self, session):
        """Per §2.6 reconcile must raise instead of clamping the residual."""
        from app.services.exposure_engine import (
            ExposureEngineService,
            ExposureOverAllocationError,
        )

        order_id, linked, order_qty = self._seed_overallocated_linkage(session)

        with pytest.raises(ExposureOverAllocationError) as exc_info:
            ExposureEngineService.reconcile_from_orders(session)

        # Per §2.7 the error message must name the offending order_id and
        # the over-allocation amount = linked - order_qty = 12 - 10 = 2.
        assert order_id in str(exc_info.value)
        assert exc_info.value.over_allocation == Decimal("2.000")
        assert exc_info.value.linked_qty == linked
        assert exc_info.value.order_qty == order_qty

    def test_reconcile_overallocation_persists_no_exposure(self, session):
        """No Exposure row should exist when reconcile aborts."""
        from app.models.exposure import Exposure
        from app.services.exposure_engine import (
            ExposureEngineService,
            ExposureOverAllocationError,
        )

        self._seed_overallocated_linkage(session)
        session.commit()  # commit the seed so a rollback by the service path
        # cannot wipe it; we want to assert that NO Exposure row was added.

        with pytest.raises(ExposureOverAllocationError):
            ExposureEngineService.reconcile_from_orders(session)
        session.rollback()

        assert session.query(Exposure).count() == 0

    def test_reconcile_route_returns_409_on_over_allocation(self, client, session):
        """Route layer surfaces the hard-fail as 409 Conflict (constitution §2.6)."""
        order_id, _, _ = self._seed_overallocated_linkage(session)
        session.commit()

        resp = client.post("/exposures/reconcile")
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert order_id in detail
        # Constitution §2.7: error names the offending residual delta.
        assert "over-allocated" in detail.lower()

    def test_reconcile_normal_case_still_produces_correct_snapshot(self, client):
        """Direction-correct, in-bounds linkage still reconciles cleanly.

        Per §2.4: SO Aluminum 10 MT + SHORT hedge 10 MT (linked qty 6.0)
        → exposure: original=10, linked=6, open=4 → partially_hedged.
        """
        order = _create_order(client, "SO", 10.0)
        order_id = order.json()["id"]

        contract_resp = client.post(
            "/contracts/hedge",
            json={
                "commodity": "LME_AL",
                "quantity_mt": 10.0,
                "legs": [
                    {"side": "sell", "price_type": "fixed"},
                    {"side": "buy", "price_type": "variable"},
                ],
            },
        )
        contract_id = contract_resp.json()["id"]
        link = client.post(
            "/linkages",
            json={
                "order_id": order_id,
                "contract_id": contract_id,
                "quantity_mt": 6.0,
            },
        )
        assert link.status_code == 201

        resp = client.post("/exposures/reconcile")
        assert resp.status_code == 200

        exposures = client.get("/exposures/list").json()["items"]
        assert len(exposures) == 1
        # §2.4 derivation: open = order_qty - linked = 10 - 6 = 4
        assert exposures[0]["original_tons"] == "10.000"
        assert exposures[0]["open_tons"] == "4.000"
        assert exposures[0]["status"] == "partially_hedged"


# ---------------------------------------------------------------------------
# List exposures
# ---------------------------------------------------------------------------


class TestListExposures:
    def test_list_exposures_after_reconcile(self, client):
        _create_order(client, "SO", 100.0)
        _create_order(client, "PO", 200.0)
        client.post("/exposures/reconcile")

        resp = client.get("/exposures/list")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2

    def test_list_exposures_filter_by_commodity(self, client):
        _create_order(client, "SO", 100.0)
        client.post("/exposures/reconcile")

        resp = client.get("/exposures/list", params={"commodity": "ALUMINUM"})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

        resp2 = client.get("/exposures/list", params={"commodity": "COPPER"})
        assert resp2.status_code == 200
        assert len(resp2.json()["items"]) == 0

    def test_list_exposures_filter_by_status(self, client):
        _create_order(client, "SO", 100.0)
        client.post("/exposures/reconcile")

        resp = client.get("/exposures/list", params={"status": "open"})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

        resp2 = client.get("/exposures/list", params={"status": "fully_hedged"})
        assert resp2.status_code == 200
        assert len(resp2.json()["items"]) == 0


# ---------------------------------------------------------------------------
# Get single exposure
# ---------------------------------------------------------------------------


class TestGetExposure:
    def test_get_exposure_by_id(self, client):
        _create_order(client, "SO", 250.0)
        client.post("/exposures/reconcile")
        items = client.get("/exposures/list").json()["items"]
        exp_id = items[0]["id"]

        resp = client.get(f"/exposures/{exp_id}")
        assert resp.status_code == 200
        assert _mt(resp.json()["original_tons"]) == 250.0

    def test_get_exposure_not_found(self, client):
        import uuid

        resp = client.get(f"/exposures/{uuid.uuid4()}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Net exposure
# ---------------------------------------------------------------------------


class TestNetExposure:
    def test_net_exposure_calculation(self, client):
        """Net = long - short per commodity."""
        _create_order(client, "PO", 600.0)  # long
        _create_order(client, "SO", 200.0)  # short
        client.post("/exposures/reconcile")

        resp = client.get("/exposures/net")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["commodity"] == "ALUMINUM"
        assert _mt(items[0]["long_original"]) == 600.0
        assert _mt(items[0]["short_original"]) == 200.0
        # net = (SO_open - PO_open) = (200 - 600) = -400 (net long)
        assert _mt(items[0]["net_tons"]) == -400.0


# ---------------------------------------------------------------------------
# Hedge tasks
# ---------------------------------------------------------------------------


class TestHedgeTasks:
    def test_hedge_tasks_created_after_reconcile(self, client, session):
        """Reconcile creates exposures → then service creates hedge tasks."""
        _create_order(client, "SO", 100.0)
        _create_order(client, "PO", 200.0)
        client.post("/exposures/reconcile")

        # Create tasks via service (called from test)
        from app.services.exposure_engine import ExposureEngineService

        count = ExposureEngineService.create_hedge_tasks(session)
        session.commit()
        assert count == 2

        resp = client.get("/exposures/tasks")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2

    def test_hedge_tasks_idempotent(self, client, session):
        """Creating tasks twice should not duplicate."""
        _create_order(client, "SO", 100.0)
        client.post("/exposures/reconcile")

        from app.services.exposure_engine import ExposureEngineService

        c1 = ExposureEngineService.create_hedge_tasks(session)
        session.commit()
        c2 = ExposureEngineService.create_hedge_tasks(session)
        session.commit()
        assert c1 == 1
        assert c2 == 0

    def test_execute_hedge_task(self, client, session):
        _create_order(client, "SO", 100.0)
        client.post("/exposures/reconcile")

        from app.services.exposure_engine import ExposureEngineService

        ExposureEngineService.create_hedge_tasks(session)
        session.commit()

        tasks = client.get("/exposures/tasks").json()["items"]
        task_id = tasks[0]["id"]

        resp = client.post(f"/exposures/tasks/{task_id}/execute")
        assert resp.status_code == 200
        assert resp.json()["status"] == "executed"
        assert resp.json()["executed_at"] is not None

    def test_execute_task_already_executed(self, client, session):
        _create_order(client, "SO", 100.0)
        client.post("/exposures/reconcile")

        from app.services.exposure_engine import ExposureEngineService

        ExposureEngineService.create_hedge_tasks(session)
        session.commit()

        tasks = client.get("/exposures/tasks").json()["items"]
        task_id = tasks[0]["id"]

        client.post(f"/exposures/tasks/{task_id}/execute")
        resp2 = client.post(f"/exposures/tasks/{task_id}/execute")
        assert resp2.status_code == 409
