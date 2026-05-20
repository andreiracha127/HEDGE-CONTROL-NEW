"""rfq_quote_attribution_columns

Adds actor_sub and inbound_message_id to rfq_quotes so quote attribution
(human REST actor sub vs LLM inbound message id) is durably persisted
rather than living only as transient Python attributes on the ORM instance.

Revision ID: 046_rfq_quote_attribution_columns
Revises: 045_market_data_governance_columns
Create Date: 2026-05-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "046_rfq_quote_attribution_columns"
down_revision = "045_market_data_governance_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rfq_quotes",
        sa.Column("actor_sub", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "rfq_quotes",
        sa.Column(
            "inbound_message_id",
            UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("rfq_quotes", "inbound_message_id")
    op.drop_column("rfq_quotes", "actor_sub")
