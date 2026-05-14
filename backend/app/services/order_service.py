"""OrderService – business logic for sales / purchase orders and SO↔PO links.

Extracted from ``app.api.routes.orders`` (A.2) so the route layer stays thin.
Follows the same ``@staticmethod`` + ``session: Session`` convention used by
``ContractService`` and ``DealEngineService``.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.pagination import paginate
from app.core.precision import quantize_price
from app.models.deal import DealLinkedType
from app.models.orders import (
    Order,
    OrderPricingConvention,
    OrderType,
    PriceType,
    SoPoLink,
)
from app.services.deal_engine import DealEngineService
from app.schemas.orders import (
    OrderListResponse,
    OrderRead,
    PurchaseOrderCreate,
    SalesOrderCreate,
    SoPoLinkCreate,
    SoPoLinkListResponse,
    SoPoLinkRead,
)


class OrderService:
    """Pure-logic layer for the ``/orders`` domain."""

    # ------------------------------------------------------------------
    # Order CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def create_sales_order(
        session: Session,
        payload: SalesOrderCreate,
        *,
        commit: bool = True,
    ) -> Order:
        """Create a Sales Order (SO)."""
        return OrderService._create_order(
            session, payload, OrderType.sales, commit=commit
        )

    @staticmethod
    def create_purchase_order(
        session: Session,
        payload: PurchaseOrderCreate,
        *,
        commit: bool = True,
    ) -> Order:
        """Create a Purchase Order (PO)."""
        return OrderService._create_order(
            session, payload, OrderType.purchase, commit=commit
        )

    @staticmethod
    def list_orders(
        session: Session,
        *,
        order_type: str | None = None,
        price_type: str | None = None,
        include_deleted: bool = False,
        cursor: str | None = None,
        limit: int = 50,
    ) -> OrderListResponse:
        """Return a cursor-paginated list of orders."""
        query = session.query(Order)
        if not include_deleted:
            query = query.filter(Order.deleted_at.is_(None))
        if order_type:
            query = query.filter(Order.order_type == OrderType(order_type))
        if price_type:
            query = query.filter(Order.price_type == PriceType(price_type))
        items, next_cursor = paginate(
            query,
            created_at_col=Order.created_at,
            id_col=Order.id,
            cursor=cursor,
            limit=limit,
        )
        return OrderListResponse(
            items=[OrderRead.model_validate(o) for o in items],
            next_cursor=next_cursor,
        )

    @staticmethod
    def get_by_id(session: Session, order_id: UUID) -> Order:
        """Fetch a single order or raise 404."""
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )
        return order

    @staticmethod
    def archive(session: Session, order_id: UUID, *, commit: bool = True) -> Order:
        """Soft-delete (archive) an order."""
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )
        if order.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order already archived",
            )
        order.deleted_at = datetime.now(timezone.utc)
        session.flush()
        DealEngineService.validate_deals_for_linked_entity(
            session,
            (DealLinkedType.sales_order, DealLinkedType.purchase_order),
            order.id,
        )
        DealEngineService.recompute_deals_for_linked_entity(
            session,
            (DealLinkedType.sales_order, DealLinkedType.purchase_order),
            order.id,
        )
        # ``commit=False`` callers still need recomputed Deal columns flushed
        # before they refresh/read the affected deal in the same transaction.
        session.flush()
        if commit:
            session.commit()
            session.refresh(order)
        return order

    # ------------------------------------------------------------------
    # SO ↔ PO Links
    # ------------------------------------------------------------------

    @staticmethod
    def create_sopo_link(
        session: Session, payload: SoPoLinkCreate, *, commit: bool = True
    ) -> SoPoLink:
        """Create a Sales-Order ↔ Purchase-Order link."""
        so = session.get(Order, payload.sales_order_id)
        if not so or so.order_type != OrderType.sales:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid sales order",
            )
        po = session.get(Order, payload.purchase_order_id)
        if not po or po.order_type != OrderType.purchase:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid purchase order",
            )
        existing = (
            session.query(SoPoLink)
            .filter(
                SoPoLink.sales_order_id == payload.sales_order_id,
                SoPoLink.purchase_order_id == payload.purchase_order_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Link already exists",
            )
        link = SoPoLink(
            sales_order_id=payload.sales_order_id,
            purchase_order_id=payload.purchase_order_id,
            linked_tons=payload.linked_tons,
        )
        session.add(link)
        session.flush()
        if commit:
            session.commit()
            session.refresh(link)
        return link

    @staticmethod
    def list_sopo_links(
        session: Session,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> SoPoLinkListResponse:
        """Return a cursor-paginated list of SO↔PO links."""
        query = session.query(SoPoLink)
        items, next_cursor = paginate(
            query,
            created_at_col=SoPoLink.created_at,
            id_col=SoPoLink.id,
            cursor=cursor,
            limit=limit,
        )
        return SoPoLinkListResponse(
            items=[SoPoLinkRead.model_validate(link) for link in items],
            next_cursor=next_cursor,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_order(
        session: Session,
        payload: SalesOrderCreate | PurchaseOrderCreate,
        order_type: OrderType,
        *,
        commit: bool = True,
    ) -> Order:
        """Shared logic for SO / PO creation."""
        # Cross-validate pricing_convention ↔ price_type for variable orders.
        # A variable-price order may provide a pricing_convention without an
        # avg_entry_price — the price will be determined later by the market
        # convention.  However a variable order with a price but no convention
        # is invalid and rejected.
        if payload.price_type.value == PriceType.variable.value:
            has_conv = payload.pricing_convention is not None
            has_price = payload.avg_entry_price is not None
            if has_price and not has_conv:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="pricing_convention is required when avg_entry_price is set for variable orders",
                )

        order = Order(
            order_type=order_type,
            price_type=PriceType(payload.price_type.value),
            commodity=payload.commodity,
            quantity_mt=payload.quantity_mt,
            counterparty_id=payload.counterparty_id,
            counterparty_name=payload.counterparty_name,
            pricing_type=payload.pricing_type,
            delivery_terms=payload.delivery_terms,
            delivery_date_start=payload.delivery_date_start,
            delivery_date_end=payload.delivery_date_end,
            payment_terms_days=payload.payment_terms_days,
            currency=payload.currency,
            notes=payload.notes,
        )

        if payload.price_type.value == PriceType.fixed.value:
            if payload.avg_entry_price is not None:
                order.avg_entry_price = quantize_price(payload.avg_entry_price)
        else:
            # Variable pricing
            if payload.pricing_convention is not None:
                order.pricing_convention = OrderPricingConvention(
                    payload.pricing_convention.value
                )
            if payload.avg_entry_price is not None:
                order.avg_entry_price = quantize_price(payload.avg_entry_price)
            order.reference_month = payload.reference_month
            order.observation_date_start = payload.observation_date_start
            order.observation_date_end = payload.observation_date_end
            order.fixing_date = payload.fixing_date

        session.add(order)
        if commit:
            session.commit()
            session.refresh(order)
        else:
            session.flush()
        return order
