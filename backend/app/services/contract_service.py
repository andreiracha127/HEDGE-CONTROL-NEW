"""Contract service — business logic for HedgeContract CRUD.

Every public method receives a ``Session`` and returns domain objects or
raises ``HTTPException``.  The caller (route) is responsible for audit
marking and HTTP-response formatting.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.pagination import paginate
from app.core.precision import quantize_mt
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
    VALID_STATUS_TRANSITIONS,
)
from app.models.linkages import HedgeOrderLinkage
from app.models.orders import Order
from app.schemas.contracts import (
    HedgeContractCreate,
    HedgeContractListResponse,
    HedgeContractRead,
    HedgeContractStatusUpdate,
    HedgeContractUpdate,
    HedgeLegPriceType,
    HedgeLegSide as HedgeLegSideSchema,
)


GENERIC_STATUS_TRANSITIONS: dict[HedgeContractStatus, set[HedgeContractStatus]] = {
    HedgeContractStatus.active: {HedgeContractStatus.cancelled},
    HedgeContractStatus.partially_settled: {HedgeContractStatus.cancelled},
    HedgeContractStatus.settled: set(),
    HedgeContractStatus.cancelled: set(),
}


def _generate_reference() -> str:
    """Generate a unique HC-XXXXXXXX reference."""
    return f"HC-{_uuid.uuid4().hex[:8].upper()}"


class ContractService:
    """Stateless service for HedgeContract operations."""

    # ── Create ────────────────────────────────────────────────────────

    @staticmethod
    def create(
        session: Session,
        payload: HedgeContractCreate,
        *,
        created_by: str | None = None,
    ) -> HedgeContract:
        """Create a new hedge contract from validated payload.

        Derives classification from leg configuration:
        - fixed leg buy  → long
        - fixed leg sell → short
        """
        fixed_leg = next(
            leg for leg in payload.legs if leg.price_type == HedgeLegPriceType.fixed
        )
        variable_leg = next(
            leg for leg in payload.legs if leg.price_type == HedgeLegPriceType.variable
        )

        classification = (
            HedgeClassification.long
            if fixed_leg.side == HedgeLegSideSchema.buy
            else HedgeClassification.short
        )

        contract = HedgeContract(
            commodity=payload.commodity,
            quantity_mt=payload.quantity_mt,
            fixed_leg_side=HedgeLegSide(fixed_leg.side.value),
            variable_leg_side=HedgeLegSide(variable_leg.side.value),
            classification=classification,
            status=HedgeContractStatus.active,
            reference=_generate_reference(),
            counterparty_id=payload.counterparty_id,
            fixed_price_value=payload.fixed_price_value,
            fixed_price_unit=payload.fixed_price_unit,
            float_pricing_convention=payload.float_pricing_convention,
            premium_discount=payload.premium_discount,
            settlement_date=payload.settlement_date,
            prompt_date=payload.prompt_date,
            trade_date=payload.trade_date or datetime.now(timezone.utc).date(),
            source_type=payload.source_type or "manual",
            notes=payload.notes,
            created_by=created_by,
        )
        session.add(contract)
        session.flush()
        session.refresh(contract)
        return contract

    # ── List ──────────────────────────────────────────────────────────

    @staticmethod
    def list(
        session: Session,
        *,
        status_filter: str | None = None,
        classification: str | None = None,
        commodity: str | None = None,
        include_deleted: bool = False,
        cursor: str | None = None,
        limit: int = 50,
    ) -> HedgeContractListResponse:
        """List hedge contracts with optional filters and cursor pagination."""
        query = session.query(HedgeContract)

        if not include_deleted:
            query = query.filter(HedgeContract.deleted_at.is_(None))
        if status_filter:
            query = query.filter(
                HedgeContract.status == HedgeContractStatus(status_filter)
            )
        if classification:
            query = query.filter(
                HedgeContract.classification == HedgeClassification(classification)
            )
        if commodity:
            query = query.filter(HedgeContract.commodity == commodity)

        items, next_cursor = paginate(
            query,
            created_at_col=HedgeContract.created_at,
            id_col=HedgeContract.id,
            cursor=cursor,
            limit=limit,
        )
        return HedgeContractListResponse(
            items=[HedgeContractRead.model_validate(c) for c in items],
            next_cursor=next_cursor,
        )

    # ── Get by ID ─────────────────────────────────────────────────────

    @staticmethod
    def get_by_id(session: Session, contract_id: UUID) -> HedgeContract:
        """Fetch a single hedge contract or raise 404."""
        contract = session.get(HedgeContract, contract_id)
        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hedge contract not found",
            )
        return contract

    # ── Archive (soft-delete without cancellation) ────────────────────

    @staticmethod
    def archive(session: Session, contract_id: UUID) -> HedgeContract:
        """Soft-delete a hedge contract (set deleted_at). Raises 409 if already archived."""
        contract = session.get(HedgeContract, contract_id)
        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hedge contract not found",
            )
        if contract.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Hedge contract already archived",
            )
        contract.deleted_at = datetime.now(timezone.utc)
        session.flush()
        session.refresh(contract)
        return contract

    # ── Partial update ────────────────────────────────────────────────

    @staticmethod
    def update(
        session: Session,
        contract_id: UUID,
        payload: HedgeContractUpdate,
    ) -> HedgeContract:
        """Apply partial update to a non-deleted hedge contract."""
        contract = session.get(HedgeContract, contract_id)
        if not contract or contract.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hedge contract not found",
            )
        update_data = payload.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update",
            )

        # ── Service-side defense (PR-4 / J-A1-03) ─────────────────────────
        # Lowering ``quantity_mt`` below SUM(linkages.quantity_mt) would
        # implicitly over-allocate without any linkage write occurring. The
        # DB-level invariant on PostgreSQL enforces this institutionally; we
        # check at the application layer for a clean 422 with a helpful
        # message before the trigger fires. Also covers SQLite test paths
        # where the trigger is not installed.
        #
        # PR-5 codex P2: count only linkages whose ORDER side is live
        # (Order.deleted_at IS NULL). Mirrors the §3.5 / §3.9 read-side
        # dual-filter and migration 032's trigger update — without this
        # filter the precheck rejects 422 for a quantity reduction that
        # the DB invariant (post-032) would accept.
        if "quantity_mt" in update_data and update_data["quantity_mt"] is not None:
            new_qty = quantize_mt(update_data["quantity_mt"])
            linked_total = (
                session.query(
                    func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0)
                )
                .join(Order, Order.id == HedgeOrderLinkage.order_id)
                .filter(
                    HedgeOrderLinkage.contract_id == contract_id,
                    Order.deleted_at.is_(None),
                )
                .scalar()
            )
            linked_total = quantize_mt(linked_total)
            if new_qty < linked_total:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Cannot reduce contract quantity to {new_qty} MT: "
                        f"existing linkages already allocate {linked_total} MT. "
                        "Remove or reduce linkages first."
                    ),
                )

        for field, value in update_data.items():
            setattr(contract, field, value)
        session.flush()
        session.refresh(contract)
        return contract

    # ── Status transition ─────────────────────────────────────────────

    @staticmethod
    def transition_status(
        session: Session,
        contract_id: UUID,
        payload: HedgeContractStatusUpdate,
    ) -> HedgeContract:
        """Validate and apply a status transition."""
        contract = session.get(HedgeContract, contract_id)
        if not contract or contract.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hedge contract not found",
            )

        try:
            target = HedgeContractStatus(payload.status)
        except ValueError:
            # Pydantic already validates the enum, but keep as safety net
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status: {payload.status}",
            )

        if target in {
            HedgeContractStatus.settled,
            HedgeContractStatus.partially_settled,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Settlement transitions must go through POST "
                    "/cashflow/contracts/{contract_id}/settle"
                ),
            )

        allowed = GENERIC_STATUS_TRANSITIONS.get(contract.status, set())
        if target not in allowed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Transition from {contract.status.value} to "
                    f"{target.value} is not allowed"
                ),
            )

        contract.status = target
        session.flush()
        session.refresh(contract)
        return contract

    # ── Delete (soft-delete + cancel) ─────────────────────────────────

    @staticmethod
    def delete(session: Session, contract_id: UUID) -> HedgeContract:
        """Cancel and soft-delete a hedge contract."""
        contract = session.get(HedgeContract, contract_id)
        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hedge contract not found",
            )
        if contract.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Hedge contract already deleted",
            )
        contract.status = HedgeContractStatus.cancelled
        contract.deleted_at = datetime.now(timezone.utc)
        session.flush()
        session.refresh(contract)
        return contract
