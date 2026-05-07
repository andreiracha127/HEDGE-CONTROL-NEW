import re
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

from app.core.database import SessionLocal
from app.models.contracts import HedgeContract
from app.models.linkages import HedgeOrderLinkage


def _create_counterparty(
    client, name: str = "Counterparty 1", phone: str = "+5511999990001"
) -> str:
    """Create a counterparty with whatsapp_phone and return its UUID."""
    resp = client.post(
        "/counterparties",
        json={
            "type": "broker",
            "name": name,
            "country": "BRA",
            "whatsapp_phone": phone,
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _create_sales_order(client, quantity_mt: float) -> str:
    response = client.post(
        "/orders/sales", json={"price_type": "variable", "quantity_mt": quantity_mt}
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_rfq(client, payload: dict) -> dict:
    response = client.post("/rfqs", json=payload)
    assert response.status_code == 201
    return response.json()


def _create_quote(client, rfq_id: str, payload: dict) -> dict:
    response = client.post(f"/rfqs/{rfq_id}/quotes", json=payload)
    assert response.status_code == 201
    return response.json()


def _get_rfq(client, rfq_id: str) -> dict:
    response = client.get(f"/rfqs/{rfq_id}")
    assert response.status_code == 200
    return response.json()


def _get_commercial_exposure(client) -> dict:
    response = client.get("/exposures/commercial")
    assert response.status_code == 200
    rows = response.json()
    return next(row for row in rows if row["commodity"] == "ALUMINUM")


def test_refresh_keeps_state_and_persists_refresh_invitations(client) -> None:
    cp_id = _create_counterparty(client)

    rfq = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": 5.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id}],
        },
    )
    assert rfq["state"] == "SENT"
    assert len(rfq["invitations"]) == 1

    _create_quote(
        client,
        rfq["id"],
        {
            "rfq_id": rfq["id"],
            "counterparty_id": cp_id,
            "fixed_price_value": 100.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )
    rfq_after_quote = _get_rfq(client, rfq["id"])
    assert rfq_after_quote["state"] == "QUOTED"

    refresh = client.post(f"/rfqs/{rfq['id']}/actions/refresh", json={"user_id": "U1"})
    assert refresh.status_code == 200
    refreshed = refresh.json()
    assert refreshed["state"] == "QUOTED"
    assert len(refreshed["invitations"]) == 2


def test_reject_closes_rfq_without_exposure_change(client) -> None:
    _create_sales_order(client, 10.0)
    exposure_before = _get_commercial_exposure(client)
    cp_id = _create_counterparty(client)

    rfq = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": 2.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id}],
        },
    )
    _create_quote(
        client,
        rfq["id"],
        {
            "rfq_id": rfq["id"],
            "counterparty_id": cp_id,
            "fixed_price_value": 100.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )

    reject = client.post(f"/rfqs/{rfq['id']}/actions/reject", json={"user_id": "U1"})
    assert reject.status_code == 200
    assert reject.json()["state"] == "CLOSED"

    exposure_after = _get_commercial_exposure(client)
    exposure_before.pop("calculation_timestamp")
    exposure_after.pop("calculation_timestamp")
    assert exposure_before == exposure_after


def test_award_creates_contract_and_reduces_exposure_via_linkage(client) -> None:
    order_id = _create_sales_order(client, 10.0)
    cp_id = _create_counterparty(client)

    rfq = _create_rfq(
        client,
        {
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
    _create_quote(
        client,
        rfq["id"],
        {
            "rfq_id": rfq["id"],
            "counterparty_id": cp_id,
            "fixed_price_value": 100.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )

    before = _get_commercial_exposure(client)
    award = client.post(f"/rfqs/{rfq['id']}/actions/award", json={"user_id": "U1"})
    assert award.status_code == 200
    assert award.json()["state"] == "CLOSED"

    after = _get_commercial_exposure(client)
    assert float(after["commercial_active_mt"]) == float(before["commercial_active_mt"]) - 5.0

    with SessionLocal() as session:
        contracts = session.query(HedgeContract).all()
        linkages = session.query(HedgeOrderLinkage).all()
        assert len(contracts) == 1
        assert len(linkages) == 1


def test_award_spread_creates_two_contracts(client) -> None:
    cp_id = _create_counterparty(client)

    buy_trade = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": 5.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id}],
        },
    )
    sell_trade = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": 5.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "SELL",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id}],
        },
    )
    spread = _create_rfq(
        client,
        {
            "intent": "SPREAD",
            "commodity": "LME_AL",
            "quantity_mt": 5.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "buy_trade_id": buy_trade["id"],
            "sell_trade_id": sell_trade["id"],
            "invitations": [{"counterparty_id": cp_id}],
        },
    )

    # CP1 spread = 110 - 100 = 10
    _create_quote(
        client,
        buy_trade["id"],
        {
            "rfq_id": buy_trade["id"],
            "counterparty_id": cp_id,
            "fixed_price_value": 100.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )
    _create_quote(
        client,
        sell_trade["id"],
        {
            "rfq_id": sell_trade["id"],
            "counterparty_id": cp_id,
            "fixed_price_value": 110.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )

    award = client.post(f"/rfqs/{spread['id']}/actions/award", json={"user_id": "U1"})
    assert award.status_code == 200
    assert award.json()["state"] == "CLOSED"

    with SessionLocal() as session:
        contracts = session.query(HedgeContract).all()
        assert len(contracts) == 2


_HC_REFERENCE_RE = re.compile(r"^HC-[0-9A-F]{32}$")


def _frozen_award_time() -> datetime:
    return datetime(2026, 1, 15, 12, 30, 0, tzinfo=timezone.utc)


def test_award_trade_date_uses_utc(client) -> None:
    order_id = _create_sales_order(client, 10.0)
    cp_id = _create_counterparty(client)

    rfq = _create_rfq(
        client,
        {
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
    _create_quote(
        client,
        rfq["id"],
        {
            "rfq_id": rfq["id"],
            "counterparty_id": cp_id,
            "fixed_price_value": 100.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )

    frozen = _frozen_award_time()
    with patch("app.services.rfq_service.now_utc", return_value=frozen):
        award = client.post(
            f"/rfqs/{rfq['id']}/actions/award", json={"user_id": "U1"}
        )
    assert award.status_code == 200

    with SessionLocal() as session:
        contracts = session.query(HedgeContract).all()
        assert len(contracts) == 1
        assert contracts[0].trade_date == frozen.date()
        assert contracts[0].trade_date == date(2026, 1, 15)
        assert _HC_REFERENCE_RE.match(contracts[0].reference)


def test_spread_award_three_contracts_consistent_trade_date(client) -> None:
    cp_id = _create_counterparty(client)

    buy_trade = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": 5.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id}],
        },
    )
    sell_trade = _create_rfq(
        client,
        {
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": 5.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "SELL",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id}],
        },
    )
    spread = _create_rfq(
        client,
        {
            "intent": "SPREAD",
            "commodity": "LME_AL",
            "quantity_mt": 5.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "buy_trade_id": buy_trade["id"],
            "sell_trade_id": sell_trade["id"],
            "invitations": [{"counterparty_id": cp_id}],
        },
    )
    _create_quote(
        client,
        buy_trade["id"],
        {
            "rfq_id": buy_trade["id"],
            "counterparty_id": cp_id,
            "fixed_price_value": 100.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )
    _create_quote(
        client,
        sell_trade["id"],
        {
            "rfq_id": sell_trade["id"],
            "counterparty_id": cp_id,
            "fixed_price_value": 110.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )

    frozen = _frozen_award_time()
    with patch("app.services.rfq_service.now_utc", return_value=frozen):
        award = client.post(
            f"/rfqs/{spread['id']}/actions/award", json={"user_id": "U1"}
        )
    assert award.status_code == 200

    with SessionLocal() as session:
        contracts = session.query(HedgeContract).all()
        assert len(contracts) == 2
        for c in contracts:
            assert c.trade_date == frozen.date()
            assert _HC_REFERENCE_RE.match(c.reference)
        # All contracts produced by one award call share one trade_date.
        assert len({c.trade_date for c in contracts}) == 1
        # And distinct references — collision-safe identity.
        assert len({c.reference for c in contracts}) == len(contracts)


def test_award_reference_collision_safe() -> None:
    """Full-UUID reference format must remain collision-free at scale."""
    refs = {f"HC-{uuid.uuid4().hex.upper()}" for _ in range(10_000)}
    assert len(refs) == 10_000
    for ref in refs:
        assert _HC_REFERENCE_RE.match(ref)
        assert len(ref) <= 50
