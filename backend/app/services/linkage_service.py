"""Shared linkage creation logic used by both linkages route and RFQ award."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.pagination import paginate
from app.core.precision import quantize_mt
from app.models.contracts import HedgeClassification, HedgeContract, HedgeContractStatus
from app.models.linkages import HedgeOrderLinkage
from app.models.orders import Order, OrderType, PriceType
from app.services.price_lookup_service import canonical_commodity


def _is_postgres(session: Session) -> bool:
    bind = session.get_bind()
    return bind is not None and bind.dialect.name == "postgresql"


def _validate_linkage_direction(order: Order, contract: HedgeContract) -> None:
    """Reject direction-mismatched hedge/order pairs and fixed-price hedges.

    Constitution §2.3 + §2.4:
    - Sales order (SO) requires a SHORT hedge (sell-forward hedges sales price)
    - Purchase order (PO) requires a LONG hedge (buy-forward hedges purchase)
    - Fixed-price orders carry no market exposure and cannot be hedged.

    Rule mirrors ``DealEngineService._validate_hedge_direction`` (deal_engine.py
    around lines 152-220) but applied to the ``HedgeOrderLinkage`` aggregate.
    """
    if order.price_type == PriceType.fixed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Cannot hedge a fixed-price order. "
                "Only variable-price orders have market exposure "
                "and require hedging."
            ),
        )

    if order.order_type == OrderType.sales:
        expected = HedgeClassification.short
    else:  # OrderType.purchase
        expected = HedgeClassification.long

    if contract.classification != expected:
        order_label = (
            "sales" if order.order_type == OrderType.sales else "purchase"
        )
        expected_label = (
            "short (sell-forward)"
            if expected == HedgeClassification.short
            else "long (buy-forward)"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Linkage direction mismatch: {order_label} order requires a "
                f"{expected_label} hedge, but contract classification is "
                f"{contract.classification.value}."
            ),
        )


class LinkageService:
    """Validates overflow constraints and persists a new HedgeOrderLinkage."""

    @staticmethod
    def create(
        session: Session,
        order_id: UUID,
        contract_id: UUID,
        quantity_mt: Decimal,
    ) -> HedgeOrderLinkage:
        is_pg = _is_postgres(session)

        # ── Layer 3 (advisory lock, PostgreSQL only) ──────────────────────
        # Cross-transaction serialization scoped to this (order, contract) pair.
        # Cheap; falls through cleanly on SQLite.
        if is_pg:
            session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtext('linkage:' || :oid || ':' || :cid))"
                ),
                {"oid": str(order_id), "cid": str(contract_id)},
            )

        # ── Layer 1 (row-level lock on constraining rows) ─────────────────
        # ``with_for_update`` is a no-op on SQLite but required on PostgreSQL
        # to serialize concurrent capacity reads against the same order or
        # contract. See jury §2 J-A1-03 for mechanism analysis.
        order_query = session.query(Order).filter(Order.id == order_id)
        contract_query = session.query(HedgeContract).filter(
            HedgeContract.id == contract_id
        )
        if is_pg:
            order_query = order_query.with_for_update()
            contract_query = contract_query.with_for_update()

        order = order_query.one_or_none()
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )

        contract = contract_query.one_or_none()
        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hedge contract not found",
            )

        # ── Codex P2 lifecycle gate ───────────────────────────────────────
        # Mirror the §3.5 / §3.9 dual-filter on the WRITE path. The read
        # path now ignores any linkage whose order is soft-deleted or whose
        # hedge contract is settled / cancelled / soft-deleted; without
        # this gate clients can still 201 a linkage that every downstream
        # consumer (snapshots, reconcile, net exposure) treats as
        # invisible. Reject up-front so the API contract is consistent.
        if order.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Cannot link to an archived order",
            )
        if contract.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Cannot link to an archived hedge contract",
            )
        if contract.status not in (
            HedgeContractStatus.active,
            HedgeContractStatus.partially_settled,
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Cannot link to a hedge contract whose status is "
                    f"{contract.status.value} — only active or "
                    f"partially_settled hedges accept new linkages"
                ),
            )

        if canonical_commodity(order.commodity) != canonical_commodity(
            contract.commodity
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order commodity must match hedge contract commodity",
            )

        # ── Direction validation (J-A1-OPUS-03) ───────────────────────────
        _validate_linkage_direction(order, contract)

        # ── Capacity checks (existing, preserved) ─────────────────────────
        order_linked_qty = (
            session.query(func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0))
            .filter(HedgeOrderLinkage.order_id == order_id)
            .scalar()
        )
        contract_linked_qty = (
            session.query(func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0))
            .filter(HedgeOrderLinkage.contract_id == contract_id)
            .scalar()
        )

        linked_order_total = quantize_mt(order_linked_qty)
        linked_contract_total = quantize_mt(contract_linked_qty)
        requested_qty = quantize_mt(quantity_mt)
        order_qty = quantize_mt(order.quantity_mt)
        contract_qty = quantize_mt(contract.quantity_mt)

        if quantize_mt(linked_order_total + requested_qty) > order_qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Linkage exceeds order quantity",
            )
        if quantize_mt(linked_contract_total + requested_qty) > contract_qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Linkage exceeds contract quantity",
            )

        linkage = HedgeOrderLinkage(
            order_id=order_id,
            contract_id=contract_id,
            quantity_mt=requested_qty,
        )
        session.add(linkage)
        session.flush()
        session.refresh(linkage)
        return linkage

    @staticmethod
    def list_linkages(
        session: Session,
        *,
        order_id: UUID | None = None,
        contract_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[HedgeOrderLinkage], str | None]:
        query = session.query(HedgeOrderLinkage)
        if order_id:
            query = query.filter(HedgeOrderLinkage.order_id == order_id)
        if contract_id:
            query = query.filter(HedgeOrderLinkage.contract_id == contract_id)
        return paginate(
            query,
            created_at_col=HedgeOrderLinkage.created_at,
            id_col=HedgeOrderLinkage.id,
            cursor=cursor,
            limit=limit,
        )

    @staticmethod
    def get_by_id(session: Session, linkage_id: UUID) -> HedgeOrderLinkage:
        linkage = session.get(HedgeOrderLinkage, linkage_id)
        if not linkage:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Linkage not found"
            )
        return linkage
