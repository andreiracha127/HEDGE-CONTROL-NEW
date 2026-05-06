"""Tests for Component 1.3 — Exposure Engine."""

import pytest


def _mt(value):
    return float(value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_order(client, order_type="SO", quantity=100.0, price_type="variable"):
    if order_type == "SO":
        url = "/orders/sales"
    else:
        url = "/orders/purchase"
    return client.post(
        url,
        json={
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
        c2 = ExposureEngineService.create_hedge_tasks(session)
        assert c1 == 1
        assert c2 == 0

    def test_execute_hedge_task(self, client, session):
        _create_order(client, "SO", 100.0)
        client.post("/exposures/reconcile")

        from app.services.exposure_engine import ExposureEngineService

        ExposureEngineService.create_hedge_tasks(session)

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

        tasks = client.get("/exposures/tasks").json()["items"]
        task_id = tasks[0]["id"]

        client.post(f"/exposures/tasks/{task_id}/execute")
        resp2 = client.post(f"/exposures/tasks/{task_id}/execute")
        assert resp2.status_code == 409
