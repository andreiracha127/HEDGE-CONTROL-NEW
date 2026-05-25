"""Add hedge contract status

Revision ID: 010_add_hedge_contract_status
Revises: 009_phase4_step2_mtm_snapshots
Create Date: 2026-02-01 20:05:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_add_hedge_contract_status"
down_revision: Union[str, None] = "009_phase4_step2_mtm_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Same instance is used twice: once to .create() the type, then as the column type.
        # Reusing the postgresql.ENUM instance (with create_type=False) is the only way
        # to guarantee op.add_column does NOT emit a second CREATE TYPE under SA 2.0+.
        # The generic sa.Enum drops create_type silently — see Codex review 2026-05-22.
        status_enum_pg = postgresql.ENUM(
            "active", "cancelled", "settled",
            name="hedge_contract_status", create_type=False,
        )
        status_enum_pg.create(bind, checkfirst=True)
        op.add_column(
            "hedge_contracts",
            sa.Column(
                "status",
                status_enum_pg,
                nullable=False,
                server_default="active",
            ),
        )
    else:
        op.add_column(
            "hedge_contracts",
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        )

    op.execute("UPDATE hedge_contracts SET status = 'active' WHERE status IS NULL")


def downgrade() -> None:
    op.drop_column("hedge_contracts", "status")
