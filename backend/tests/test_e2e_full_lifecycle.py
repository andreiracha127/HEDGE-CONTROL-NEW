"""Item 3.7 – End-to-end lifecycle test.

Full flow: Order → RFQ → Quote → Award → Contract/Linkage → Settlement → P&L.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.contracts import HedgeContract
from app.models.linkages import HedgeOrderLinkage


# -- helpers ----------------------------------------------------------------


def _create_counterparty(client, name: str = "Counterparty 1") -> str:
    """Create a counterparty with whatsapp_phone and return its UUID."""
    resp = client.post(
        "/counterparties",
        json={
            "type": "broker",
            "name": name,
            "country": "BRA",
            "whatsapp_phone": "+5511999990001",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _create_sales_order(client, quantity_mt: float) -> str:
    resp = client.post(
        "/orders/sales",
        json={"price_type": "variable", "quantity_mt": quantity_mt},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _create_rfq(
    client,
    order_id: str,
    quantity_mt: float,
    direction: str = "SELL",
    counterparty_id: str | None = None,
) -> dict:
    if counterparty_id is None:
        counterparty_id = _create_counterparty(client)
    resp = client.post(
        "/rfqs",
        json={
            "intent": "COMMERCIAL_HEDGE",
            "commodity": "ALUMINUM",
            "quantity_mt": quantity_mt,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": direction,
            "order_id": order_id,
            "invitations": [{"counterparty_id": counterparty_id}],
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _submit_quote(client, rfq_id: str, counterparty_id: str) -> dict:
    resp = client.post(
        f"/rfqs/{rfq_id}/quotes",
        json={
            "rfq_id": rfq_id,
            "counterparty_id": counterparty_id,
            "fixed_price_value": 2400.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _award(client, rfq_id: str) -> dict:
    resp = client.post(f"/rfqs/{rfq_id}/actions/award", json={"user_id": "U1"})
    assert resp.status_code == 200
    return resp.json()


def _settle_contract(client, contract_id: str) -> dict:
    resp = client.post(
        f"/cashflow/contracts/{contract_id}/settle",
        json={
            "source_event_id": str(uuid.uuid4()),
            "cashflow_date": "2026-03-15",
            "currency": "USD",
            "legs": [
                {"leg_id": "FIXED", "direction": "IN", "amount": "12000.00"},
                {"leg_id": "FLOAT", "direction": "OUT", "amount": "11500.00"},
            ],
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _commercial_row(response):
    rows = response.json()
    return next(row for row in rows if row["commodity"] == "ALUMINUM")


def _dec(value) -> Decimal:
    return Decimal(str(value))


# -- lifecycle test ---------------------------------------------------------


def test_full_lifecycle_order_to_pl(client) -> None:
    """Order → RFQ → Quote → Award → Contract → Settlement → P&L."""

    # Step 1 – Create a sales order
    order_id = _create_sales_order(client, 10.0)

    # Step 1b – Create a counterparty for RFQ invitations
    cp_id = _create_counterparty(client)

    # Step 2 – Verify commercial exposure increases
    exposure_before = client.get("/exposures/commercial")
    assert exposure_before.status_code == 200
    before_row = _commercial_row(exposure_before)
    assert _dec(before_row["commercial_active_mt"]) > Decimal("0")

    # Step 3 – Create an RFQ for a commercial hedge
    rfq = _create_rfq(client, order_id, 5.0, counterparty_id=cp_id)
    assert rfq["state"] == "SENT"
    rfq_id = rfq["id"]

    # Step 4 – Submit a quote → state becomes QUOTED
    _submit_quote(client, rfq_id, cp_id)
    rfq_state = client.get(f"/rfqs/{rfq_id}")
    assert rfq_state.status_code == 200
    assert rfq_state.json()["state"] == "QUOTED"

    # Step 5 – Award → RFQ closes, contract + linkage created
    awarded = _award(client, rfq_id)
    assert awarded["state"] == "CLOSED"

    with SessionLocal() as session:
        contracts = session.query(HedgeContract).all()
        linkages = session.query(HedgeOrderLinkage).all()
        assert len(contracts) == 1
        assert len(linkages) == 1
        contract_id = str(contracts[0].id)

    # Step 6 – Exposure reduced after linkage
    exposure_after = client.get("/exposures/commercial")
    assert exposure_after.status_code == 200
    after_row = _commercial_row(exposure_after)
    assert _dec(after_row["commercial_active_mt"]) < _dec(
        before_row["commercial_active_mt"]
    )

    # Step 7 – Settle the contract
    settlement = _settle_contract(client, contract_id)
    assert "event" in settlement
    assert len(settlement["ledger_entries"]) == 2

    # Step 8 – Verify ledger entries exist
    ledger_resp = client.get(f"/cashflow/ledger/hedge-contracts/{contract_id}")
    assert ledger_resp.status_code == 200
    assert len(ledger_resp.json()) == 2

    # Step 9 – Compute P&L (should succeed; settlement was ingested so
    # realized_pl comes from the ledger entries).
    pl_resp = client.get(
        f"/pl/hedge_contract/{contract_id}",
        params={"period_start": "2026-03-01", "period_end": "2026-03-31"},
    )
    assert pl_resp.status_code == 200
    pl_data = pl_resp.json()
    assert "realized_pl" in pl_data
    assert "unrealized_mtm" in pl_data
