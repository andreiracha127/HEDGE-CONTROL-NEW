"""Guard against forked alembic migration chains.

The fork between PR-1 (`033_rfq_decimal_primitives`) and PR-3
(`035_rfq_state_event_ts_not_null`) — both pointing at
`032_linkage_capacity_live_filter` as their down_revision — was merged into
`main` undetected because the test suite builds its schema via
`Base.metadata.create_all()` rather than running alembic. This test invokes
alembic's own ScriptDirectory and asserts a single linear head, so any future
PR that introduces a parallel head fails CI before merge.
"""
from __future__ import annotations

import os

from alembic.config import Config
from alembic.script import ScriptDirectory


def _alembic_config() -> Config:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return Config(os.path.join(backend_dir, "alembic.ini"))


def test_alembic_chain_has_single_head() -> None:
    script_dir = ScriptDirectory.from_config(_alembic_config())
    heads = script_dir.get_heads()
    assert len(heads) == 1, (
        f"alembic migration chain forked — got {len(heads)} heads: {heads!r}. "
        "Every new migration must rebase its `down_revision` onto the current "
        "single head before merge."
    )


def test_alembic_chain_walks_from_base_to_head_without_gaps() -> None:
    script_dir = ScriptDirectory.from_config(_alembic_config())
    heads = script_dir.get_heads()
    assert len(heads) == 1, f"single-head precondition failed: {heads!r}"
    head = heads[0]
    revisions = list(script_dir.walk_revisions("base", head))
    revision_ids = [r.revision for r in revisions]
    assert head in revision_ids, f"head {head!r} not reachable from base"
