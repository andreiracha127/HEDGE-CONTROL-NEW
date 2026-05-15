from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.auth import (
    get_current_actor_roles,
    get_current_user,
    require_service_identity,
)
from app.main import app
from app.models.audit import AuditEvent
from app.models.counterparty import Counterparty, CounterpartyType
from app.models.contracts import HedgeContract, HedgeContractStatus
from app.models.deal import Deal
from app.models.orders import Order, OrderType, PriceType
from app.models.rfqs import RFQ, RFQDirection, RFQIntent, RFQState
from app.services.westmetall_cash_settlement import WestmetallFetchEvidence


def _as_roles(*roles: str, sub: str = "test-user") -> dict:
    return {"sub": sub, "roles": list(roles)}


@pytest.fixture()
def auth_as():
    def _set(*roles: str, sub: str = "test-user") -> None:
        app.dependency_overrides[get_current_user] = lambda: _as_roles(
            *roles, sub=sub
        )

    yield _set
    app.dependency_overrides.clear()


def _counterparty_payload(type_: str, name: str | None = None) -> dict:
    return {
        "type": type_,
        "name": name or f"{type_} CP",
        "country": "BRA",
        "city": "Sao Paulo",
        "tax_id": f"{type_}-{uuid.uuid4()}",
        "whatsapp_phone": "+5511999990000",
    }


def _insert_counterparty(session, type_: CounterpartyType, name: str) -> Counterparty:
    cp = Counterparty(
        type=type_,
        name=name,
        country="BRA",
        tax_id=f"{name}-{uuid.uuid4()}",
        whatsapp_phone="+5511999990000",
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp


def _hedge_payload() -> dict:
    return {
        "commodity": "ALUMINUM",
        "quantity_mt": "10.000000",
        "legs": [
            {"side": "buy", "price_type": "fixed"},
            {"side": "sell", "price_type": "variable"},
        ],
        "fixed_price_value": "2450.000000",
        "fixed_price_unit": "USD/MT",
        "float_pricing_convention": "avg",
    }


def _insert_deal(session) -> Deal:
    deal = Deal(
        reference=f"DEAL-{uuid.uuid4().hex[:8]}",
        name="RBAC deal",
        commodity="ALUMINUM",
        total_physical_tons=Decimal("0"),
        total_hedge_tons=Decimal("0"),
        hedge_ratio=Decimal("0"),
    )
    session.add(deal)
    session.commit()
    session.refresh(deal)
    return deal


def _insert_order(session) -> Order:
    order = Order(
        order_type=OrderType.sales,
        price_type=PriceType.fixed,
        commodity="ALUMINUM",
        quantity_mt=Decimal("10"),
        currency="USD",
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


def _insert_hedge_contract(session) -> HedgeContract:
    contract = HedgeContract(
        commodity="ALUMINUM",
        quantity_mt=Decimal("10"),
        fixed_leg_side="buy",
        variable_leg_side="sell",
        classification="long",
        status=HedgeContractStatus.active,
    )
    session.add(contract)
    session.commit()
    session.refresh(contract)
    return contract


def _insert_rfq(session) -> RFQ:
    rfq = RFQ(
        rfq_number=f"RFQ-{uuid.uuid4().hex[:8]}",
        intent=RFQIntent.global_position,
        commodity="ALUMINUM",
        quantity_mt=Decimal("10"),
        delivery_window_start=date(2026, 6, 1),
        delivery_window_end=date(2026, 6, 30),
        direction=RFQDirection.buy,
        commercial_active_mt=Decimal("0"),
        commercial_passive_mt=Decimal("0"),
        commercial_net_mt=Decimal("0"),
        commercial_reduction_applied_mt=Decimal("0"),
        exposure_snapshot_timestamp=datetime.now(timezone.utc),
        state=RFQState.created,
    )
    session.add(rfq)
    session.commit()
    session.refresh(rfq)
    return rfq


def test_get_current_actor_roles_filters_unknown_values() -> None:
    assert get_current_actor_roles(_as_roles("trader", "garbage", "admin")) == [
        "trader"
    ]


@pytest.mark.parametrize("roles", [("auditor", "trader"), ("auditor", "risk_manager")])
def test_get_current_actor_roles_rejects_auditor_mixed_roles(roles) -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_actor_roles(_as_roles(*roles))
    assert exc_info.value.status_code == 401
    assert "auditor must be exclusive" in exc_info.value.detail


def test_get_current_actor_roles_allows_dev_anonymous_broad_roles() -> None:
    assert get_current_actor_roles(
        _as_roles("trader", "risk_manager", "auditor", sub="anonymous")
    ) == ["auditor", "risk_manager", "trader"]


def test_get_current_actor_roles_accepts_trader_plus_risk_manager() -> None:
    assert get_current_actor_roles(_as_roles("trader", "risk_manager")) == [
        "risk_manager",
        "trader",
    ]


def test_require_service_identity_rejects_unknown_name() -> None:
    with pytest.raises(ValueError):
        require_service_identity("unknown_service")


@pytest.mark.parametrize(
    ("role", "type_", "expected_status"),
    [
        ("trader", "broker", 403),
        ("trader", "customer", 201),
        ("risk_manager", "broker", 201),
    ],
)
def test_counterparty_post_type_gate(
    client, auth_as, role: str, type_: str, expected_status: int
) -> None:
    auth_as(role)
    response = client.post(
        "/counterparties", json=_counterparty_payload(type_, f"post-{role}-{type_}")
    )
    assert response.status_code == expected_status


def test_counterparty_patch_trader_404s_broker(client, auth_as, session) -> None:
    broker = _insert_counterparty(session, CounterpartyType.broker, "broker patch")
    auth_as("trader")
    response = client.patch(f"/counterparties/{broker.id}", json={"city": "Rio"})
    assert response.status_code == 404


def test_counterparty_patch_trader_accepts_customer(client, auth_as, session) -> None:
    customer = _insert_counterparty(session, CounterpartyType.customer, "customer patch")
    auth_as("trader")
    response = client.patch(f"/counterparties/{customer.id}", json={"city": "Rio"})
    assert response.status_code == 200


def test_counterparty_delete_trader_404s_broker(client, auth_as, session) -> None:
    broker = _insert_counterparty(session, CounterpartyType.broker, "broker delete")
    auth_as("trader")
    response = client.delete(f"/counterparties/{broker.id}")
    assert response.status_code == 404


def test_counterparty_get_list_trader_filters_broker_bank(
    client, auth_as, session
) -> None:
    _insert_counterparty(session, CounterpartyType.customer, "customer list")
    _insert_counterparty(session, CounterpartyType.supplier, "supplier list")
    _insert_counterparty(session, CounterpartyType.broker, "broker list")
    _insert_counterparty(session, CounterpartyType.bank_br, "bank list")
    auth_as("trader")

    response = client.get("/counterparties")

    assert response.status_code == 200
    types = {item["type"] for item in response.json()["items"]}
    assert types == {"customer", "supplier"}


def test_counterparty_get_by_id_trader_404s_broker(client, auth_as, session) -> None:
    broker = _insert_counterparty(session, CounterpartyType.broker, "broker get")
    auth_as("trader")
    response = client.get(f"/counterparties/{broker.id}")
    assert response.status_code == 404


def test_counterparty_get_by_id_auditor_returns_broker(client, auth_as, session) -> None:
    broker = _insert_counterparty(session, CounterpartyType.broker, "auditor broker")
    auth_as("auditor")
    response = client.get(f"/counterparties/{broker.id}")
    assert response.status_code == 200


def test_westmetall_ingest_trader_rejected(client, auth_as) -> None:
    auth_as("trader")
    response = client.post(
        "/market-data/westmetall/aluminum/cash-settlement/ingest",
        json={"settlement_date": "2026-01-30"},
    )
    assert response.status_code == 403


def test_westmetall_ingest_service_identity_accepts(client, auth_as, monkeypatch) -> None:
    evidence = WestmetallFetchEvidence(
        source_url="https://example.test",
        html_sha256="abc123",
        fetched_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "app.api.routes.westmetall.ingest_westmetall_cash_settlement_daily_for_date",
        lambda session, settlement_date: (None, 0, 1, evidence),
    )
    auth_as(sub="service:westmetall_ingest")
    response = client.post(
        "/market-data/westmetall/aluminum/cash-settlement/ingest",
        json={"settlement_date": "2026-01-30"},
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("post", "/rfqs", {
            "intent": "GLOBAL_POSITION",
            "commodity": "ALUMINUM",
            "quantity_mt": "10.000000",
            "delivery_window_start": "2026-06-01",
            "delivery_window_end": "2026-06-30",
            "direction": "BUY",
            "invitations": [],
        }),
        ("post", "/rfqs/preview-text", {
            "channel_type": "whatsapp",
            "trade_type": "outright",
            "leg1": {
                "side": "buy",
                "price_type": "fixed",
                "quantity_mt": "1.000000",
                "month_name": "Jun",
                "year": 2026,
            },
            "company_header": "ACME",
            "company_label_for_payoff": "ACME",
        }),
        ("post", "/contracts/hedge", _hedge_payload()),
        ("post", "/deals", {"name": "RBAC deal", "commodity": "ALUMINUM"}),
    ],
)
def test_matrix_mutation_routes_reject_trader(client, auth_as, method, path, json_body):
    auth_as("trader")
    response = getattr(client, method)(path, json=json_body)
    assert response.status_code == 403


def test_rfq_award_trader_rejected(client, auth_as, session) -> None:
    rfq = _insert_rfq(session)
    auth_as("trader")
    response = client.post(f"/rfqs/{rfq.id}/actions/award", json={})
    assert response.status_code == 403


def test_deal_add_link_trader_rejected(client, auth_as, session) -> None:
    deal = _insert_deal(session)
    order = _insert_order(session)
    auth_as("trader")
    response = client.post(
        f"/deals/{deal.id}/links",
        json={"linked_type": "sales_order", "linked_id": str(order.id)},
    )
    assert response.status_code == 403


def test_linkage_create_trader_rejected(client, auth_as, session) -> None:
    order = _insert_order(session)
    contract = _insert_hedge_contract(session)
    auth_as("trader")
    response = client.post(
        "/linkages",
        json={
            "order_id": str(order.id),
            "contract_id": str(contract.id),
            "quantity_mt": "1.000000",
        },
    )
    assert response.status_code == 403


def test_exposure_reconcile_trader_rejected(client, auth_as) -> None:
    auth_as("trader")
    response = client.post("/exposures/reconcile")
    assert response.status_code == 403


def test_finance_pipeline_trader_rejected(client, auth_as) -> None:
    auth_as("trader")
    response = client.post("/finance/pipeline/run", json={"run_date": "2026-05-11"})
    assert response.status_code == 403


def test_ws_rfq_subscription_rejects_trader(client) -> None:
    from app.api.routes.ws import manager

    rfq_id = str(uuid.uuid4())
    with patch(
        "app.api.routes.ws._validate_token",
        return_value=_as_roles("trader"),
    ):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "authenticate", "token": "fake-jwt"})
            ws.receive_json()
            ws.send_json({"action": "subscribe", "topic": "rfq", "id": rfq_id})
            response = ws.receive_json()
            assert response["type"] == "subscription_error"
            assert response["reason"] == "forbidden"
            state = manager.get_state(ws)
            assert state is None or ("rfq", rfq_id) not in state.subscriptions


@pytest.mark.parametrize("role", ["risk_manager", "auditor"])
def test_ws_rfq_subscription_accepts_risk_manager_or_auditor(client, role) -> None:
    rfq_id = str(uuid.uuid4())
    with patch(
        "app.api.routes.ws._validate_token",
        return_value=_as_roles(role),
    ):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "authenticate", "token": "fake-jwt"})
            ws.receive_json()
            ws.send_json({"action": "subscribe", "topic": "rfq", "id": rfq_id})
            response = ws.receive_json()
            assert response["type"] == "subscription_ack"
            assert response["topic"] == "rfq"


def test_webhook_post_attributes_to_service_webhook_inbound(
    client, monkeypatch, session
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    monkeypatch.setattr(
        "app.api.routes.webhooks._executor.submit", lambda *args, **kwargs: None
    )
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.rbac",
                                    "from": "5511999990000",
                                    "timestamp": "1770000000",
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    response = client.post("/webhooks/whatsapp", json=payload)

    assert response.status_code == 200
    rows = session.query(AuditEvent).all()
    assert any(
        row.payload.get("metadata", {}).get("actor_sub") == "service:webhook_inbound"
        for row in rows
    )


def test_westmetall_scheduler_attributes_service_actor(monkeypatch, session) -> None:
    from app.tasks.westmetall_task import run_westmetall_ingestion

    evidence = WestmetallFetchEvidence(
        source_url="https://example.test",
        html_sha256="abc123",
        fetched_at=datetime.now(timezone.utc),
    )

    monkeypatch.setattr(
        "app.tasks.westmetall_task.ingest_westmetall_cash_settlement_bulk",
        lambda session: ([uuid.uuid4()], uuid.uuid4(), 1, 0, evidence),
    )

    run_westmetall_ingestion()

    rows = session.query(AuditEvent).all()
    assert any(
        row.payload.get("metadata", {}).get("actor_sub")
        == "service:westmetall_ingest"
        for row in rows
    )
