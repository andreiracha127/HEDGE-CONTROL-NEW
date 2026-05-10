"""Phase A3 Wave 4: archive legacy baseline payloads.

Revision ID: 039_a3_cashflow_baseline_archive
Revises: 038_a3_price_provenance
Create Date: 2026-05-10 00:00:00.000000
"""

from __future__ import annotations

import uuid
from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "039_a3_cashflow_baseline_archive"
down_revision = "038_a3_price_provenance"
branch_labels = None
depends_on = None

ARCHIVE_REASON = "PR-A3-4 legacy analytic-shaped baseline payload"


def _uuid_type(dialect_name: str):
    if dialect_name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(length=36)


def _new_archive_id(dialect_name: str):
    value = uuid.uuid4()
    if dialect_name == "postgresql":
        return value
    return str(value)


def _is_legacy_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return True
    if "cashflow_items" in payload:
        return True
    return payload.get("view") != "baseline"


def _source_table(bind: sa.Connection) -> sa.Table:
    return sa.Table(
        "cashflow_baseline_snapshots",
        sa.MetaData(),
        autoload_with=bind,
    )


def _archive_table(bind: sa.Connection) -> sa.Table:
    return sa.Table(
        "cashflow_baseline_snapshot_archives",
        sa.MetaData(),
        autoload_with=bind,
    )


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    json_type = postgresql.JSONB() if dialect_name == "postgresql" else sa.JSON()
    uuid_type = _uuid_type(dialect_name)

    null_correlation_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM cashflow_baseline_snapshots "
            "WHERE correlation_id IS NULL"
        )
    ).scalar()
    if null_correlation_count:
        raise RuntimeError(
            "Refusing to archive legacy baseline snapshots with NULL correlation_id; "
            "manual remediation required before migration can proceed."
        )

    op.create_table(
        "cashflow_baseline_snapshot_archives",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("original_snapshot_id", uuid_type, nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("snapshot_data", json_type, nullable=False),
        sa.Column("total_net_cashflow", sa.Numeric(18, 6), nullable=False),
        sa.Column("inputs_hash", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("original_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("archive_reason", sa.String(length=128), nullable=False),
    )

    source = _source_table(bind)
    archive = _archive_table(bind)
    rows = bind.execute(sa.select(source)).mappings().all()
    legacy_rows = [row for row in rows if _is_legacy_payload(row["snapshot_data"])]

    if legacy_rows:
        bind.execute(
            archive.insert(),
            [
                {
                    "id": _new_archive_id(dialect_name),
                    "original_snapshot_id": row["id"],
                    "as_of_date": row["as_of_date"],
                    "snapshot_data": row["snapshot_data"],
                    "total_net_cashflow": row["total_net_cashflow"],
                    "inputs_hash": row["inputs_hash"],
                    "correlation_id": row["correlation_id"],
                    "original_created_at": row["created_at"],
                    "archive_reason": ARCHIVE_REASON,
                }
                for row in legacy_rows
            ],
        )
        bind.execute(
            source.delete().where(source.c.id.in_([row["id"] for row in legacy_rows]))
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("cashflow_baseline_snapshot_archives"):
        return

    source = _source_table(bind)
    archive = _archive_table(bind)
    archived_rows = bind.execute(sa.select(archive)).mappings().all()

    for row in archived_rows:
        if row["correlation_id"] is None:
            raise RuntimeError(
                "Refusing to restore archived baseline snapshots with NULL correlation_id; "
                "manual remediation required before downgrade can proceed."
            )
        active_count = bind.execute(
            sa.select(sa.func.count())
            .select_from(source)
            .where(source.c.as_of_date == row["as_of_date"])
        ).scalar_one()
        if active_count:
            raise RuntimeError(
                "Refusing to restore archived baseline snapshot because an active "
                "baseline snapshot already exists for the same as_of_date."
            )

    if archived_rows:
        bind.execute(
            source.insert(),
            [
                {
                    "id": row["original_snapshot_id"],
                    "as_of_date": row["as_of_date"],
                    "snapshot_data": row["snapshot_data"],
                    "total_net_cashflow": row["total_net_cashflow"],
                    "inputs_hash": row["inputs_hash"],
                    "correlation_id": row["correlation_id"],
                    "created_at": row["original_created_at"],
                }
                for row in archived_rows
            ],
        )

    op.drop_table("cashflow_baseline_snapshot_archives")
