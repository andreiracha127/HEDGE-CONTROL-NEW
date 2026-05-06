"""PR-8 (J-A1-01 / S-A1-J-01) — DealPNLSnapshot.price_references.

Covers acceptance criteria §6.2 of the dispatch:
* per-commodity provenance dict (single + multi-commodity)
* weekend lookback returns the actual settlement_date used
* deduplication across multiple legs of the same commodity
* idempotency contract (post-PR-8 only)
* hash determinism — different price for ANY commodity → different hash
* model-level @validates rejects {} and incomplete entries (portable)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.counterparty import Counterparty
from app.models.deal import DealPNLSnapshot
from app.models.market_data import CashSettlementPrice
from app.models.orders import Order, OrderType, PriceType
from app.services.deal_engine import DealEngineService, _compute_inputs_hash

ENDPOINT = "/deals"


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _create_counterparty(session) -> uuid.UUID:
    cp = Counterparty(
        type="customer",
        name=f"Cpty-{uuid.uuid4().hex[:6]}",
        country="BRA",
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp.id


def _create_order(
    session,
    order_type: OrderType,
    *,
    qty: Decimal = Decimal("100"),
    price: Decimal = Decimal("2500"),
    price_type: PriceType = PriceType.variable,
    commodity: str = "ALUMINUM",
) -> uuid.UUID:
    order = Order(
        order_type=order_type,
        price_type=price_type,
        commodity=commodity,
        quantity_mt=qty,
        avg_entry_price=price,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order.id


def _create_active_hedge(
    session,
    cp_id: uuid.UUID,
    *,
    classification: HedgeClassification,
    commodity: str,
    qty: Decimal = Decimal("100"),
) -> uuid.UUID:
    fixed_side = (
        HedgeLegSide.buy
        if classification == HedgeClassification.long
        else HedgeLegSide.sell
    )
    var_side = (
        HedgeLegSide.sell if fixed_side == HedgeLegSide.buy else HedgeLegSide.buy
    )
    contract = HedgeContract(
        reference=f"HC-{uuid.uuid4().hex[:8].upper()}",
        counterparty_id=str(cp_id),
        commodity=commodity,
        quantity_mt=qty,
        fixed_price_value=Decimal("2450"),
        fixed_price_unit="USD/MT",
        fixed_leg_side=fixed_side,
        variable_leg_side=var_side,
        classification=classification,
        premium_discount=Decimal("0"),
        settlement_date=date(2026, 9, 30),
        trade_date=date(2026, 1, 1),
        status=HedgeContractStatus.active,
        source_type="manual",
    )
    session.add(contract)
    session.commit()
    session.refresh(contract)
    return contract.id


def _insert_price(
    session,
    *,
    symbol: str,
    settlement_date: date,
    price_usd: float,
    source: str = "westmetall",
) -> None:
    session.add(
        CashSettlementPrice(
            source=source,
            symbol=symbol,
            settlement_date=settlement_date,
            price_usd=price_usd,
            source_url="https://example.test/source",
            html_sha256="0" * 64,
            fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    session.commit()


# ──────────────────────────────────────────────────────────────────────
# §6.2 — single-commodity variable-price provenance populated
# ──────────────────────────────────────────────────────────────────────


class TestSingleCommodityProvenance:
    def test_single_commodity_provenance_populated(self, client, session):
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=2700.0,
        )
        r = client.post(ENDPOINT, json={"name": "Single", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        so_id = _create_order(session, OrderType.sales)
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 201
        prov = r2.json()["price_references"]
        assert set(prov.keys()) == {"ALUMINUM"}
        entry = prov["ALUMINUM"]
        assert set(entry.keys()) == {"value", "source", "settlement_date"}
        assert entry["settlement_date"] == "2026-01-31"
        assert entry["source"] == "westmetall"


# ──────────────────────────────────────────────────────────────────────
# §6.2 — multi-commodity: both keys populated; correction → new row
# ──────────────────────────────────────────────────────────────────────


class TestMultiCommodityProvenance:
    def test_multi_commodity_aluminum_plus_copper_hedge(self, client, session):
        # Aluminum SO needs ALU price; Copper hedge needs CU price.
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=2700.0,
        )
        _insert_price(
            session,
            symbol="LME_CU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=9100.0,
        )

        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json={"name": "Multi", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]

        # Variable-price ALU SO + active COPPER short hedge (different
        # commodity from the deal-level commodity is allowed since the
        # deal model only has a string commodity field).
        so_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price_type=PriceType.variable,
            commodity="ALUMINUM",
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )

        cu_hedge_id = _create_active_hedge(
            session,
            cp_id,
            classification=HedgeClassification.short,
            commodity="COPPER",
            qty=Decimal("50"),
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "hedge", "linked_id": str(cu_hedge_id)},
        )

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 201
        prov = r2.json()["price_references"]
        assert set(prov.keys()) == {"ALUMINUM", "COPPER"}
        assert Decimal(prov["ALUMINUM"]["value"]) == Decimal("2700.0")
        assert Decimal(prov["COPPER"]["value"]) == Decimal("9100.0")

    def test_correction_to_one_commodity_yields_new_row(self, client, session):
        """Correcting Copper price → different inputs_hash → new row."""
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=2700.0,
        )
        _insert_price(
            session,
            symbol="LME_CU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=9100.0,
        )

        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json={"name": "Corr", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        so_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price_type=PriceType.variable,
            commodity="ALUMINUM",
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )
        hedge_id = _create_active_hedge(
            session,
            cp_id,
            classification=HedgeClassification.short,
            commodity="COPPER",
            qty=Decimal("50"),
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "hedge", "linked_id": str(hedge_id)},
        )

        r1 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        snap1 = r1.json()
        # Now correct the Copper price (LME republishes).
        with SessionLocal() as s:
            row = (
                s.query(CashSettlementPrice)
                .filter(
                    CashSettlementPrice.symbol == "LME_CU_CASH_SETTLEMENT_DAILY"
                )
                .first()
            )
            row.price_usd = 9200.0
            s.commit()

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        snap2 = r2.json()
        assert snap1["inputs_hash"] != snap2["inputs_hash"]
        assert snap1["id"] != snap2["id"]
        with SessionLocal() as s:
            assert s.query(DealPNLSnapshot).count() == 2


# ──────────────────────────────────────────────────────────────────────
# §6.2 — weekend lookback: settlement_date is the actual row's date
# ──────────────────────────────────────────────────────────────────────


class TestWeekendLookback:
    def test_monday_snapshot_falls_back_to_friday_settlement(
        self, client, session
    ):
        # 2026-02-02 is a Monday → nominal D-1 is 2026-02-01 (Sunday).
        # Only Friday 2026-01-30 has a published price → provenance
        # MUST report 2026-01-30, not Sunday 2026-02-01.
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 30),
            price_usd=2755.5,
        )
        r = client.post(ENDPOINT, json={"name": "Mon", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        so_id = _create_order(session, OrderType.sales)
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-02"},
        )
        assert r2.status_code == 201
        prov = r2.json()["price_references"]
        assert prov["ALUMINUM"]["settlement_date"] == "2026-01-30"


# ──────────────────────────────────────────────────────────────────────
# §6.2 — deduplication: 2 legs of the same commodity → 1 entry
# ──────────────────────────────────────────────────────────────────────


class TestDeduplication:
    def test_two_legs_same_commodity_one_entry(self, client, session):
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=2700.0,
        )
        r = client.post(ENDPOINT, json={"name": "Dedup", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        so_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price_type=PriceType.variable,
        )
        po_id = _create_order(
            session,
            OrderType.purchase,
            qty=Decimal("80"),
            price_type=PriceType.variable,
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "purchase_order", "linked_id": str(po_id)},
        )

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 201
        prov = r2.json()["price_references"]
        assert list(prov.keys()) == ["ALUMINUM"]


# ──────────────────────────────────────────────────────────────────────
# §6.2 — idempotency (post-PR-8): same inputs → same row
# ──────────────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_same_inputs_returns_same_snapshot(self, client, session):
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=2700.0,
        )
        r = client.post(ENDPOINT, json={"name": "Idem", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        so_id = _create_order(session, OrderType.sales)
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )

        r1 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r1.json()["id"] == r2.json()["id"]
        assert r1.json()["inputs_hash"] == r2.json()["inputs_hash"]
        with SessionLocal() as s:
            assert s.query(DealPNLSnapshot).count() == 1


# ──────────────────────────────────────────────────────────────────────
# §6.2 — _compute_inputs_hash includes price_references determ.
# ──────────────────────────────────────────────────────────────────────


class TestInputsHashIncludesProvenance:
    def test_hash_includes_price_references_via_json_dumps_sortkeys(self):
        deal_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        snap_date = date(2026, 2, 1)
        link_id = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
        prov = {
            "ALUMINUM": {
                "value": "2700.0",
                "source": "westmetall",
                "settlement_date": "2026-01-31",
            }
        }
        actual = _compute_inputs_hash(deal_id, snap_date, [link_id], prov)
        # Reconstruct the canonical bytes the function MUST hash.
        expected = hashlib.sha256(
            json.dumps(
                {
                    "deal_id": str(deal_id),
                    "snapshot_date": str(snap_date),
                    "links": [str(link_id)],
                    "price_references": prov,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        assert actual == expected

    def test_hash_differs_when_any_inner_value_changes(self):
        deal_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        snap_date = date(2026, 2, 1)
        link_ids: list[uuid.UUID] = []
        h1 = _compute_inputs_hash(
            deal_id,
            snap_date,
            link_ids,
            {
                "ALUMINUM": {
                    "value": "2700.0",
                    "source": "westmetall",
                    "settlement_date": "2026-01-31",
                }
            },
        )
        h2 = _compute_inputs_hash(
            deal_id,
            snap_date,
            link_ids,
            {
                "ALUMINUM": {
                    "value": "2701.0",  # corrected
                    "source": "westmetall",
                    "settlement_date": "2026-01-31",
                }
            },
        )
        assert h1 != h2

    def test_hash_differs_between_null_and_empty_object(self):
        deal_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        snap_date = date(2026, 2, 1)
        h_null = _compute_inputs_hash(deal_id, snap_date, [], None)
        # Pre-PR-8 hash format (no price_references key) — recompute the
        # OLD-format hash and assert it differs from the post-PR-8 one
        # even when no market price was consulted. Guarantees no
        # cross-format collision.
        old = hashlib.sha256(
            json.dumps(
                {
                    "deal_id": str(deal_id),
                    "snapshot_date": str(snap_date),
                    "links": [],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        assert h_null != old


# ──────────────────────────────────────────────────────────────────────
# §6.2 — model @validates: portable shape enforcement on SQLite
# ──────────────────────────────────────────────────────────────────────


class TestPriceReferencesValidator:
    def test_empty_dict_rejected(self):
        with pytest.raises(ValueError, match="non-empty dict"):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={},
            )

    def test_inner_missing_keys_rejected(self):
        with pytest.raises(ValueError, match="missing required key"):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={"ALUMINUM": {"value": "1"}},
            )

    def test_inner_not_a_dict_rejected(self):
        with pytest.raises(ValueError, match="must be a dict"):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={"ALUMINUM": "scalar"},
            )

    def test_null_accepted(self):
        snap = DealPNLSnapshot(
            deal_id=uuid.uuid4(),
            snapshot_date=date(2026, 2, 1),
            inputs_hash="x" * 64,
            price_references=None,
        )
        assert snap.price_references is None

    def test_well_formed_dict_accepted(self):
        snap = DealPNLSnapshot(
            deal_id=uuid.uuid4(),
            snapshot_date=date(2026, 2, 1),
            inputs_hash="x" * 64,
            price_references={
                "ALUMINUM": {
                    "value": "2700.0",
                    "source": "westmetall",
                    "settlement_date": "2026-01-31",
                }
            },
        )
        assert snap.price_references is not None
