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
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.core.database import SessionLocal
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.counterparty import Counterparty
from app.models.deal import DealLink, DealPNLSnapshot
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

    @pytest.mark.parametrize(
        "bad_value",
        [
            "not-a-number",  # Codex's exact example
            "NaN",
            "Infinity",
            "-Infinity",
        ],
    )
    def test_inner_value_non_decimal_string_rejected(self, bad_value):
        """SQLite-portable defender: ``@validates`` must reject any
        ``value`` that ``Decimal(...)`` cannot parse to a finite number,
        even when the JSON shape is otherwise well-formed.
        Mirrors the PG-side function-backed CHECK so tests catch
        malformed audit evidence in both dialects.
        """
        with pytest.raises(ValueError):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={
                    "ALUMINUM": {
                        "value": bad_value,
                        "source": "lme",
                        "settlement_date": "2026-05-05",
                    }
                },
            )

    def test_inner_value_non_string_rejected(self):
        """Numeric ``value`` (not even a string) must also be rejected."""
        with pytest.raises(ValueError, match="must be a string"):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={
                    "ALUMINUM": {
                        "value": 2700,
                        "source": "lme",
                        "settlement_date": "2026-05-05",
                    }
                },
            )

    @pytest.mark.parametrize(
        "bad_source",
        [
            123,             # int — Codex's exact example
            1.5,             # float
            True,            # bool
            ["lme"],         # list
            {"name": "lme"}, # dict
            None,            # key present, value is None
        ],
    )
    def test_inner_source_non_string_rejected(self, bad_source):
        """Codex P2 (2026-05-06): SQLite-portable defender must mirror
        the Postgres CHECK clause ``jsonb_typeof(entry->'source') =
        'string'``. The required-keys check passes when ``source`` is
        present but any non-string type, so without this guard a direct
        ORM write could persist malformed audit evidence on SQLite that
        only fails at Postgres commit time. Mirrors the existing
        ``test_inner_value_non_string_rejected`` parity guard.
        """
        with pytest.raises(ValueError, match="source must be a string"):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={
                    "ALUMINUM": {
                        "value": "2700.0",
                        "source": bad_source,
                        "settlement_date": "2026-05-05",
                    }
                },
            )

    @pytest.mark.parametrize(
        "non_canonical_value",
        [
            "5500.0e-2",   # scientific notation — Decimal accepts, CHECK rejects
            "+5500",       # leading + — Decimal accepts, CHECK rejects
            "  5500  ",    # whitespace-padded — Decimal accepts, CHECK rejects
            "5500.",       # trailing dot — Decimal accepts, CHECK rejects
            ".5",          # leading dot — Decimal accepts, CHECK rejects
        ],
    )
    def test_inner_value_non_canonical_decimal_rejected(
        self, non_canonical_value
    ):
        """Codex P2 (2026-05-06): SQLite-portable defender must mirror
        the Postgres CHECK regex byte-for-byte. ``Decimal(...)`` is too
        permissive and would accept these forms, but the CHECK
        ``^-?\\d+(\\.\\d+)?$`` rejects them as non-fixed-point. Without
        the regex check in @validates, these would pass SQLite tests
        and only fail at Postgres commit time.
        Mirrors ``test_direct_sql_value_must_match_decimal_regex`` in
        the PG-only suite below for cross-dialect parity.
        """
        with pytest.raises(ValueError, match="canonical fixed-point"):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={
                    "ALUMINUM": {
                        "value": non_canonical_value,
                        "source": "lme",
                        "settlement_date": "2026-05-05",
                    }
                },
            )

    @pytest.mark.parametrize(
        "canonical_value",
        [
            "5500",            # plain integer
            "-5500.123456",    # negative with fraction
            "0",               # zero
        ],
    )
    def test_inner_value_canonical_decimal_accepted(self, canonical_value):
        """Codex P2 (2026-05-06): canonical fixed-point strings the
        producer (compute_deal_pnl -> quantize_price -> str(Decimal))
        actually emits must continue to be accepted. Mirrors the
        well-formed cases in ``test_direct_sql_value_must_match_decimal_regex``.
        """
        snap = DealPNLSnapshot(
            deal_id=uuid.uuid4(),
            snapshot_date=date(2026, 2, 1),
            inputs_hash="x" * 64,
            price_references={
                "ALUMINUM": {
                    "value": canonical_value,
                    "source": "lme",
                    "settlement_date": "2026-05-05",
                }
            },
        )
        assert snap.price_references is not None
        assert snap.price_references["ALUMINUM"]["value"] == canonical_value

    @pytest.mark.parametrize(
        "bad_date",
        [
            "not-a-date",       # Codex's exact example — arbitrary text
            "2026-13-01",       # impossible month — caught by calendar check
            "2026-02-30",       # impossible day — caught by calendar check
            "2026-5-5",         # single-digit — strict-ISO rejects
            "2026/05/05",       # wrong separator
            "05-05-2026",       # wrong field order
            "",                 # empty string
        ],
    )
    def test_inner_settlement_date_invalid_rejected(self, bad_date):
        """SQLite-portable defender: ``@validates`` must reject any
        ``settlement_date`` that is not a strict ISO calendar date.
        Mirrors the PG-side regex + ``::date`` cast pair so tests catch
        malformed audit evidence in both dialects.
        """
        with pytest.raises(ValueError):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={
                    "ALUMINUM": {
                        "value": "2700.0",
                        "source": "lme",
                        "settlement_date": bad_date,
                    }
                },
            )

    def test_inner_settlement_date_non_string_rejected(self):
        """``settlement_date`` must be a string (ISO date)."""
        with pytest.raises(ValueError, match="settlement_date"):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={
                    "ALUMINUM": {
                        "value": "2700.0",
                        "source": "lme",
                        "settlement_date": 20260505,
                    }
                },
            )

    # Codex P2 follow-up (2026-05-06): regex-parity guards. Python's
    # ``date.fromisoformat`` accepts compact / ISO-week / ordinal forms
    # that the PG-side ``^\d{4}-\d{2}-\d{2}$`` CHECK rejects. The
    # portable @validates must use the same anchored regex BEFORE
    # falling through to ``fromisoformat`` so SQLite tests catch what
    # would otherwise only fail at Postgres commit time.
    def test_inner_settlement_date_compact_format_rejected(self):
        """``"20260505"`` (compact ISO 8601) accepted by
        ``fromisoformat`` but rejected by the PG CHECK regex; the
        portable validator must reject it.
        """
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={
                    "ALUMINUM": {
                        "value": "2700.0",
                        "source": "lme",
                        "settlement_date": "20260505",
                    }
                },
            )

    def test_inner_settlement_date_iso_week_rejected(self):
        """``"2026-W19-2"`` (ISO week date) accepted by
        ``fromisoformat`` but rejected by the PG CHECK regex; the
        portable validator must reject it.
        """
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={
                    "ALUMINUM": {
                        "value": "2700.0",
                        "source": "lme",
                        "settlement_date": "2026-W19-2",
                    }
                },
            )

    def test_inner_settlement_date_ordinal_rejected(self):
        """``"2026-125"`` (ordinal date) accepted by
        ``fromisoformat`` but rejected by the PG CHECK regex; the
        portable validator must reject it.
        """
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            DealPNLSnapshot(
                deal_id=uuid.uuid4(),
                snapshot_date=date(2026, 2, 1),
                inputs_hash="x" * 64,
                price_references={
                    "ALUMINUM": {
                        "value": "2700.0",
                        "source": "lme",
                        "settlement_date": "2026-125",
                    }
                },
            )


# ──────────────────────────────────────────────────────────────────────
# Postgres-only — direct-SQL writes are rejected by the per-entry CHECK
#
# Codex P2 (2026-05-06) flagged that the original CHECK only verified
# "non-empty object" and would accept entries like
# ``{"ALUMINUM": {"value": "2700"}}`` (missing source + settlement_date)
# or numeric ``value`` if a production repair/import wrote
# ``price_references`` directly via SQL (bypassing the ORM @validates).
#
# The migration now creates an IMMUTABLE STRICT plpgsql function
# ``_assert_price_references_shape(jsonb)`` that iterates jsonb_each and
# enforces per-entry shape; the CHECK calls that function. These tests
# are PG-only because the function and the CHECK both live behind the
# Postgres dialect guard in ``030_pnl_provenance.py``. SQLite test envs
# already exercise the same shapes via the @validates suite above.
# ──────────────────────────────────────────────────────────────────────

_TEST_PG_URL = os.environ.get("TEST_DATABASE_URL_PG")


@pytest.mark.skipif(
    not _TEST_PG_URL,
    reason="TEST_DATABASE_URL_PG not set — PG-only CHECK function tests skipped",
)
class TestPriceReferencesCheckOnPostgres:
    """Direct-SQL inserts must be rejected by the function-backed CHECK.

    Builds a minimal table mirroring the production columns referenced by
    the CHECK, runs the migration's ``upgrade()`` which creates the
    function and constraint, and asserts each malformed shape raises
    ``IntegrityError``. The well-formed entry must succeed.
    """

    @staticmethod
    def _setup_engine_with_check():
        """Create engine + bare table + run migration upgrade()."""
        from sqlalchemy import create_engine
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        engine = create_engine(_TEST_PG_URL)  # type: ignore[arg-type]
        # Build a minimal table to run the migration's add_column +
        # create_check_constraint + function-creation against.
        with engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS deal_pnl_snapshots"))
            conn.execute(
                sa.text(
                    """
                    CREATE TABLE deal_pnl_snapshots (
                        id uuid PRIMARY KEY,
                        deal_id uuid NOT NULL,
                        snapshot_date date NOT NULL,
                        inputs_hash varchar(64) NOT NULL,
                        created_at timestamp NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            # Run only the bits of upgrade() we care about (column + check).
            import importlib.util
            from pathlib import Path

            mig_path = (
                Path(__file__).resolve().parents[1]
                / "alembic"
                / "versions"
                / "030_pnl_provenance.py"
            )
            spec = importlib.util.spec_from_file_location(
                "_pr8_pnl_provenance_pgcheck", mig_path
            )
            migration = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(migration)
            ctx = MigrationContext.configure(conn)
            migration.op = Operations(ctx)
            migration.upgrade()
        return engine

    @staticmethod
    def _teardown(engine):
        from sqlalchemy import text as _t
        with engine.begin() as conn:
            conn.execute(_t("DROP TABLE IF EXISTS deal_pnl_snapshots"))
            conn.execute(_t("DROP FUNCTION IF EXISTS _assert_price_references_shape(jsonb)"))
        engine.dispose()

    @staticmethod
    def _try_insert(engine, payload):
        """Try a raw insert with the given price_references JSON."""
        import json as _json
        from sqlalchemy import text as _t

        with engine.begin() as conn:
            conn.execute(
                _t(
                    "INSERT INTO deal_pnl_snapshots "
                    "(id, deal_id, snapshot_date, inputs_hash, price_references) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), CURRENT_DATE, "
                    ":h, CAST(:p AS jsonb))"
                ),
                {"h": "x" * 64, "p": _json.dumps(payload)},
            )

    def test_direct_sql_malformed_shapes_rejected_well_formed_accepted(self):
        from sqlalchemy.exc import IntegrityError

        engine = self._setup_engine_with_check()
        try:
            # 1. Missing source + settlement_date (Codex's exact example)
            with pytest.raises(IntegrityError):
                self._try_insert(engine, {"ALUMINUM": {"value": "2700"}})

            # 2. settlement_date not ISO date format
            with pytest.raises(IntegrityError):
                self._try_insert(
                    engine,
                    {
                        "ALUMINUM": {
                            "value": "2700",
                            "source": "lme",
                            "settlement_date": "not-a-date",
                        }
                    },
                )

            # 3. value is numeric, not string
            with pytest.raises(IntegrityError):
                self._try_insert(
                    engine,
                    {
                        "ALUMINUM": {
                            "value": 2700,
                            "source": "lme",
                            "settlement_date": "2026-05-05",
                        }
                    },
                )

            # 4. Empty object — also forbidden
            with pytest.raises(IntegrityError):
                self._try_insert(engine, {})

            # 5. Well-formed entry — must succeed
            self._try_insert(
                engine,
                {
                    "ALUMINUM": {
                        "value": "2700",
                        "source": "lme",
                        "settlement_date": "2026-05-05",
                    }
                },
            )

            # 6. NULL price_references — also valid (nullable column)
            from sqlalchemy import text as _t

            with engine.begin() as conn:
                conn.execute(
                    _t(
                        "INSERT INTO deal_pnl_snapshots "
                        "(id, deal_id, snapshot_date, inputs_hash, price_references) "
                        "VALUES (gen_random_uuid(), gen_random_uuid(), CURRENT_DATE, "
                        ":h, NULL)"
                    ),
                    {"h": "y" * 64},
                )
        finally:
            self._teardown(engine)

    def test_direct_sql_value_must_match_decimal_regex(self):
        """Codex P2 (2026-05-06): the per-entry CHECK now also enforces
        the documented Decimal-as-string contract on ``value``. The
        producer (compute_deal_pnl -> quantize_price -> str(Decimal))
        only ever emits canonical fixed-point strings; direct-SQL writes
        that smuggle in scientific notation, NaN, +sign, leading or
        trailing dots, whitespace, or arbitrary text must be rejected
        by the function-backed CHECK.
        """
        from sqlalchemy.exc import IntegrityError

        engine = self._setup_engine_with_check()
        try:
            base = {
                "ALUMINUM": {
                    "value": "PLACEHOLDER",
                    "source": "lme",
                    "settlement_date": "2026-05-05",
                }
            }

            def _with(value):
                payload = {"ALUMINUM": dict(base["ALUMINUM"])}
                payload["ALUMINUM"]["value"] = value
                return payload

            # Rejected: arbitrary text (Codex's exact example)
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("not-a-number"))

            # Rejected: scientific notation
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("5500.0e-2"))

            # Rejected: NaN
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("NaN"))

            # Rejected: leading +
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("+5500"))

            # Rejected: trailing dot
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("5500."))

            # Rejected: leading dot
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with(".5"))

            # Rejected: empty string
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with(""))

            # Rejected: surrounding whitespace
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("  5500  "))

            # Accepted: well-formed negative
            self._try_insert(engine, _with("-5500.123456"))

            # Accepted: well-formed zero
            self._try_insert(engine, _with("0"))

            # Accepted: well-formed plain integer
            self._try_insert(engine, _with("5500"))

            # Accepted: well-formed fractional
            self._try_insert(engine, _with("0.000001"))
        finally:
            self._teardown(engine)

    def test_direct_sql_settlement_date_must_be_iso_calendar_date(self):
        """Codex P2 follow-up (2026-05-06): the per-entry CHECK now also
        enforces ISO calendar-date validity on ``settlement_date``. The
        producer always emits ``date.isoformat()`` strings; direct-SQL
        writes that smuggle in arbitrary text, wrong format, or
        impossible calendar dates (month=13, day=30 in February) must
        be rejected by the function-backed CHECK (regex + ``::date``
        cast pair).
        """
        from sqlalchemy.exc import IntegrityError

        engine = self._setup_engine_with_check()
        try:
            base = {
                "ALUMINUM": {
                    "value": "2700",
                    "source": "lme",
                    "settlement_date": "PLACEHOLDER",
                }
            }

            def _with(settlement):
                payload = {"ALUMINUM": dict(base["ALUMINUM"])}
                payload["ALUMINUM"]["settlement_date"] = settlement
                return payload

            # Rejected by regex layer — arbitrary text (already covered
            # in the malformed-shapes test, repeated here for clarity).
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("not-a-date"))

            # Rejected by ::date cast — impossible month (regex passes,
            # cast fails). This is the case the regex alone CANNOT
            # catch, justifying the belt-and-suspenders pair.
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("2026-13-01"))

            # Rejected by ::date cast — impossible day in February.
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("2026-02-30"))

            # Rejected by regex layer — single-digit month/day breaks
            # strict ISO format (the producer always zero-pads).
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("2026-5-5"))

            # Rejected by regex layer — wrong separator.
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("2026/05/05"))

            # Rejected by regex layer — wrong field order.
            with pytest.raises(IntegrityError):
                self._try_insert(engine, _with("05-05-2026"))

            # Accepted: well-formed ISO date.
            self._try_insert(engine, _with("2026-05-05"))
        finally:
            self._teardown(engine)


# ──────────────────────────────────────────────────────────────────────
# Codex P2 (2026-05-06) — idempotency under price-source repair.
#
# When a post-PR-8 snapshot already exists but the underlying
# CashSettlementPrice row is later removed or unavailable during a
# repair, ``compute_deal_pnl`` MUST still return the existing snapshot
# rather than raise ``PriceReferenceUnprovable``. The fix probes
# existing snapshots for this (deal, date) BEFORE the market lookup
# loop and reuses any whose persisted ``price_references`` still
# reproduce the current ``inputs_hash``.
#
# These tests exercise the service directly (DealEngineService) rather
# than the HTTP route so we can both:
#   * mock the price-lookup helper to simulate the source disappearing,
#   * inspect the persisted DealPNLSnapshot rows to assert no new
#     duplicate row was created.
# ──────────────────────────────────────────────────────────────────────


class TestSnapshotReuseUnderPriceSourceRepair:
    def _create_variable_price_deal_with_snapshot(
        self, client, session, *, snapshot_date_str: str = "2026-02-01"
    ):
        """Helper: variable-price ALU SO deal with one persisted snapshot."""
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=2700.0,
        )
        r = client.post(
            ENDPOINT, json={"name": "Repair", "commodity": "ALUMINUM"}
        )
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
        r1 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": snapshot_date_str},
        )
        assert r1.status_code == 201, r1.text
        return deal_id, r1.json()

    def test_compute_deal_pnl_reuses_snapshot_when_market_price_unavailable(
        self, client, session, monkeypatch
    ):
        """Codex P2 — repair: ``CashSettlementPrice`` row deleted after
        snapshot creation. A repeated call MUST return the persisted
        snapshot, not raise ``PriceReferenceUnprovable`` (→ 422).
        """
        from app.services import deal_engine as deal_engine_mod
        from app.services.price_lookup_service import PriceReferenceUnprovable

        deal_id, snap1 = self._create_variable_price_deal_with_snapshot(
            client, session
        )
        snapshot_date_obj = date(2026, 2, 1)

        # Simulate the price-source row vanishing post-snapshot. Any
        # call into the lookup helper now hard-fails. The probe must
        # short-circuit BEFORE this is reached.
        def _raise_unprovable(*args, **kwargs):
            raise PriceReferenceUnprovable(
                "simulated repair: source row deleted",
                commodity="ALUMINUM",
            )

        monkeypatch.setattr(
            deal_engine_mod,
            "_get_market_quote",
            _raise_unprovable,
        )

        with SessionLocal() as s:
            snap2 = DealEngineService.compute_deal_pnl(
                s, uuid.UUID(deal_id), snapshot_date_obj
            )
            s.commit()
            # Capture attributes WHILE the session is still open —
            # accessing them after the ``with`` block exits would
            # raise ``DetachedInstanceError`` because SQLAlchemy
            # cannot refresh from a closed session.
            snap2_id = str(snap2.id)
            snap2_hash = snap2.inputs_hash

        assert snap2_id == snap1["id"]
        assert snap2_hash == snap1["inputs_hash"]
        # Exactly one row — no duplicate persisted by the second call.
        with SessionLocal() as s:
            assert (
                s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .count()
                == 1
            )

    def test_compute_deal_pnl_reuses_snapshot_for_fixed_price_only_deal_unchanged(
        self, client, session
    ):
        """Regression: fixed-price-only deal already had
        ``price_references = NULL`` and reused via the existing
        post-build hash-match. The new probe must still locate it
        when the market-lookup stage would not run anyway.
        """
        r = client.post(
            ENDPOINT, json={"name": "Fixed", "commodity": "ALUMINUM"}
        )
        deal_id = r.json()["id"]
        so_id = _create_order(
            session,
            OrderType.sales,
            qty=Decimal("100"),
            price=Decimal("2500"),
            price_type=PriceType.fixed,
        )
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
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]
        # Persisted price_references must remain NULL (no market lookup).
        assert r1.json()["price_references"] is None
        with SessionLocal() as s:
            assert (
                s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .count()
                == 1
            )

    def test_compute_deal_pnl_creates_new_row_when_price_changes(
        self, client, session
    ):
        """Forensic correctness: when the price IS available but
        differs from what produced the existing snapshot, the probe
        must miss (different recomputed hash) and a new row persists
        alongside the old. Two rows = old + new.
        """
        deal_id, snap1 = self._create_variable_price_deal_with_snapshot(
            client, session
        )

        # Update the underlying price (LME republishes a corrected value).
        with SessionLocal() as s:
            row = (
                s.query(CashSettlementPrice)
                .filter(
                    CashSettlementPrice.symbol
                    == "LME_ALU_CASH_SETTLEMENT_DAILY"
                )
                .first()
            )
            row.price_usd = 2750.0
            s.commit()

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 201
        snap2 = r2.json()
        assert snap2["id"] != snap1["id"]
        assert snap2["inputs_hash"] != snap1["inputs_hash"]
        with SessionLocal() as s:
            rows = (
                s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .order_by(DealPNLSnapshot.created_at.asc())
                .all()
            )
            assert len(rows) == 2
            # First row's hash unchanged; second differs.
            assert str(rows[0].id) == snap1["id"]
            assert rows[0].inputs_hash == snap1["inputs_hash"]
            assert rows[1].inputs_hash == snap2["inputs_hash"]

    def test_compute_deal_pnl_creates_new_row_when_link_set_changes(
        self, client, session
    ):
        """Different link set → different ``link_ids`` → different
        recomputed hash for the existing snapshot's ``price_references``,
        so the probe correctly misses and a fresh snapshot is created.
        """
        deal_id, snap1 = self._create_variable_price_deal_with_snapshot(
            client, session
        )

        # Add a second link (a fixed-price PO — no extra commodity needed).
        po_id = _create_order(
            session,
            OrderType.purchase,
            qty=Decimal("80"),
            price=Decimal("2400"),
            price_type=PriceType.fixed,
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
        snap2 = r2.json()
        assert snap2["id"] != snap1["id"]
        assert snap2["inputs_hash"] != snap1["inputs_hash"]
        with SessionLocal() as s:
            assert (
                s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .count()
                == 2
            )

    def test_compute_deal_pnl_legacy_snapshot_not_reused(
        self, client, session
    ):
        """Legacy (pre-PR-8) rows have an ``inputs_hash`` computed in
        the OLD format (no ``price_references`` key) and stored
        ``price_references = NULL``. Recomputing the hash with the new
        format produces a different value → the probe must NOT reuse
        the legacy row → a fresh post-PR-8 row is inserted alongside.
        Mirrors §3.4.3: legacy rows are sealed, never bound to current
        link sets retroactively.
        """
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=2700.0,
        )
        r = client.post(
            ENDPOINT, json={"name": "Legacy", "commodity": "ALUMINUM"}
        )
        deal_id_str = r.json()["id"]
        deal_id = uuid.UUID(deal_id_str)
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

        # Insert a legacy snapshot directly with an OLD-format hash and
        # NULL price_references (the pre-PR-8 producer signature).
        snapshot_date_obj = date(2026, 2, 1)
        with SessionLocal() as s:
            link_ids = sorted(
                str(lk.id)
                for lk in s.query(DealLink)
                .filter(DealLink.deal_id == deal_id)
                .all()
            )
            legacy_hash = hashlib.sha256(
                json.dumps(
                    {
                        "deal_id": str(deal_id),
                        "snapshot_date": str(snapshot_date_obj),
                        "links": link_ids,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            legacy_row = DealPNLSnapshot(
                deal_id=deal_id,
                snapshot_date=snapshot_date_obj,
                physical_revenue=Decimal("100000"),
                physical_cost=Decimal("0"),
                hedge_pnl_realized=Decimal("0"),
                hedge_pnl_mtm=Decimal("0"),
                total_pnl=Decimal("100000"),
                inputs_hash=legacy_hash,
                price_references=None,
            )
            s.add(legacy_row)
            s.commit()
            legacy_id = legacy_row.id

        # Now request a snapshot via the post-PR-8 path.
        r2 = client.post(
            f"{ENDPOINT}/{deal_id_str}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 201
        new = r2.json()
        # The new row is NOT the legacy row — legacy is sealed.
        assert new["id"] != str(legacy_id)
        assert new["inputs_hash"] != legacy_hash
        # The new (post-PR-8) row must carry populated price_references.
        assert new["price_references"] is not None
        assert "ALUMINUM" in new["price_references"]
        # Both rows persist — legacy is preserved, new row inserted.
        with SessionLocal() as s:
            rows = (
                s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == deal_id)
                .all()
            )
            assert len(rows) == 2
            ids = {str(r.id) for r in rows}
            assert str(legacy_id) in ids
            assert new["id"] in ids

    def test_outage_fallback_returns_newest_matching_snapshot(
        self, client, session, monkeypatch
    ):
        """Codex P2 (PR #22 follow-up) — when the total-unavailability
        fallback finds multiple post-PR-8 snapshots whose stored
        ``price_references`` each still hash-match the current link
        set (e.g. price correction created ``snap_new`` after
        ``snap_old``, then the price feed was wiped), the fallback
        MUST return the NEWEST matching snapshot (``snap_new``), not
        an arbitrary unordered DB row that could regress P&L to the
        pre-correction value.

        Scenario:
          1. Insert ALU price P1=2700 → first snapshot ``snap_old`` (P1).
          2. Correct the price to P2=2750 → second snapshot ``snap_new``
             with a different ``inputs_hash`` (different
             ``price_references["value"]``).
          3. Delete the ``CashSettlementPrice`` row entirely (price-feed
             wipe) and force the lookup helper to raise
             ``PriceReferenceUnprovable`` so the outage fallback fires.
          4. Re-request the snapshot. Both ``snap_old`` and ``snap_new``
             still hash-match the current link set against their own
             stored ``price_references``, so without a strictly
             monotonic ORDER BY the DB could return either row first.
             The fix orders by the monotonic ``sequence DESC`` column
             so the newest reusable snapshot wins regardless of
             ``created_at`` precision.

        Asserts:
          * Returned snapshot id == ``snap_new.id`` (NOT ``snap_old.id``).
          * ``sequence(snap_new) > sequence(snap_old)`` so the ordering
            semantics are observable in the persisted data.
          * No new row is created (count remains 2).
        """
        from app.services import deal_engine as deal_engine_mod
        from app.services.price_lookup_service import PriceReferenceUnprovable

        deal_id, snap_old = self._create_variable_price_deal_with_snapshot(
            client, session
        )
        snapshot_date_obj = date(2026, 2, 1)

        # Step 2: price correction — LME republishes at 2750. The
        # second POST sees a different ``price_references["value"]``,
        # so a fresh post-PR-8 row is inserted alongside ``snap_old``.
        with SessionLocal() as s:
            row = (
                s.query(CashSettlementPrice)
                .filter(
                    CashSettlementPrice.symbol
                    == "LME_ALU_CASH_SETTLEMENT_DAILY"
                )
                .first()
            )
            row.price_usd = 2750.0
            s.commit()

        r_new = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r_new.status_code == 201
        snap_new = r_new.json()
        assert snap_new["id"] != snap_old["id"]
        assert snap_new["inputs_hash"] != snap_old["inputs_hash"]

        # Codex P2 (PR #22 follow-up): the production ORDER BY is now
        # ``sequence DESC`` — a strictly monotonic insertion counter. We
        # no longer need to fudge ``created_at`` to make the test
        # deterministic on SQLite's second-precision timestamps; the
        # ``sequence`` column is monotonic by construction (Postgres
        # SEQUENCE on prod, process-local Python counter on SQLite test
        # path). The sanity check below verifies the column was
        # populated and ``snap_new`` has a strictly greater value than
        # ``snap_old``.
        with SessionLocal() as s:
            rows = (
                s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .order_by(DealPNLSnapshot.sequence.asc())
                .all()
            )
            assert len(rows) == 2
            assert str(rows[0].id) == snap_old["id"]
            assert str(rows[1].id) == snap_new["id"]
            assert rows[1].sequence > rows[0].sequence

        # Step 3: wipe the price-feed row and force any lookup to
        # raise so the total-unavailability outage fallback fires.
        with SessionLocal() as s:
            s.query(CashSettlementPrice).filter(
                CashSettlementPrice.symbol
                == "LME_ALU_CASH_SETTLEMENT_DAILY"
            ).delete()
            s.commit()

        def _raise_unprovable(*args, **kwargs):
            raise PriceReferenceUnprovable(
                "simulated outage: source row deleted",
                commodity="ALUMINUM",
            )

        monkeypatch.setattr(
            deal_engine_mod,
            "_get_market_quote",
            _raise_unprovable,
        )

        # Step 4: outage fallback fires. Both snapshots still
        # hash-match against their own stored ``price_references``;
        # the ORDER BY ``created_at DESC`` clause guarantees we
        # return the newest one (``snap_new``).
        with SessionLocal() as s:
            reused = DealEngineService.compute_deal_pnl(
                s, uuid.UUID(deal_id), snapshot_date_obj
            )
            s.commit()
            reused_id = str(reused.id)
            reused_hash = reused.inputs_hash

        assert reused_id == snap_new["id"], (
            "outage fallback returned the wrong snapshot — expected "
            "the newest reusable row (snap_new) but got snap_old; the "
            "ORDER BY ``sequence DESC`` clause is missing or "
            "ineffective."
        )
        assert reused_id != snap_old["id"]
        assert reused_hash == snap_new["inputs_hash"]

        # No new row was persisted by the fallback.
        with SessionLocal() as s:
            assert (
                s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .count()
                == 2
            )

    def test_sequence_is_monotonic_across_inserts(
        self, client, session
    ):
        """Codex P2 (PR #22 follow-up) — verify the new ``sequence``
        column is strictly monotonic across consecutive inserts on the
        SQLite test path. This pins the contract that powers the
        outage-fallback ORDER BY: every newly persisted snapshot has a
        ``sequence`` value strictly greater than every prior snapshot
        in the table, regardless of ``created_at`` precision or UUID
        ordering.

        Three snapshots are created via the same producer that the
        outage fallback consults (price corrections that change the
        ``inputs_hash``), then read back ordered by ``sequence`` ASC.
        The column values must form a strictly increasing sequence.
        """
        deal_id, snap_a = self._create_variable_price_deal_with_snapshot(
            client, session
        )

        # Bump the price twice to produce two more distinct snapshots
        # for the same (deal_id, snapshot_date) — each correction
        # changes ``price_references["value"]`` and therefore the
        # ``inputs_hash``, so a new row is persisted.
        for new_price in (2750.0, 2800.0):
            with SessionLocal() as s:
                row = (
                    s.query(CashSettlementPrice)
                    .filter(
                        CashSettlementPrice.symbol
                        == "LME_ALU_CASH_SETTLEMENT_DAILY"
                    )
                    .first()
                )
                row.price_usd = new_price
                s.commit()
            r = client.post(
                f"{ENDPOINT}/{deal_id}/pnl-snapshot",
                params={"snapshot_date": "2026-02-01"},
            )
            assert r.status_code == 201

        with SessionLocal() as s:
            rows = (
                s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .order_by(DealPNLSnapshot.sequence.asc())
                .all()
            )
            assert len(rows) == 3
            sequences = [r.sequence for r in rows]
            # Strictly increasing — sequence[i+1] > sequence[i] for all i.
            assert all(
                sequences[i + 1] > sequences[i]
                for i in range(len(sequences) - 1)
            ), f"sequence values not strictly monotonic: {sequences}"
            # And every row got a non-NULL value.
            assert all(s_val is not None for s_val in sequences)

    def test_outage_fallback_uses_sequence_not_created_at(
        self, client, session, monkeypatch
    ):
        """Codex P2 (PR #22 follow-up) — prove the outage-fallback
        ORDER BY operates on the monotonic ``sequence`` column rather
        than ``created_at``. We deliberately make ``snap_new`` carry an
        EARLIER ``created_at`` than ``snap_old`` (simulating the
        SQLite second-precision tie / clock skew Codex reproduced) and
        assert that the fallback STILL returns ``snap_new`` because
        its ``sequence`` is higher.

        This test would FAIL on the previous ``ORDER BY created_at
        DESC, id DESC`` implementation (which would prefer ``snap_old``
        because its ``created_at`` is later) and PASSES on the new
        ``ORDER BY sequence DESC`` implementation.
        """
        from app.services import deal_engine as deal_engine_mod
        from app.services.price_lookup_service import PriceReferenceUnprovable

        deal_id, snap_old = self._create_variable_price_deal_with_snapshot(
            client, session
        )
        snapshot_date_obj = date(2026, 2, 1)

        # Create snap_new via a price correction (different inputs_hash
        # → new row).
        with SessionLocal() as s:
            row = (
                s.query(CashSettlementPrice)
                .filter(
                    CashSettlementPrice.symbol
                    == "LME_ALU_CASH_SETTLEMENT_DAILY"
                )
                .first()
            )
            row.price_usd = 2750.0
            s.commit()

        r_new = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r_new.status_code == 201
        snap_new = r_new.json()
        assert snap_new["id"] != snap_old["id"]

        # Adversarial case: rewind ``snap_new.created_at`` to BEFORE
        # ``snap_old.created_at``. The previous ORDER BY would now
        # prefer ``snap_old``; the new ORDER BY must still prefer
        # ``snap_new`` because its ``sequence`` is higher.
        with SessionLocal() as s:
            snap_old_obj = s.get(DealPNLSnapshot, uuid.UUID(snap_old["id"]))
            snap_new_obj = s.get(DealPNLSnapshot, uuid.UUID(snap_new["id"]))
            snap_new_obj.created_at = snap_old_obj.created_at - timedelta(
                seconds=10
            )
            s.commit()
            # Sanity: snap_new is older by created_at but newer by sequence.
            assert snap_new_obj.created_at < snap_old_obj.created_at
            assert snap_new_obj.sequence > snap_old_obj.sequence

        # Wipe the price feed and force the lookup to raise so the
        # outage fallback fires.
        with SessionLocal() as s:
            s.query(CashSettlementPrice).filter(
                CashSettlementPrice.symbol
                == "LME_ALU_CASH_SETTLEMENT_DAILY"
            ).delete()
            s.commit()

        def _raise_unprovable(*args, **kwargs):
            raise PriceReferenceUnprovable(
                "simulated outage: source row deleted",
                commodity="ALUMINUM",
            )

        monkeypatch.setattr(
            deal_engine_mod,
            "_get_market_quote",
            _raise_unprovable,
        )

        with SessionLocal() as s:
            reused = DealEngineService.compute_deal_pnl(
                s, uuid.UUID(deal_id), snapshot_date_obj
            )
            s.commit()
            reused_id = str(reused.id)

        # The fix is at the column level (sequence), not the timestamp
        # level (created_at) — even with snap_new's created_at rewound
        # behind snap_old's, the monotonic sequence still wins.
        assert reused_id == snap_new["id"], (
            "outage fallback ordered by created_at instead of "
            "sequence — snap_new (newer sequence, older created_at) "
            "should have won but snap_old was returned. The ORDER BY "
            "must be on ``sequence DESC``."
        )


# ──────────────────────────────────────────────────────────────────────
# Codex P1 (PR #22 follow-up, 2026-05-06) — ``DealPNLSnapshot.sequence``
# is populated via a split-by-dialect architecture. The previous design
# wired a Python ``default=`` callable that returned ``func.nextval(...)``
# on PostgreSQL; SQLAlchemy only inlines a SQL expression when it is
# configured directly as the column default, so the return value was
# instead bound as a DBAPI parameter, failing PG inserts at runtime.
#
# The current architecture:
#   * PostgreSQL — ``Sequence("deal_pnl_snapshots_sequence_seq")`` is
#     declared on the column; SQLAlchemy auto-fires ``nextval(...)``
#     server-side. Migration 031 ALSO binds
#     ``server_default = nextval(...)`` so raw-SQL inserts converge on
#     the same sequence. Multi-worker safe.
#   * SQLite — ``Sequence`` is a no-op; a ``before_insert`` event
#     listener (``_set_sqlite_sequence``) computes
#     ``COALESCE(MAX(sequence), 0) + 1`` inline. Race-free under
#     SQLite's serialized writes.
# ──────────────────────────────────────────────────────────────────────


from app.core.database import engine as _pnl_engine
from app.models.deal import _set_sqlite_sequence

_IS_POSTGRES = _pnl_engine.dialect.name == "postgresql"


class TestSqliteSequenceEventListener:
    """Unit tests for ``_set_sqlite_sequence`` — the ``before_insert``
    event listener that backs ``DealPNLSnapshot.sequence`` on SQLite.

    The listener MUST:
      * Early-return on PostgreSQL (server-side ``Sequence`` /
        ``server_default`` own that path; the listener must never
        interfere with it).
      * Early-return when ``target.sequence`` is already set (caller-
        supplied values pass through unchanged).
      * On SQLite with ``target.sequence is None``, query
        ``COALESCE(MAX(sequence), 0) + 1`` against the in-flight
        connection and assign the integer to ``target.sequence``.
    """

    def test_listener_early_returns_on_postgresql(self):
        """On PG the listener MUST early-return so SQLAlchemy's
        ``Sequence`` / ``server_default`` populate the column
        server-side. Touching ``target.sequence`` here would shadow
        the DB sequence and re-introduce the multi-worker duplicate
        bug Codex P2 flagged earlier."""

        class _FakeDialect:
            name = "postgresql"

        class _FakeConn:
            dialect = _FakeDialect()

            def execute(self, _stmt):  # pragma: no cover - must not run
                raise AssertionError(
                    "listener executed SQL on PostgreSQL — it must "
                    "early-return so server-side nextval() fires."
                )

        class _FakeTarget:
            sequence = None

        target = _FakeTarget()
        _set_sqlite_sequence(mapper=None, connection=_FakeConn(), target=target)
        assert target.sequence is None, (
            "listener mutated target.sequence on PostgreSQL; the "
            "server-side Sequence / server_default must own that path."
        )

    def test_listener_assigns_max_plus_one_on_sqlite(self):
        """On SQLite with ``target.sequence is None``, the listener
        executes ``COALESCE(MAX(sequence), 0) + 1`` and assigns the
        scalar result to ``target.sequence``. The ``+1`` is computed
        inside the SQL — the listener just casts to ``int``."""

        executed_sql: list[str] = []

        class _FakeResult:
            def scalar(self):
                return 42

        class _FakeDialect:
            name = "sqlite"

        class _FakeConn:
            dialect = _FakeDialect()

            def execute(self, stmt):
                executed_sql.append(str(stmt))
                return _FakeResult()

        class _FakeTarget:
            sequence = None

        target = _FakeTarget()
        _set_sqlite_sequence(mapper=None, connection=_FakeConn(), target=target)
        assert target.sequence == 42
        assert isinstance(target.sequence, int)
        assert len(executed_sql) == 1
        sql_text = executed_sql[0].lower()
        assert "max(sequence)" in sql_text
        assert "deal_pnl_snapshots" in sql_text
        assert "coalesce" in sql_text

    def test_listener_preserves_caller_supplied_sequence_on_sqlite(self):
        """When the caller has already populated ``target.sequence``,
        the listener MUST early-return and leave the value untouched —
        even on SQLite. This protects deliberate writes (e.g. tests
        that pre-set sequence to exercise edge cases)."""

        class _FakeDialect:
            name = "sqlite"

        class _FakeConn:
            dialect = _FakeDialect()

            def execute(self, _stmt):  # pragma: no cover - must not run
                raise AssertionError(
                    "listener queried SQL despite target.sequence "
                    "being pre-set; it must early-return when the "
                    "caller has supplied a value."
                )

        class _FakeTarget:
            sequence = 99

        target = _FakeTarget()
        _set_sqlite_sequence(mapper=None, connection=_FakeConn(), target=target)
        assert target.sequence == 99, (
            "listener overwrote caller-supplied target.sequence; it "
            "must preserve a non-None value and skip the SQL probe."
        )


@pytest.mark.skipif(
    not _IS_POSTGRES,
    reason=(
        "Server-side sequence DEFAULT and multi-session monotonicity "
        "are PostgreSQL-only contracts (SQLite has no SEQUENCE objects)."
    ),
)
class TestPostgresServerSideSequence:
    """PG-only tests pinning the institutional contract that the
    ``sequence`` column is populated by ``nextval('deal_pnl_..._seq')``
    on EVERY insert path — ORM and raw SQL alike — across all workers.
    """

    def test_sequence_column_has_server_default_nextval(self):
        """After migration 031, the ``sequence`` column on
        ``deal_pnl_snapshots`` MUST have a server-side DEFAULT that
        calls ``nextval('deal_pnl_snapshots_sequence_seq')``.

        Without this binding, raw-SQL inserts (admin tools, COPY,
        repair scripts) would get NULL for ``sequence`` on PG, and
        ORM inserts would only consult the sequence via the Python
        default — a path Codex P2 proved broken under multi-worker.
        """
        from sqlalchemy import inspect

        insp = inspect(_pnl_engine)
        cols = {
            c["name"]: c
            for c in insp.get_columns("deal_pnl_snapshots")
        }
        assert "sequence" in cols, "sequence column missing post-031"
        default = cols["sequence"].get("default")
        assert default is not None, (
            "deal_pnl_snapshots.sequence has no server_default — "
            "raw-SQL inserts will NULL the column and break ordering. "
            "Migration 031 must bind nextval() as the column DEFAULT."
        )
        assert "nextval" in str(default).lower(), (
            f"sequence column server_default is {default!r}; expected "
            f"a nextval('deal_pnl_snapshots_sequence_seq') reference."
        )
        assert "deal_pnl_snapshots_sequence_seq" in str(default), (
            f"sequence column default does not reference the expected "
            f"sequence name; got {default!r}."
        )

    def test_sequence_unique_across_two_concurrent_sessions(self):
        """Two distinct sessions (representing two workers) inserting
        a snapshot simultaneously MUST receive DIFFERENT sequence
        values. This proves the server-side sequence (not a Python
        counter) populates the column.

        If the broken Python ``itertools.count`` default were still
        in effect, both workers would start their counters at 1 in
        their own process and assign duplicate sequence values.
        """
        import threading

        from app.models.contracts import (
            HedgeClassification,
            HedgeContract,
            HedgeContractStatus,
            HedgeLegSide,
        )
        from app.models.counterparty import Counterparty
        from app.models.deal import Deal, DealLink, DealLinkedType, DealPNLSnapshot
        from app.models.deal import DealStatus
        from app.models.orders import Order, OrderType, PriceType

        # Seed a deal we can attach snapshots to.
        seed = SessionLocal()
        deal = Deal(
            reference=f"D-SEQRACE-{uuid.uuid4().hex[:6]}",
            name="seq-race-deal",
            commodity="ALUMINUM",
            status=DealStatus.open,
        )
        seed.add(deal)
        seed.commit()
        seed.refresh(deal)
        deal_id = deal.id
        seed.close()

        barrier = threading.Barrier(2)
        results: dict[str, int | BaseException] = {}

        def _writer(tag: str) -> None:
            sess = SessionLocal()
            try:
                snap = DealPNLSnapshot(
                    deal_id=deal_id,
                    snapshot_date=date(2026, 5, 6),
                    physical_revenue=Decimal("0"),
                    physical_cost=Decimal("0"),
                    hedge_pnl_realized=Decimal("0"),
                    hedge_pnl_mtm=Decimal("0"),
                    total_pnl=Decimal("0"),
                    inputs_hash=hashlib.sha256(tag.encode()).hexdigest(),
                )
                sess.add(snap)
                # Synchronize so both flushes contend for the sequence.
                barrier.wait(timeout=10)
                sess.commit()
                sess.refresh(snap)
                results[tag] = snap.sequence
            except BaseException as exc:  # pragma: no cover
                results[tag] = exc
            finally:
                sess.close()

        t_a = threading.Thread(target=_writer, args=("A",))
        t_b = threading.Thread(target=_writer, args=("B",))
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        seq_a = results.get("A")
        seq_b = results.get("B")
        assert isinstance(seq_a, int) and isinstance(seq_b, int), (
            f"both workers must persist successfully; got {results!r}"
        )
        assert seq_a != seq_b, (
            f"two concurrent workers got DUPLICATE sequence values "
            f"({seq_a} == {seq_b}) — the server-side sequence is not "
            f"being consulted. Verify the column has the Sequence(...) "
            f"declaration with NO Python default= (so SQLAlchemy "
            f"pre-executes nextval('seq')) and that migration 031 binds "
            f"server_default=nextval(...) on the column."
        )


# ──────────────────────────────────────────────────────────────────────
# Codex P2 (PR #22 follow-up) — partial market-quote success must
# fail closed. The collect-then-decide algorithm in compute_deal_pnl
# distinguishes three cases:
#   * all commodities priced fresh → standard hash-match path
#   * partial success (≥1 fresh + ≥1 unprovable) → propagate 422
#   * total unavailability (0 fresh) → probe candidates (repair
#     scenario)
# These tests pin the partial-success and total-unavailability
# behavior for multi-commodity deals.
# ──────────────────────────────────────────────────────────────────────


class TestPartialQuoteSuccessFailsClosed:
    """Codex P2 — partial market-quote success must fail closed.

    A multi-commodity deal where ALU is priced fresh but COPPER
    raises ``PriceReferenceUnprovable`` previously fell through to
    the candidate-fallback probe, which could match a candidate
    whose stored ``price_references`` carried the now-stale
    corrected ALU value and silently return stale P&L. The fix is
    the collect-then-decide structure in ``compute_deal_pnl``: any
    partial success propagates the first
    ``PriceReferenceUnprovable`` (→ 422) and persists no new row.
    """

    def _build_multi_commodity_deal_with_snapshot(
        self, client, session, *, snapshot_date_str: str = "2026-02-01"
    ):
        """Helper: ALU variable-price SO + COPPER active short hedge,
        with a baseline snapshot persisted (both prices known).
        """
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
        r = client.post(
            ENDPOINT, json={"name": "Partial", "commodity": "ALUMINUM"}
        )
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
            qty=Decimal("50"),
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "hedge", "linked_id": str(cu_hedge_id)},
        )
        r1 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": snapshot_date_str},
        )
        assert r1.status_code == 201, r1.text
        return deal_id, r1.json()

    def test_compute_deal_pnl_partial_quote_success_with_correction_fails_closed(
        self, client, session, monkeypatch
    ):
        """Codex P2 — partial success + correction → fail closed.

        ALU lookup returns a CORRECTED value (different from the
        baseline snapshot's stored ALU price); COPPER lookup raises
        ``PriceReferenceUnprovable``. The previous (try/except-around-
        the-loop) variant would discard the partial ALU success,
        probe candidates, and match the existing snapshot via its
        old (uncorrected) stored ALU value — silently serving stale
        ALU P&L. The fix propagates the first
        ``PriceReferenceUnprovable`` (→ 422); no new snapshot is
        persisted; the existing baseline row is unchanged.
        """
        from app.services import deal_engine as deal_engine_mod
        from app.services.price_lookup_service import (
            PriceQuote,
            PriceReferenceUnprovable,
        )

        deal_id, snap1 = self._build_multi_commodity_deal_with_snapshot(
            client, session
        )

        def _mixed_quote(_session, commodity, _as_of_date):
            if commodity == "ALUMINUM":
                # Corrected value — DIFFERENT from the baseline 2700.
                return PriceQuote(
                    value=Decimal("2750"),
                    source="lme_cash_settlement",
                    settlement_date=date(2026, 1, 31),
                    symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                )
            raise PriceReferenceUnprovable(
                f"simulated repair: {commodity} source row deleted",
                commodity=commodity,
            )

        monkeypatch.setattr(deal_engine_mod, "_get_market_quote", _mixed_quote)

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        # Route must map PriceReferenceUnprovable to 422 (4xx contract).
        assert r2.status_code == 422, r2.text
        # The baseline snapshot is NOT returned and no new row is
        # persisted — exactly one row exists, and it is snap1.
        with SessionLocal() as s:
            rows = (
                s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .all()
            )
            assert len(rows) == 1
            assert str(rows[0].id) == snap1["id"]
            assert rows[0].inputs_hash == snap1["inputs_hash"]

    def test_compute_deal_pnl_partial_quote_success_unchanged_value_fails_closed(
        self, client, session, monkeypatch
    ):
        """Strict semantics — partial success ALWAYS fails closed,
        even when the fresh ALU value EQUALS the baseline.

        The unprovable COPPER commodity cannot be proven consistent
        without a live quote, so reusing the candidate is unsafe by
        contract regardless of whether the freshly-quoted commodities
        happen to match. This pins the strict interpretation in the
        dispatch §3.4.1 partial-success row.
        """
        from app.services import deal_engine as deal_engine_mod
        from app.services.price_lookup_service import (
            PriceQuote,
            PriceReferenceUnprovable,
        )

        deal_id, snap1 = self._build_multi_commodity_deal_with_snapshot(
            client, session
        )

        def _mixed_quote(_session, commodity, _as_of_date):
            if commodity == "ALUMINUM":
                # SAME value as the baseline — no correction.
                return PriceQuote(
                    value=Decimal("2700"),
                    source="lme_cash_settlement",
                    settlement_date=date(2026, 1, 31),
                    symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                )
            raise PriceReferenceUnprovable(
                f"simulated repair: {commodity} source row deleted",
                commodity=commodity,
            )

        monkeypatch.setattr(deal_engine_mod, "_get_market_quote", _mixed_quote)

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 422, r2.text
        with SessionLocal() as s:
            rows = (
                s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .all()
            )
            assert len(rows) == 1
            assert str(rows[0].id) == snap1["id"]
            assert rows[0].inputs_hash == snap1["inputs_hash"]

    def test_compute_deal_pnl_total_unavailability_reuses_candidate(
        self, client, session, monkeypatch
    ):
        """Total unavailability (multi-commodity) → repair scenario
        reuses the candidate. ZERO fresh quotes obtained, so the
        candidate fallback is honest (no fresh evidence to be stale
        relative to). Mirrors the single-commodity reuse test but
        confirms multi-commodity coverage.
        """
        from app.services import deal_engine as deal_engine_mod
        from app.services.price_lookup_service import PriceReferenceUnprovable

        deal_id, snap1 = self._build_multi_commodity_deal_with_snapshot(
            client, session
        )
        snapshot_date_obj = date(2026, 2, 1)

        def _all_unprovable(_session, commodity, _as_of_date):
            raise PriceReferenceUnprovable(
                f"simulated repair: {commodity} source row deleted",
                commodity=commodity,
            )

        monkeypatch.setattr(
            deal_engine_mod, "_get_market_quote", _all_unprovable
        )

        with SessionLocal() as s:
            snap2 = DealEngineService.compute_deal_pnl(
                s, uuid.UUID(deal_id), snapshot_date_obj
            )
            s.commit()
            snap2_id = str(snap2.id)
            snap2_hash = snap2.inputs_hash

        assert snap2_id == snap1["id"]
        assert snap2_hash == snap1["inputs_hash"]
        with SessionLocal() as s:
            assert (
                s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .count()
                == 1
            )


# ──────────────────────────────────────────────────────────────────────
# Codex P2 (PR #22) — sequence is the canonical tie-breaker for the
# detail (latest_pnl) and history reads.
#
# When a corrected market quote produces a second snapshot for the same
# (deal_id, snapshot_date), SQLite ``created_at`` second-precision can
# tie. The detail/history endpoints must surface the NEW row, not the
# stale pre-correction one. ``DealPNLSnapshot.sequence`` is monotonic
# per insertion and is the deterministic tie-breaker.
# ──────────────────────────────────────────────────────────────────────


class TestSequenceOrderingOnReads:
    @staticmethod
    def _seed_simple_deal(client, session) -> str:
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=2700.0,
        )
        r = client.post(ENDPOINT, json={"name": "SeqOrd", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        so_id = _create_order(session, OrderType.sales)
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )
        return deal_id

    def test_detail_endpoint_returns_newest_snapshot_after_correction(
        self, client, session
    ):
        """Detail (``latest_pnl``) must surface the post-correction row.

        Forces ``created_at`` to tie via direct UPDATE so the test
        exercises the ``sequence`` tie-breaker rather than relying on
        timestamp progression.
        """
        deal_id = self._seed_simple_deal(client, session)

        # Snap 1 at price 2700.
        r1 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r1.status_code == 201
        snap_old_id = r1.json()["id"]

        # Correct the underlying price → next snapshot has a different
        # inputs_hash and is persisted as a new row.
        with SessionLocal() as s:
            row = (
                s.query(CashSettlementPrice)
                .filter(
                    CashSettlementPrice.symbol
                    == "LME_ALU_CASH_SETTLEMENT_DAILY"
                )
                .first()
            )
            row.price_usd = 2750.0
            s.commit()

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        )
        assert r2.status_code == 201
        snap_new_id = r2.json()["id"]
        assert snap_new_id != snap_old_id

        # Force ``created_at`` to tie so ``sequence`` is the only thing
        # disambiguating the two rows.
        with SessionLocal() as s:
            tied = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
            s.execute(
                sa.update(DealPNLSnapshot)
                .where(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .values(created_at=tied)
            )
            s.commit()
            # Confirm both rows actually share the same created_at.
            cas = [
                row.created_at
                for row in s.query(DealPNLSnapshot)
                .filter(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .all()
            ]
            assert len(cas) == 2
            assert cas[0] == cas[1]

        # Detail endpoint must return the post-correction row.
        r_detail = client.get(f"{ENDPOINT}/{deal_id}")
        assert r_detail.status_code == 200
        latest = r_detail.json()["latest_pnl"]
        assert latest is not None
        assert latest["id"] == snap_new_id

    def test_history_endpoint_orders_by_snapshot_date_then_sequence(
        self, client, session
    ):
        """History endpoint orders by (snapshot_date DESC, sequence DESC).

        Builds 4 snapshots — 2 on date D1 (a correction produces a
        second row), 2 on date D2 (same). Asserts the returned order
        is D2-newest, D2-oldest, D1-newest, D1-oldest. Forces tied
        ``created_at`` so ``sequence`` is the active tie-breaker.
        """
        # Two days of prices so we can compute snapshots for D1 and D2.
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 30),
            price_usd=2700.0,
        )
        _insert_price(
            session,
            symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
            settlement_date=date(2026, 1, 31),
            price_usd=2705.0,
        )
        r = client.post(
            ENDPOINT, json={"name": "SeqHist", "commodity": "ALUMINUM"}
        )
        deal_id = r.json()["id"]
        so_id = _create_order(session, OrderType.sales)
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )

        def _correct_price(settlement_date_obj: date, new_value: float) -> None:
            with SessionLocal() as s:
                row = (
                    s.query(CashSettlementPrice)
                    .filter(
                        CashSettlementPrice.symbol
                        == "LME_ALU_CASH_SETTLEMENT_DAILY",
                        CashSettlementPrice.settlement_date
                        == settlement_date_obj,
                    )
                    .first()
                )
                row.price_usd = new_value
                s.commit()

        # D1 = 2026-01-31 (uses settlement 2026-01-30).
        # D2 = 2026-02-01 (uses settlement 2026-01-31).
        d1_old = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-01-31"},
        ).json()["id"]
        _correct_price(date(2026, 1, 30), 2710.0)
        d1_new = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-01-31"},
        ).json()["id"]
        d2_old = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        ).json()["id"]
        _correct_price(date(2026, 1, 31), 2715.0)
        d2_new = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot",
            params={"snapshot_date": "2026-02-01"},
        ).json()["id"]

        assert len({d1_old, d1_new, d2_old, d2_new}) == 4

        # Force all four rows to share the same ``created_at`` so the
        # within-date tie-breaker is exclusively ``sequence``.
        with SessionLocal() as s:
            tied = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
            s.execute(
                sa.update(DealPNLSnapshot)
                .where(DealPNLSnapshot.deal_id == uuid.UUID(deal_id))
                .values(created_at=tied)
            )
            s.commit()

        r_hist = client.get(f"{ENDPOINT}/{deal_id}/pnl-history")
        assert r_hist.status_code == 200
        ids = [item["id"] for item in r_hist.json()["items"]]
        assert ids == [d2_new, d2_old, d1_new, d1_old]
