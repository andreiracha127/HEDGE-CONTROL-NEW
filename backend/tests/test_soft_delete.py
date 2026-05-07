"""Tests for soft-delete (archived) behavior on orders, contracts, and RFQs."""

from uuid import UUID

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.utils import now_utc
from app.models.rfqs import RFQ


def _create_sales_order(client: TestClient) -> dict:
    resp = client.post(
        "/orders/sales",
        json={"price_type": "fixed", "quantity_mt": 100},
    )
    assert resp.status_code == 201
    return resp.json()


def _create_hedge_contract(client: TestClient) -> dict:
    resp = client.post(
        "/contracts/hedge",
        json={
            "commodity": "Zinc",
            "quantity_mt": 50,
            "legs": [
                {"side": "buy", "price_type": "fixed"},
                {"side": "sell", "price_type": "variable"},
            ],
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _create_counterparty(client: TestClient) -> str:
    """Create a counterparty and return its UUID."""
    resp = client.post(
        "/counterparties",
        json={
            "type": "broker",
            "name": "Test CP SoftDelete",
            "country": "BRA",
            "whatsapp_phone": "+5511999990000",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _create_rfq(client: TestClient, order_id: str, cp_id: str) -> dict:
    resp = client.post(
        "/rfqs",
        json={
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
    assert resp.status_code == 201
    return resp.json()


# ── Order soft-delete ────────────────────────────────────────────────


class TestOrderSoftDelete:
    def test_archive_order_sets_deleted_at(self, client: TestClient):
        order = _create_sales_order(client)
        resp = client.patch(f"/orders/{order['id']}/archive")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted_at"] is not None

    def test_archived_order_excluded_from_list(self, client: TestClient):
        order = _create_sales_order(client)
        client.patch(f"/orders/{order['id']}/archive")
        resp = client.get("/orders")
        assert resp.status_code == 200
        ids = [o["id"] for o in resp.json()["items"]]
        assert order["id"] not in ids

    def test_include_deleted_shows_archived_order(self, client: TestClient):
        order = _create_sales_order(client)
        client.patch(f"/orders/{order['id']}/archive")
        resp = client.get("/orders?include_deleted=true")
        assert resp.status_code == 200
        ids = [o["id"] for o in resp.json()["items"]]
        assert order["id"] in ids

    def test_archive_already_archived_returns_409(self, client: TestClient):
        order = _create_sales_order(client)
        client.patch(f"/orders/{order['id']}/archive")
        resp = client.patch(f"/orders/{order['id']}/archive")
        assert resp.status_code == 409

    def test_archive_nonexistent_order_returns_404(self, client: TestClient):
        resp = client.patch("/orders/00000000-0000-0000-0000-000000000000/archive")
        assert resp.status_code == 404


# ── HedgeContract soft-delete ────────────────────────────────────────


class TestContractSoftDelete:
    def test_archive_contract_sets_deleted_at(self, client: TestClient):
        contract = _create_hedge_contract(client)
        resp = client.patch(f"/contracts/hedge/{contract['id']}/archive")
        assert resp.status_code == 200
        assert resp.json()["deleted_at"] is not None

    def test_archived_contract_excluded_from_list(self, client: TestClient):
        contract = _create_hedge_contract(client)
        client.patch(f"/contracts/hedge/{contract['id']}/archive")
        resp = client.get("/contracts/hedge")
        assert resp.status_code == 200
        ids = [c["id"] for c in resp.json()["items"]]
        assert contract["id"] not in ids

    def test_include_deleted_shows_archived_contract(self, client: TestClient):
        contract = _create_hedge_contract(client)
        client.patch(f"/contracts/hedge/{contract['id']}/archive")
        resp = client.get("/contracts/hedge?include_deleted=true")
        assert resp.status_code == 200
        ids = [c["id"] for c in resp.json()["items"]]
        assert contract["id"] in ids

    def test_archive_already_archived_returns_409(self, client: TestClient):
        contract = _create_hedge_contract(client)
        client.patch(f"/contracts/hedge/{contract['id']}/archive")
        resp = client.patch(f"/contracts/hedge/{contract['id']}/archive")
        assert resp.status_code == 409

    def test_archive_nonexistent_contract_returns_404(self, client: TestClient):
        resp = client.patch(
            "/contracts/hedge/00000000-0000-0000-0000-000000000000/archive"
        )
        assert resp.status_code == 404


# ── RFQ soft-delete ──────────────────────────────────────────────────


def _close_rfq(client: TestClient, rfq_id: str) -> None:
    """Cancel an RFQ to drive it to ``CLOSED`` so it becomes archivable."""
    resp = client.post(
        f"/rfqs/{rfq_id}/actions/cancel",
        json={"user_id": "test-user"},
    )
    assert resp.status_code == 200, resp.text


def _force_archive(rfq_id: str) -> None:
    """Set ``deleted_at`` directly on the row.

    Used to test that *every* mutation path rejects archived RFQs even when
    the state would otherwise allow the mutation. The archive route itself
    gates on ``CLOSED``; this helper bypasses that gate to construct the
    archived-but-active-state scenarios required by the lifecycle invariant.
    """
    with SessionLocal() as session:
        rfq = session.get(RFQ, UUID(rfq_id))
        assert rfq is not None
        rfq.deleted_at = now_utc()
        session.commit()


class TestRFQSoftDelete:
    @staticmethod
    def _create_variable_order(client: TestClient) -> dict:
        resp = client.post(
            "/orders/sales",
            json={"price_type": "variable", "quantity_mt": 100},
        )
        assert resp.status_code == 201
        return resp.json()

    def test_archive_rfq_sets_deleted_at(self, client: TestClient):
        order = self._create_variable_order(client)
        cp_id = _create_counterparty(client)
        rfq = _create_rfq(client, order["id"], cp_id)
        _close_rfq(client, rfq["id"])
        resp = client.patch(
            f"/rfqs/{rfq['id']}/archive",
            json={"user_id": "test-user"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted_at"] is not None

    def test_archived_rfq_excluded_from_list(self, client: TestClient):
        order = self._create_variable_order(client)
        cp_id = _create_counterparty(client)
        rfq = _create_rfq(client, order["id"], cp_id)
        _close_rfq(client, rfq["id"])
        client.patch(
            f"/rfqs/{rfq['id']}/archive",
            json={"user_id": "test-user"},
        )
        resp = client.get("/rfqs")
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()["items"]]
        assert rfq["id"] not in ids

    def test_include_deleted_shows_archived_rfq(self, client: TestClient):
        order = self._create_variable_order(client)
        cp_id = _create_counterparty(client)
        rfq = _create_rfq(client, order["id"], cp_id)
        _close_rfq(client, rfq["id"])
        client.patch(
            f"/rfqs/{rfq['id']}/archive",
            json={"user_id": "test-user"},
        )
        resp = client.get("/rfqs?include_deleted=true")
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()["items"]]
        assert rfq["id"] in ids

    def test_archive_already_archived_returns_409(self, client: TestClient):
        order = self._create_variable_order(client)
        cp_id = _create_counterparty(client)
        rfq = _create_rfq(client, order["id"], cp_id)
        _close_rfq(client, rfq["id"])
        client.patch(
            f"/rfqs/{rfq['id']}/archive",
            json={"user_id": "test-user"},
        )
        resp = client.patch(
            f"/rfqs/{rfq['id']}/archive",
            json={"user_id": "test-user"},
        )
        assert resp.status_code == 409

    def test_archive_nonexistent_rfq_returns_404(self, client: TestClient):
        resp = client.patch(
            "/rfqs/00000000-0000-0000-0000-000000000000/archive",
            json={"user_id": "test-user"},
        )
        assert resp.status_code == 404


class TestArchivedRFQMutationsRejected:
    """Every mutation path must reject archived RFQs with 409 (J-A2-11).

    Each test creates an RFQ, forces ``deleted_at`` directly to bypass the
    archive route's CLOSED-state precondition, then attempts a mutation
    that would normally succeed in the RFQ's current state. The mutation
    must fail with 409 ``RFQ is archived`` before the state machine runs.
    """

    @staticmethod
    def _create_variable_order(client: TestClient) -> dict:
        resp = client.post(
            "/orders/sales",
            json={"price_type": "variable", "quantity_mt": 100},
        )
        assert resp.status_code == 201
        return resp.json()

    def test_archived_rfq_rejects_quote_submission_with_409(
        self, client: TestClient
    ) -> None:
        order = self._create_variable_order(client)
        cp_id = _create_counterparty(client)
        rfq = _create_rfq(client, order["id"], cp_id)
        _force_archive(rfq["id"])

        resp = client.post(
            f"/rfqs/{rfq['id']}/quotes",
            json={
                "rfq_id": rfq["id"],
                "counterparty_id": cp_id,
                "fixed_price_value": 2500.0,
                "fixed_price_unit": "USD/MT",
                "float_pricing_convention": "avg",
                "received_at": now_utc().isoformat(),
            },
        )
        assert resp.status_code == 409
        assert "archived" in resp.json()["detail"].lower()

    def test_archived_rfq_rejects_refresh_with_409(self, client: TestClient) -> None:
        order = self._create_variable_order(client)
        cp_id = _create_counterparty(client)
        rfq = _create_rfq(client, order["id"], cp_id)
        _force_archive(rfq["id"])

        resp = client.post(
            f"/rfqs/{rfq['id']}/actions/refresh",
            json={"user_id": "test-user"},
        )
        assert resp.status_code == 409
        assert "archived" in resp.json()["detail"].lower()

    def test_archived_rfq_rejects_reject_quote_with_409(
        self, client: TestClient
    ) -> None:
        order = self._create_variable_order(client)
        cp_id = _create_counterparty(client)
        rfq = _create_rfq(client, order["id"], cp_id)
        _force_archive(rfq["id"])

        resp = client.post(
            f"/rfqs/{rfq['id']}/actions/reject-quote"
            "?quote_id=00000000-0000-0000-0000-000000000000",
            json={"user_id": "test-user"},
        )
        assert resp.status_code == 409
        assert "archived" in resp.json()["detail"].lower()

    def test_archived_rfq_rejects_award_with_409(self, client: TestClient) -> None:
        order = self._create_variable_order(client)
        cp_id = _create_counterparty(client)
        rfq = _create_rfq(client, order["id"], cp_id)
        _force_archive(rfq["id"])

        resp = client.post(
            f"/rfqs/{rfq['id']}/actions/award",
            json={"user_id": "test-user"},
        )
        assert resp.status_code == 409
        assert "archived" in resp.json()["detail"].lower()

    def test_archived_rfq_visible_via_get_but_not_get_live(
        self, client: TestClient
    ) -> None:
        """``RFQService.get`` (audit-history loader) still returns the RFQ;
        ``get_live`` (mutation loader) raises 409. Verified by contrast:
        the read endpoint succeeds (uses ``get`` via ``_build_rfq_read``),
        while a mutation endpoint fails."""
        order = self._create_variable_order(client)
        cp_id = _create_counterparty(client)
        rfq = _create_rfq(client, order["id"], cp_id)
        _force_archive(rfq["id"])

        read_resp = client.get(f"/rfqs/{rfq['id']}")
        assert read_resp.status_code == 200
        assert read_resp.json()["deleted_at"] is not None

        mutation_resp = client.post(
            f"/rfqs/{rfq['id']}/actions/cancel",
            json={"user_id": "test-user"},
        )
        assert mutation_resp.status_code == 409
        assert "archived" in mutation_resp.json()["detail"].lower()
