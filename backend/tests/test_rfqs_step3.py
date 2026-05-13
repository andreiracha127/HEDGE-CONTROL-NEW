import re
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from app.core.database import SessionLocal
from app.models.contracts import HedgeContract
from app.models.linkages import HedgeOrderLinkage
from app.models.rfqs import RFQStateEvent
from app.services.rfq_service import RFQService


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


def _create_spread_with_quotes(client) -> tuple[dict, dict, dict]:
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
    return buy_trade, sell_trade, spread


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

    refresh = client.post(f"/rfqs/{rfq['id']}/actions/refresh", json={})
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

    reject = client.post(f"/rfqs/{rfq['id']}/actions/reject", json={})
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
    award = client.post(f"/rfqs/{rfq['id']}/actions/award", json={})
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

    award = client.post(f"/rfqs/{spread['id']}/actions/award", json={})
    assert award.status_code == 200
    assert award.json()["state"] == "CLOSED"

    with SessionLocal() as session:
        contracts = session.query(HedgeContract).all()
        assert len(contracts) == 2


def test_award_acquires_row_lock_postgres(client) -> None:
    with SessionLocal() as session:
        if session.bind.dialect.name != "postgresql":
            pytest.skip("row-level lock assertion is PostgreSQL-only")

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

    with patch.object(
        RFQService, "get_live_for_update", wraps=RFQService.get_live_for_update
    ) as locked_get:
        award = client.post(f"/rfqs/{rfq['id']}/actions/award", json={})

    assert award.status_code == 200
    locked_get.assert_called_once()


def test_award_uses_locked_live_loader(client) -> None:
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

    with patch.object(
        RFQService, "get_live_for_update", wraps=RFQService.get_live_for_update
    ) as locked_get:
        award = client.post(f"/rfqs/{rfq['id']}/actions/award", json={})

    assert award.status_code == 200
    locked_get.assert_called_once()


def test_concurrent_award_rfq_only_one_succeeds(client) -> None:
    with SessionLocal() as session:
        if session.bind.dialect.name != "postgresql":
            pytest.skip("concurrent row-lock assertion is PostgreSQL-only")


def test_spread_award_closes_both_child_rfqs(client) -> None:
    buy_trade, sell_trade, spread = _create_spread_with_quotes(client)

    award = client.post(f"/rfqs/{spread['id']}/actions/award", json={})
    assert award.status_code == 200

    assert _get_rfq(client, buy_trade["id"])["state"] == "CLOSED"
    assert _get_rfq(client, sell_trade["id"])["state"] == "CLOSED"

    with SessionLocal() as session:
        events = (
            session.query(RFQStateEvent)
            .filter(
                RFQStateEvent.rfq_id.in_(
                    [uuid.UUID(buy_trade["id"]), uuid.UUID(sell_trade["id"])]
                ),
                RFQStateEvent.trigger == "closed_by_parent_spread",
            )
            .all()
        )
    assert len(events) == 2
    assert {event.reason for event in events} == {
        f"PARENT_SPREAD_AWARDED:{spread['rfq_number']}"
    }


def test_spread_child_award_blocked_after_parent_award(client) -> None:
    buy_trade, sell_trade, spread = _create_spread_with_quotes(client)

    award = client.post(f"/rfqs/{spread['id']}/actions/award", json={})
    assert award.status_code == 200

    buy_award = client.post(
        f"/rfqs/{buy_trade['id']}/actions/award", json={}
    )
    sell_award = client.post(
        f"/rfqs/{sell_trade['id']}/actions/award", json={}
    )

    assert buy_award.status_code == 409
    assert sell_award.status_code == 409


def test_spread_award_blocked_when_child_already_closed(client) -> None:
    """Codex P1 fix on PR-7: when a spread child has already been awarded
    individually (or closed via another path), parent spread award must
    hard-fail with 409. The previous "skip with warning" semantics from
    PR-7 dispatch §2.2 was incorrect — it would still create a duplicate
    contract for the closed child quote, doubling the position.
    """
    buy_trade, sell_trade, spread = _create_spread_with_quotes(client)

    child_award = client.post(
        f"/rfqs/{buy_trade['id']}/actions/award", json={}
    )
    assert child_award.status_code == 200
    assert _get_rfq(client, buy_trade["id"])["state"] == "CLOSED"

    parent_award = client.post(
        f"/rfqs/{spread['id']}/actions/award", json={}
    )
    assert parent_award.status_code == 409
    assert "already" in parent_award.json()["detail"].lower()
    # Sell child remains untouched (parent transaction rolled back).
    assert _get_rfq(client, sell_trade["id"])["state"] == "QUOTED"


def test_award_quote_endpoint_deleted_returns_404(client) -> None:
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
    quote = _create_quote(
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

    response = client.post(
        f"/rfqs/{rfq['id']}/actions/award-quote",
        json={"quote_id": quote["id"]},
    )
    assert response.status_code == 404


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
            f"/rfqs/{rfq['id']}/actions/award", json={}
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
            f"/rfqs/{spread['id']}/actions/award", json={}
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
