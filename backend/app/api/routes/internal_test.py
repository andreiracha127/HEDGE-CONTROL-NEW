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
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    columns_by_table = _columns_by_table(inspector, existing_tables)
    escaped_trace = _escape_like(request.trace_id)
    rfq_like = f"{escaped_trace} %"
    counterparty_like = f"{escaped_trace}-%"
    source_like = f"e2e://{escaped_trace}/%"

    with engine.begin() as connection:
        rfq_filter = """
            SELECT id FROM rfqs
            WHERE text_en LIKE :rfq_like ESCAPE '\\'
                OR text_pt LIKE :rfq_like ESCAPE '\\'
        """
        rfq_params = {"rfq_like": rfq_like}
        if _has_columns(existing_tables, columns_by_table, "rfqs", ("text_en", "text_pt")):
            audit_where = [f"(entity_type = 'rfq' AND entity_id IN ({rfq_filter}))"]
            if _has_columns(existing_tables, columns_by_table, "hedge_contracts", ("rfq_id",)):
                contract_filter = f"""
                    SELECT id FROM hedge_contracts
                    WHERE rfq_id IN ({rfq_filter})
                """
                audit_where.append(
                    f"""
                    (
                        entity_type = 'hedge_contract'
                        AND entity_id IN ({contract_filter})
                    )
                    """
                )
            deleted["audit_events"] = _delete_if_columns(
                connection,
                existing_tables,
                columns_by_table,
                "audit_events",
                ("entity_type", "entity_id"),
                " OR ".join(audit_where),
                rfq_params,
            )
            deleted["hedge_contracts"] = _delete_if_columns(
                connection,
                existing_tables,
                columns_by_table,
                "hedge_contracts",
                ("rfq_id",),
                f"rfq_id IN ({rfq_filter})",
                rfq_params,
            )
            deleted["rfq_quotes"] = _delete_if_columns(
                connection,
                existing_tables,
                columns_by_table,
                "rfq_quotes",
                ("rfq_id",),
                f"rfq_id IN ({rfq_filter})",
                rfq_params,
            )
            deleted["rfq_invitations"] = _delete_if_columns(
                connection,
                existing_tables,
                columns_by_table,
                "rfq_invitations",
                ("rfq_id",),
                f"rfq_id IN ({rfq_filter})",
                rfq_params,
            )
            deleted["rfq_state_events"] = _delete_if_columns(
                connection,
                existing_tables,
                columns_by_table,
                "rfq_state_events",
                ("rfq_id",),
                f"rfq_id IN ({rfq_filter})",
                rfq_params,
            )
            deleted["rfqs"] = _delete_if_columns(
                connection,
                existing_tables,
                columns_by_table,
                "rfqs",
                ("text_en", "text_pt"),
                "text_en LIKE :rfq_like ESCAPE '\\' OR text_pt LIKE :rfq_like ESCAPE '\\'",
                rfq_params,
            )
        else:
            for table in (
                "audit_events",
                "hedge_contracts",
                "rfq_quotes",
                "rfq_invitations",
                "rfq_state_events",
                "rfqs",
            ):
                deleted[table] = -1
        deleted["cash_settlement_prices"] = _delete_if_columns(
            connection,
            existing_tables,
            columns_by_table,
            "cash_settlement_prices",
            ("source_url",),
            "source_url LIKE :source_like ESCAPE '\\'",
            {"source_like": source_like},
        )
        deleted["counterparties"] = _delete_if_columns(
            connection,
            existing_tables,
            columns_by_table,
            "counterparties",
            ("tax_id",),
            "tax_id LIKE :counterparty_like ESCAPE '\\'",
            {"counterparty_like": counterparty_like},
        )
    return deleted


def _columns_by_table(inspector: Any, existing_tables: set[str]) -> dict[str, set[str]]:
    cleanup_tables = {
        "audit_events",
        "hedge_contracts",
        "rfq_quotes",
        "rfq_invitations",
        "rfq_state_events",
        "rfqs",
        "cash_settlement_prices",
        "counterparties",
    }
    return {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in cleanup_tables
        if table in existing_tables
    }


def _delete_if_columns(
    connection: Any,
    existing_tables: set[str],
    columns_by_table: dict[str, set[str]],
    table: str,
    required_columns: tuple[str, ...],
    where_clause: str,
    params: dict[str, Any],
) -> int:
    if table not in existing_tables:
        return -1
    if any(column not in columns_by_table[table] for column in required_columns):
        return -1
    result = connection.execute(
        text(f'DELETE FROM "{table}" WHERE {where_clause}'),
        params,
    )
    return result.rowcount or 0


def _has_columns(
    existing_tables: set[str],
    columns_by_table: dict[str, set[str]],
    table: str,
    required_columns: tuple[str, ...],
) -> bool:
    return table in existing_tables and all(
        column in columns_by_table[table] for column in required_columns
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
