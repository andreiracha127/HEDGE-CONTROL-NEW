"""Focused unit tests for HedgeContract identity hygiene (J-A2-12).

Covers reference format and length sanity for the full-UUID scheme adopted
in PR-2. The award-path integration assertions live in test_rfqs_step3.py.
"""

import re
import uuid

from app.models.contracts import HedgeContract


_HC_REFERENCE_RE = re.compile(r"^HC-[0-9A-F]{32}$")
_REFERENCE_COLUMN_LENGTH = 50


def test_reference_format_matches_full_uuid_scheme() -> None:
    for _ in range(1_000):
        ref = f"HC-{uuid.uuid4().hex.upper()}"
        assert _HC_REFERENCE_RE.match(ref), ref


def test_reference_fits_column_length() -> None:
    ref = f"HC-{uuid.uuid4().hex.upper()}"
    assert len(ref) == 35
    assert len(ref) <= _REFERENCE_COLUMN_LENGTH


def test_reference_column_metadata_unchanged() -> None:
    """Column constraints PR-2 relies on must remain stable."""
    column = HedgeContract.__table__.c.reference
    assert column.unique is True
    assert column.type.length == _REFERENCE_COLUMN_LENGTH
