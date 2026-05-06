from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_any_role
from app.core.database import get_session
from app.api.dependencies.uow import unit_of_work
from app.schemas.exposure import CommercialExposureRead, GlobalExposureRead
from app.schemas.exposure_engine import (
    ExposureDetailRead,
    ExposureListResponse,
    HedgeTaskListResponse,
    HedgeTaskRead,
    NetExposureResponse,
    ReconcileResponse,
)
from app.services.exposure_engine import ExposureEngineService
from app.services.exposure_service import ExposureService

router = APIRouter()


# ------------------------------------------------------------------
# Legacy endpoints (kept for backward compatibility)
# ------------------------------------------------------------------


@router.get("/commercial", response_model=list[CommercialExposureRead])
def get_commercial_exposure(
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> list[CommercialExposureRead]:
    return ExposureService.compute_commercial_snapshot(session)


@router.get("/global", response_model=list[GlobalExposureRead])
def get_global_exposure(
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> list[GlobalExposureRead]:
    return ExposureService.compute_global_snapshot(session)


# ------------------------------------------------------------------
# New Exposure Engine endpoints (1.3)
# ------------------------------------------------------------------


@router.post("/reconcile", response_model=ReconcileResponse)
def reconcile_exposures(
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    with unit_of_work(session):
        result = ExposureEngineService.reconcile_from_orders(session)
    return result


@router.get("/net", response_model=NetExposureResponse)
def get_net_exposure(
    commodity: Optional[str] = Query(None),
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    items = ExposureEngineService.compute_net_exposure(session, commodity)
    return {"items": items}


@router.get("/tasks", response_model=HedgeTaskListResponse)
def list_hedge_tasks(
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    items, next_cursor = ExposureEngineService.list_pending_tasks(
        session, cursor=cursor, limit=limit
    )
    return {"items": items, "next_cursor": next_cursor}


@router.post("/tasks/{task_id}/execute")
def execute_hedge_task(
    task_id: UUID,
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    with unit_of_work(session):
        task = ExposureEngineService.execute_task(session, task_id)
    return HedgeTaskRead.model_validate(task)


# ------------------------------------------------------------------
# Exposure list (static path before /{id})
# ------------------------------------------------------------------


@router.get("/list", response_model=ExposureListResponse)
def list_exposures(
    commodity: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    settlement_month: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    items, next_cursor = ExposureEngineService.list_exposures(
        session,
        commodity=commodity,
        status_filter=status_filter,
        settlement_month=settlement_month,
        cursor=cursor,
        limit=limit,
    )

    # Enrich exposure items with price_type, order_type, and hedged_tons
    from app.models.orders import Order
    from app.models.linkages import HedgeOrderLinkage

    source_ids = [item.source_id for item in items]
    order_map: dict = {}
    linked_map: dict = {}

    if source_ids:
        orders = session.query(Order).filter(Order.id.in_(source_ids)).all()
        order_map = {str(o.id): o for o in orders}

        # Linked hedge quantities per order
        linkages = (
            session.query(
                HedgeOrderLinkage.order_id,
                func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0).label(
                    "linked_qty"
                ),
            )
            .filter(HedgeOrderLinkage.order_id.in_(source_ids))
            .group_by(HedgeOrderLinkage.order_id)
            .all()
        )
        linked_map = {str(l.order_id): float(l.linked_qty) for l in linkages}

    enriched = []
    for item in items:
        d = ExposureDetailRead.model_validate(item).model_dump()
        order = order_map.get(str(item.source_id))
        if order:
            d["price_type"] = order.price_type.value if order.price_type else None
            d["order_type"] = order.order_type.value if order.order_type else None
            d["counterparty_name"] = order.counterparty_name
            d["pricing_convention"] = (
                order.pricing_convention.value if order.pricing_convention else None
            )
            d["reference_month"] = order.reference_month
            d["observation_date_start"] = order.observation_date_start
            d["observation_date_end"] = order.observation_date_end
            d["fixing_date"] = order.fixing_date
            d["avg_entry_price"] = (
                float(order.avg_entry_price) if order.avg_entry_price else None
            )
            d["order_notes"] = order.notes
            d["delivery_date_start"] = order.delivery_date_start
            d["delivery_date_end"] = order.delivery_date_end
        d["hedged_tons"] = linked_map.get(str(item.source_id), 0.0)
        enriched.append(d)

    return {"items": enriched, "next_cursor": next_cursor}


@router.get("/{exposure_id}")
def get_exposure(
    exposure_id: UUID,
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from app.models.orders import Order
    from app.models.linkages import HedgeOrderLinkage
    from app.models.contracts import HedgeContract

    exp = ExposureEngineService.get_exposure(session, exposure_id)
    d = ExposureDetailRead.model_validate(exp).model_dump()

    # Enrich with order info
    order = session.query(Order).filter(Order.id == exp.source_id).first()
    if order:
        d["price_type"] = order.price_type.value if order.price_type else None
        d["order_type"] = order.order_type.value if order.order_type else None
        d["order_reference"] = order.reference if hasattr(order, "reference") else None
        d["counterparty_name"] = order.counterparty_name
        d["pricing_convention"] = (
            order.pricing_convention.value if order.pricing_convention else None
        )
        d["reference_month"] = order.reference_month
        d["observation_date_start"] = (
            str(order.observation_date_start) if order.observation_date_start else None
        )
        d["observation_date_end"] = (
            str(order.observation_date_end) if order.observation_date_end else None
        )
        d["fixing_date"] = str(order.fixing_date) if order.fixing_date else None
        d["avg_entry_price"] = (
            float(order.avg_entry_price) if order.avg_entry_price else None
        )
        d["order_notes"] = order.notes
        d["delivery_date_start"] = (
            str(order.delivery_date_start) if order.delivery_date_start else None
        )
        d["delivery_date_end"] = (
            str(order.delivery_date_end) if order.delivery_date_end else None
        )

    # Enrich with hedge linkages
    linkages = (
        session.query(HedgeOrderLinkage, HedgeContract)
        .join(HedgeContract, HedgeOrderLinkage.contract_id == HedgeContract.id)
        .filter(HedgeOrderLinkage.order_id == exp.source_id)
        .all()
    )

    total_hedged = 0.0
    linked_contracts = []
    for link, contract in linkages:
        total_hedged += float(link.quantity_mt)
        linked_contracts.append(
            {
                "linkage_id": str(link.id),
                "contract_id": str(contract.id),
                "contract_reference": contract.reference
                if hasattr(contract, "reference")
                else None,
                "quantity_mt": float(link.quantity_mt),
                "commodity": contract.commodity
                if hasattr(contract, "commodity")
                else None,
                "classification": contract.classification.value
                if hasattr(contract, "classification") and contract.classification
                else None,
            }
        )

    d["hedged_tons"] = total_hedged
    d["linked_contracts"] = linked_contracts

    return d
