from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


@contextmanager
def unit_of_work(
    session: Session,
    *,
    request: Request | None = None,
) -> Iterator[Session]:
    """Commit one route-level mutation boundary, including deferred audit rows."""
    try:
        yield session
        if request is not None and hasattr(request.state, "audit_commit"):
            previous = getattr(request.state, "audit_defer_commit", False)
            request.state.audit_defer_commit = True
            try:
                request.state.audit_commit()
            finally:
                request.state.audit_defer_commit = previous
        session.commit()
    except Exception:
        session.rollback()
        raise
