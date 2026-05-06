"""Shared linkage creation logic used by both linkages route and RFQ award."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.pagination import paginate
from app.core.precision import quantize_mt
from app.models.contracts import HedgeContract
from app.models.linkages import HedgeOrderLinkage
from app.models.orders import Order
from app.services.price_lookup_service import canonical_commodity


class LinkageService:
    """Validates overflow constraints and persists a new HedgeOrderLinkage."""

    @staticmethod
    def create(
        session: Session,
        order_id: UUID,
        contract_id: UUID,
        quantity_mt: Decimal,
    ) -> HedgeOrderLinkage:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )

        contract = session.get(HedgeContract, contract_id)
        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hedge contract not found",
            )
        if canonical_commodity(order.commodity) != canonical_commodity(
            contract.commodity
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order commodity must match hedge contract commodity",
            )

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
