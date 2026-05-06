"""Shared linkage creation logic used by both linkages route and RFQ award."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.pagination import paginate
from app.models.contracts import HedgeContract
from app.models.linkages import HedgeOrderLinkage
from app.models.orders import Order


class LinkageService:
    """Validates overflow constraints and persists a new HedgeOrderLinkage."""

    @staticmethod
    def create(
        session: Session,
        order_id: UUID,
        contract_id: UUID,
        quantity_mt: float,
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

        if float(order_linked_qty or 0.0) + quantity_mt > order.quantity_mt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Linkage exceeds order quantity",
            )
        if float(contract_linked_qty or 0.0) + quantity_mt > contract.quantity_mt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Linkage exceeds contract quantity",
            )

        linkage = HedgeOrderLinkage(
            order_id=order_id,
            contract_id=contract_id,
            quantity_mt=quantity_mt,
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
