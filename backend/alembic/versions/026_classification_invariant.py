"""Enforce HedgeContract classification invariant.

Revision ID: 026_classification_invariant
Revises: 025_decimal_primitives
Create Date: 2026-05-06 00:00:00.000000

"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "026_classification_invariant"
down_revision: Union[str, None] = "025_decimal_primitives"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_NAME = "chk_classification_matches_fixed_leg"
CONSTRAINT_SQL = (
    "(fixed_leg_side = 'buy' AND classification = 'long') OR "
    "(fixed_leg_side = 'sell' AND classification = 'short')"
)

logger = logging.getLogger(__name__)


def _backfill_inconsistent_classifications(bind) -> int:
    """Canonicalize drifted rows using fixed_leg_side as source of truth."""
    if bind.dialect.name == "postgresql":
        long_expr = "CAST('long' AS hedge_classification)"
        short_expr = "CAST('short' AS hedge_classification)"
    else:
        # SQLite (test dialect): no named ENUM type — plain text literals.
        # Casting to an unknown type name on SQLite triggers NUMERIC affinity
        # coercion, which would write 0 into the classification column.
        long_expr = "'long'"
        short_expr = "'short'"

    result = bind.execute(
        sa.text(
            f"""
            UPDATE hedge_contracts
            SET classification = CASE fixed_leg_side
                WHEN 'buy' THEN {long_expr}
                WHEN 'sell' THEN {short_expr}
            END
            WHERE (fixed_leg_side = 'buy' AND classification <> 'long')
               OR (fixed_leg_side = 'sell' AND classification <> 'short')
            """
        )
    )
    corrected = int(result.rowcount or 0)
    logger.warning(
        "classification invariant backfill corrected %s hedge_contracts rows",
        corrected,
    )
    return corrected


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    _backfill_inconsistent_classifications(bind)

    if is_pg:
        op.create_check_constraint(
            CONSTRAINT_NAME,
            "hedge_contracts",
            CONSTRAINT_SQL,
        )
    else:
        with op.batch_alter_table("hedge_contracts") as batch:
            batch.create_check_constraint(CONSTRAINT_NAME, CONSTRAINT_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.drop_constraint(CONSTRAINT_NAME, "hedge_contracts", type_="check")
    else:
        with op.batch_alter_table("hedge_contracts") as batch:
            batch.drop_constraint(CONSTRAINT_NAME, type_="check")
