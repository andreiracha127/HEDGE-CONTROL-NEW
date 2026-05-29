from __future__ import annotations

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "049_commercial_partners_foundation.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_049", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _create_pre_049_schema(conn: sa.Connection) -> None:
    md = sa.MetaData()
    sa.Table(
        "counterparties",
        md,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("short_name", sa.String(length=50)),
        sa.Column("tax_id", sa.String(length=50)),
        sa.Column("country", sa.String(length=3), nullable=False),
        sa.Column("city", sa.String(length=100)),
        sa.Column("address", sa.Text()),
        sa.Column("contact_name", sa.String(length=200)),
        sa.Column("contact_email", sa.String(length=200)),
        sa.Column("contact_phone", sa.String(length=50)),
        sa.Column("whatsapp_phone", sa.String(length=50)),
        sa.Column("credit_limit_usd", sa.Numeric(15, 2)),
        sa.Column("risk_rating", sa.String(length=10), nullable=False),
        sa.Column("kyc_status", sa.String(length=12), nullable=False),
        sa.Column("sanctions_status", sa.String(length=12), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    for ref in (
        "orders",
        "rfq_invitations",
        "rfq_quotes",
        "hedge_contracts",
        "llm_decision_artifacts",
    ):
        sa.Table(
            ref,
            md,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("counterparty_id", sa.String(length=100)),
        )
    md.create_all(conn)


def _seed_counterparty(conn, cp_id, type_, name, credit=None, is_deleted=0, kyc_status="approved"):
    conn.execute(
        sa.text(
            "INSERT INTO counterparties (id, type, name, country, risk_rating, "
            "kyc_status, sanctions_status, is_active, is_deleted, credit_limit_usd, created_at) VALUES "
            "(:id, :type, :name, 'BRA', 'medium', :kyc_status, 'clear', 1, :is_deleted, :credit, "
            "'2026-01-01 00:00:00')"
        ),
        {
            "id": cp_id,
            "type": type_,
            "name": name,
            "credit": credit,
            "is_deleted": is_deleted,
            "kyc_status": kyc_status,
        },
    )


def _run(conn, direction):
    m = _load()
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        getattr(m, direction)()


def test_049_chains_from_048():
    m = _load()
    assert m.revision == "049_commercial_partners_foundation"
    assert m.down_revision == "048_order_external_reference"


def test_049_migrates_customer_supplier_preserving_uuid_and_resets_fail_closed():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        _create_pre_049_schema(conn)
        cust_id = str(uuid.uuid4())
        supp_id = str(uuid.uuid4())
        broker_id = str(uuid.uuid4())
        del_id = str(uuid.uuid4())
        _seed_counterparty(conn, cust_id, "customer", "Cust", credit=1000)
        _seed_counterparty(conn, supp_id, "supplier", "Supp", credit=2000)
        _seed_counterparty(conn, broker_id, "broker", "Brk")
        # a soft-deleted customer must still migrate (an order may FK it)
        _seed_counterparty(conn, del_id, "customer", "DelCust", credit=500, is_deleted=1)
        # an order referencing the customer (valid)
        conn.execute(
            sa.text("INSERT INTO orders (id, counterparty_id) VALUES (:i, :c)"),
            {"i": str(uuid.uuid4()), "c": cust_id},
        )

        _run(conn, "upgrade")

        rows = conn.execute(
            sa.text(
                "SELECT id, kind, kyc_status, sanctions_status, credit_limit, approved_value, "
                "credit_currency, approved_currency, is_deleted "
                "FROM commercial_partners"
            )
        ).fetchall()
        by_id = {r[0]: r for r in rows}
        assert cust_id in by_id and supp_id in by_id  # UUID reused
        assert by_id[cust_id][1] == "customer"
        assert by_id[cust_id][2] == "pending"  # kyc reset
        assert by_id[cust_id][3] == "unscreened"  # sanctions reset
        assert Decimal(str(by_id[cust_id][4])) == Decimal("1000.00")  # customer credit_limit
        assert by_id[cust_id][5] is None  # customer has no approved_value
        assert by_id[cust_id][6] == "USD"  # customer credit_currency derived
        assert Decimal(str(by_id[supp_id][5])) == Decimal("2000.00")  # supplier approved_value
        assert by_id[supp_id][4] is None  # supplier has no credit_limit
        assert by_id[supp_id][7] == "USD"  # supplier approved_currency derived
        # soft-deleted customer migrated, is_deleted preserved (FK safety)
        assert del_id in by_id
        assert bool(by_id[del_id][8]) is True

        # counterparties now hedge-only; hedge sanctions reset to unscreened
        remaining = conn.execute(
            sa.text("SELECT type, kyc_status, sanctions_status FROM counterparties")
        ).fetchall()
        assert {r[0] for r in remaining} == {"broker"}
        assert remaining[0][1] == "pending"
        assert remaining[0][2] == "unscreened"

        # order still resolves to a commercial_partner with the same id
        oc = conn.execute(sa.text("SELECT counterparty_id FROM orders")).scalar_one()
        assert oc == cust_id


def test_049_halts_when_order_references_hedge_counterparty():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        _create_pre_049_schema(conn)
        broker_id = str(uuid.uuid4())
        _seed_counterparty(conn, broker_id, "broker", "Brk")
        conn.execute(
            sa.text("INSERT INTO orders (id, counterparty_id) VALUES (:i, :c)"),
            {"i": str(uuid.uuid4()), "c": broker_id},
        )
        with pytest.raises(RuntimeError, match="reference a hedge"):
            _run(conn, "upgrade")


def test_049_halts_when_hedge_ref_points_at_commercial_counterparty():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        _create_pre_049_schema(conn)
        cust_id = str(uuid.uuid4())
        _seed_counterparty(conn, cust_id, "customer", "Cust")
        conn.execute(
            sa.text("INSERT INTO rfq_invitations (id, counterparty_id) VALUES (:i, :c)"),
            {"i": str(uuid.uuid4()), "c": cust_id},
        )
        with pytest.raises(RuntimeError, match="hedge-domain references"):
            _run(conn, "upgrade")


def test_049_check_constraint_blocks_cross_kind_credit():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        _create_pre_049_schema(conn)
        _run(conn, "upgrade")
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO commercial_partners "
                    "(id, kind, name, country, lei_status, kyc_status, sanctions_status, "
                    "risk_rating, is_active, is_deleted, approved_value) VALUES "
                    "(:i, 'customer', 'X', 'BRA', 'not_provided', 'pending', 'unscreened', "
                    "'medium', 1, 0, 5.00)"
                ),
                {"i": str(uuid.uuid4())},
            )


def test_049_check_constraint_blocks_supplier_credit_limit():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        _create_pre_049_schema(conn)
        _run(conn, "upgrade")
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO commercial_partners "
                    "(id, kind, name, country, lei_status, kyc_status, sanctions_status, "
                    "risk_rating, is_active, is_deleted, credit_limit) VALUES "
                    "(:i, 'supplier', 'Y', 'BRA', 'not_provided', 'pending', 'unscreened', "
                    "'medium', 1, 0, 9.00)"
                ),
                {"i": str(uuid.uuid4())},
            )


def test_049_postgres_hedge_type_filter_casts_enum_to_text():
    m = _load()
    assert m._counterparty_type_expr(is_pg=True) == "type::text"
    assert m._counterparty_type_expr(is_pg=False) == "type"
