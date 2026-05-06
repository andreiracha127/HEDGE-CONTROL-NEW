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
from datetime import date, datetime, timezone
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
# Postgres dialect guard in ``028_pnl_provenance.py``. SQLite test envs
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
                / "028_pnl_provenance.py"
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

        assert str(snap2.id) == snap1["id"]
        assert snap2.inputs_hash == snap1["inputs_hash"]
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
