"""PR-8 (J-A1-01) — hard-fail behavior on missing market price.

Covers acceptance criteria §6.1 of the dispatch
(``docs/audits/2026-05-06-phase-a1-pr-8-pnl-price-evidence-dispatch.md``):
no silent fallbacks in ``_get_market_quote``, ``_order_value``, or
``compute_deal_pnl``; the route returns 422 with no snapshot persisted.
"""

from __future__ import annotations

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
from app.services.deal_engine import DealEngineService
from app.services.price_lookup_service import PriceReferenceUnprovable

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
    price_type: PriceType = PriceType.fixed,
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
    session, cp_id: uuid.UUID, *, classification: HedgeClassification, commodity: str
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
        quantity_mt=Decimal("100"),
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
# §6.1 — hard-fail: variable-price physical leg without market price
# ──────────────────────────────────────────────────────────────────────


class TestHardFailVariablePricePhysical:
    def test_variable_price_so_missing_market_returns_422(self, client, session):
        """variable-price SO + no D-1 price → 422, no snapshot persisted."""
        r = client.post(ENDPOINT, json={"name": "VarSO", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]

        so_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price=Decimal("2600"),
            price_type=PriceType.variable,
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 422
        # No snapshot must have been persisted.
        with SessionLocal() as s:
            snaps = s.query(DealPNLSnapshot).all()
            assert snaps == []

    def test_variable_price_po_missing_market_returns_422(self, client, session):
        r = client.post(ENDPOINT, json={"name": "VarPO", "commodity": "COPPER"})
        deal_id = r.json()["id"]

        po_id = _create_order(
            session,
            OrderType.purchase,
            qty=Decimal("50"),
            price=Decimal("9000"),
            price_type=PriceType.variable,
            commodity="COPPER",
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "purchase_order", "linked_id": str(po_id)},
        )

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 422
        with SessionLocal() as s:
            assert s.query(DealPNLSnapshot).count() == 0


# ──────────────────────────────────────────────────────────────────────
# §6.1 — hard-fail: active hedge MTM without market price
# ──────────────────────────────────────────────────────────────────────


class TestHardFailActiveHedge:
    def test_active_hedge_missing_market_returns_422(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json={"name": "Hedged", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]

        # Variable-price SO so a short hedge can be linked.
        so_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price_type=PriceType.variable,
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )

        hedge_id = _create_active_hedge(
            session,
            cp_id,
            classification=HedgeClassification.short,
            commodity="ALUMINUM",
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "hedge", "linked_id": str(hedge_id)},
        )

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 422
        with SessionLocal() as s:
            assert s.query(DealPNLSnapshot).count() == 0


# ──────────────────────────────────────────────────────────────────────
# §6.1 — fixed-price-only deal: snapshot persists with NULL provenance
# ──────────────────────────────────────────────────────────────────────


class TestFixedPriceOnlyAllowed:
    def test_fixed_only_no_hedge_persists_with_null_references(
        self, client, session
    ):
        r = client.post(ENDPOINT, json={"name": "FixedOnly", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]

        so_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price=Decimal("2600"),
            price_type=PriceType.fixed,
        )
        po_id = _create_order(
            session,
            OrderType.purchase,
            qty=Decimal("100"),
            price=Decimal("2400"),
            price_type=PriceType.fixed,
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
        body = r2.json()
        assert body["price_references"] is None
        assert body["physical_revenue"] == "260000.000000"
        assert body["physical_cost"] == "240000.000000"
        assert body["total_pnl"] == "20000.000000"


# ──────────────────────────────────────────────────────────────────────
# §6.1 — mixed deal: fixed + variable, only variable-commodity missing
# ──────────────────────────────────────────────────────────────────────


class TestMixedDealHardFails:
    def test_mixed_fixed_and_variable_missing_market_returns_422(
        self, client, session
    ):
        r = client.post(ENDPOINT, json={"name": "Mixed", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]

        # Fixed-price PO (no market evidence needed).
        po_id = _create_order(
            session,
            OrderType.purchase,
            qty=Decimal("100"),
            price=Decimal("2400"),
            price_type=PriceType.fixed,
        )
        # Variable-price SO (needs market evidence — none in DB → 422).
        so_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price_type=PriceType.variable,
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "purchase_order", "linked_id": str(po_id)},
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 422
        with SessionLocal() as s:
            assert s.query(DealPNLSnapshot).count() == 0


# ──────────────────────────────────────────────────────────────────────
# §6.1 — direct service-level assertions (no fallback paths exist)
# ──────────────────────────────────────────────────────────────────────


class TestServiceLevelHardFails:
    def test_order_value_raises_on_variable_missing_market(self, session):
        """_order_value MUST raise — no avg_entry_price fallback for variable."""
        order_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price=Decimal("2500"),
            price_type=PriceType.variable,
        )
        order = session.get(Order, order_id)
        with pytest.raises(PriceReferenceUnprovable):
            DealEngineService._order_value(order, None)

    def test_order_value_fixed_uses_avg_entry_price_unchanged(self, session):
        """Fixed-price orders are unaffected — avg_entry_price IS the contract."""
        order_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price=Decimal("2500"),
            price_type=PriceType.fixed,
        )
        order = session.get(Order, order_id)
        # market_price=None must NOT raise for fixed-price orders.
        value = DealEngineService._order_value(order, None)
        assert value == Decimal("250000.000000")

    def test_compute_deal_pnl_raises_priceunprovable_when_market_missing(
        self, client, session
    ):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json={"name": "Svc", "commodity": "ALUMINUM"})
        deal_id_str = r.json()["id"]

        so_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price_type=PriceType.variable,
        )
        client.post(
            f"{ENDPOINT}/{deal_id_str}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )
        hedge_id = _create_active_hedge(
            session,
            cp_id,
            classification=HedgeClassification.short,
            commodity="ALUMINUM",
        )
        client.post(
            f"{ENDPOINT}/{deal_id_str}/links",
            json={"linked_type": "hedge", "linked_id": str(hedge_id)},
        )

        deal_uuid = uuid.UUID(deal_id_str)
        with SessionLocal() as s:
            with pytest.raises(PriceReferenceUnprovable):
                DealEngineService.compute_deal_pnl(s, deal_uuid, date(2026, 2, 1))


# ──────────────────────────────────────────────────────────────────────
# §6.1 — happy path with provenance populated
# ──────────────────────────────────────────────────────────────────────


class TestHappyPathProvenance:
    def test_variable_price_with_published_price_persists_provenance(
        self, client, session
    ):
        # Insert D-1 settlement price for ALUMINUM.
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=2700.0,
        )

        r = client.post(ENDPOINT, json={"name": "Var", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        so_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price_type=PriceType.variable,
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 201
        body = r2.json()
        prov = body["price_references"]
        assert prov is not None
        assert "ALUMINUM" in prov
        assert prov["ALUMINUM"]["source"] == "westmetall"
        assert prov["ALUMINUM"]["settlement_date"] == "2026-01-31"
        assert Decimal(prov["ALUMINUM"]["value"]) == Decimal("2700.0")
        # revenue = 100 * 2700 = 270000
        assert body["physical_revenue"] == "270000.000000"


# ──────────────────────────────────────────────────────────────────────
# §6.1 — compute_pnl_breakdown: per-commodity pricing parity with
# compute_deal_pnl when legs/hedges differ from deal-level commodity.
# (Codex P2 follow-up — see PR #22 review.)
# ──────────────────────────────────────────────────────────────────────


class TestBreakdownPerCommodityPricing:
    """compute_pnl_breakdown must use the leg's own commodity price.

    Prior implementation looked up a single price for ``deal.commodity``
    and applied it to every leg/hedge, which either hard-failed when
    ``deal.commodity`` had no price (but a leg's commodity did) or
    silently valued e.g. a COPPER hedge with the ALUMINUM price. This
    diverged from ``compute_deal_pnl`` (already per-commodity).
    """

    def test_breakdown_uses_per_leg_commodity_prices(self, client, session):
        # Distinct prices for ALUMINUM (deal commodity + SO leg) and
        # COPPER (cross-commodity hedge leg).
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
        r = client.post(ENDPOINT, json={"name": "BreakMix", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]

        # Variable-price ALUMINUM SO (uses 2700 → revenue 270 000)
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

        # Active SHORT COPPER hedge — different commodity from the deal.
        # qty=100 fixed_price=2450; mtm = 100*(2450-9100) = -665 000.
        cu_hedge_id = _create_active_hedge(
            session,
            cp_id,
            classification=HedgeClassification.short,
            commodity="COPPER",
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "hedge", "linked_id": str(cu_hedge_id)},
        )

        # Breakdown via the API endpoint.
        r2 = client.post(
            f"{ENDPOINT}/pnl-breakdown",
            json={"deal_ids": [deal_id], "snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert len(body["deals"]) == 1
        d = body["deals"][0]

        # ALUMINUM SO valued at 2700 (NOT at 9100 / NOT a hard-fail).
        assert Decimal(d["physical_revenue"]) == Decimal("270000")
        assert Decimal(d["physical_cost"]) == Decimal("0")
        # Each physical_item carries its own (per-leg) commodity.
        so_item = next(
            it for it in d["physical_items"] if it["order_type"] == "SO"
        )
        assert so_item["commodity"] == "ALUMINUM"
        assert Decimal(so_item["price"]) == Decimal("2500.000000")
        assert Decimal(so_item["value"]) == Decimal("270000.000000")

        # COPPER hedge valued at 9100 → MTM = 100*(2450-9100) = -665 000.
        cu_item = next(it for it in d["financial_items"])
        assert Decimal(cu_item["market_price"]) == Decimal("9100.000000")
        assert Decimal(cu_item["pnl"]) == Decimal("-665000")
        assert Decimal(d["hedge_pnl_mtm"]) == Decimal("-665000")

        # Total reconciles: revenue - cost + realized + mtm.
        # 270 000 - 0 + 0 + (-665 000) = -395 000.
        assert Decimal(d["total_pnl"]) == Decimal("-395000")

        # Compute_deal_pnl on identical inputs must agree on the totals.
        from app.core.database import SessionLocal
        from app.services.deal_engine import DealEngineService

        with SessionLocal() as s:
            snap = DealEngineService.compute_deal_pnl(
                s, uuid.UUID(deal_id), date(2026, 2, 1)
            )
            assert snap.physical_revenue == Decimal("270000.000000")
            assert snap.hedge_pnl_mtm == Decimal("-665000.000000")
            assert snap.total_pnl == Decimal("-395000.000000")

    def test_breakdown_hardfails_when_cross_commodity_price_missing(
        self, client, session
    ):
        # ALUMINUM price published; COPPER price NOT published → the
        # COPPER hedge cannot be MTM-valued. The whole breakdown must
        # 422 — no partial-success path (consistent with §3.3).
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=2700.0,
        )

        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json={"name": "BreakMiss", "commodity": "ALUMINUM"})
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

        cu_hedge_id = _create_active_hedge(
            session,
            cp_id,
            classification=HedgeClassification.short,
            commodity="COPPER",
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "hedge", "linked_id": str(cu_hedge_id)},
        )

        r2 = client.post(
            f"{ENDPOINT}/pnl-breakdown",
            json={"deal_ids": [deal_id], "snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 422
        # No partial result returned — error envelope only.
        body = r2.json()
        assert "deals" not in body
