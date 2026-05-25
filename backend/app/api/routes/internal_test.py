"""Test-only internal endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import inspect, text

from app.core.auth import get_current_user
from app.core.database import engine

router = APIRouter(prefix="/internal/test", tags=["internal-test"])


def require_e2e_cleanup_identity(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if user.get("sub") != "service:e2e_cleanup":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="e2e_cleanup_identity_required",
        )
    return user


class CleanupRequest(BaseModel):
    trace_id: str = Field(min_length=1, max_length=128)


@router.post("/cleanup")
def cleanup_by_trace_id(
    request: CleanupRequest,
    _identity: dict[str, Any] = Depends(require_e2e_cleanup_identity),
) -> dict[str, int]:
    deleted: dict[str, int] = {}
    tables_with_trace = (
        "audit_events",
        "rfqs",
        "deals",
        "hedge_contracts",
        "counterparties",
    )
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    columns_by_table = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in tables_with_trace
        if table in existing_tables
    }

    with engine.begin() as connection:
        for table in tables_with_trace:
            if table not in existing_tables or "trace_id" not in columns_by_table[table]:
                deleted[table] = -1
                continue
            result = connection.execute(
                text(f'DELETE FROM "{table}" WHERE trace_id = :trace_id'),
                {"trace_id": request.trace_id},
            )
            deleted[table] = result.rowcount or 0
    return deleted
