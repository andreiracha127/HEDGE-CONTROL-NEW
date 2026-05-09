"""Merge Phase A2 W-1 forked heads (033_rfq_decimal_primitives + 035_rfq_state_event_ts_not_null).

Revision ID: 036_merge_w1_heads
Revises: 033_rfq_decimal_primitives, 035_rfq_state_event_ts_not_null
Create Date: 2026-05-09 00:00:00.000000

Phase A2 W-1 closure hygiene. PR-1 (#28, `033_rfq_decimal_primitives`) and
PR-3 (#27, `035_rfq_state_event_ts_not_null`) were authored against
`032_linkage_capacity_live_filter` in parallel and merged into ``main``
without either rebasing its ``down_revision`` after the sibling landed.
``alembic.script.get_heads()`` reported two heads on ``main = f6914a8``,
so any production ``alembic upgrade head`` would fail with
``MultipleHeads``.

The fork was not caught because the test fixture builds its schema via
``Base.metadata.create_all()`` rather than alembic — a silent fallback
in the test layer that hid a hard-fail in the migration layer.

This is a no-op merge revision: it does not run any DDL of its own; it
only unifies the chain so subsequent migrations have a single linear
parent. Rewriting the ``down_revision`` of either 033 or 035 is unsafe
because either revision may already be recorded in a deployed database's
``alembic_version`` table — alembic would treat the rewritten ancestor
as already applied and skip its DDL forever.

Coverage of the three possible deployed states:
- ``alembic_version = '032_linkage_capacity_live_filter'``: ``upgrade head``
  applies 033 → 035 → 036 in order.
- ``alembic_version = '033_rfq_decimal_primitives'``: ``upgrade head``
  applies 035 → 036.
- ``alembic_version = '035_rfq_state_event_ts_not_null'``: ``upgrade head``
  applies 033 → 036.
"""

from __future__ import annotations

from typing import Sequence, Union


revision: str = "036_merge_w1_heads"
down_revision: Union[str, Sequence[str], None] = (
    "033_rfq_decimal_primitives",
    "035_rfq_state_event_ts_not_null",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: this revision exists only to merge the W-1 forked heads."""


def downgrade() -> None:
    """No-op: this revision exists only to merge the W-1 forked heads."""
