"""Deal Engine service — CRUD + links + P&L snapshots (component 1.5).

P&L logic
---------
Physical P&L  = SO revenue − PO cost
  * Fixed-price orders  → qty × avg_entry_price
  * Variable-price orders → qty × settlement_price (market)

Financial P&L = hedge positions linked to the deal
  All hedges use a single MTM formula (last settlement price):
      sell/short → tons × (entry_price − market_price)
      buy/long   → tons × (market_price − entry_price)
  Settled hedges are classified as **realized**, active as **MTM**.

Total P&L = physical_revenue − physical_cost + hedge_realized + hedge_mtm
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid as _uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.precision import quantize_money, quantize_mt, quantize_price, quantize_ratio
from app.models.deal import Deal, DealLink, DealLinkedType, DealPNLSnapshot, DealStatus
from app.models.contracts import HedgeContract, HedgeContractStatus, HedgeClassification
from app.models.orders import Order, OrderType, PriceType

logger = logging.getLogger(__name__)

DEFAULT_COMMODITY_SYMBOL = "LME_AL"


def _generate_reference() -> str:
    """Generate a unique deal reference like D-XXXXXXXX."""
    return f"D-{_uuid.uuid4().hex[:8].upper()}"


def _compute_inputs_hash(
    deal_id: _uuid.UUID,
    snapshot_date: date,
    link_ids: list[_uuid.UUID],
) -> str:
    """SHA-256 hash that changes when the deal's links change."""
    data = json.dumps(
        {
            "deal_id": str(deal_id),
            "snapshot_date": str(snapshot_date),
            "links": sorted(str(lid) for lid in link_ids),
        },
        sort_keys=True,
    )
    return hashlib.sha256(data.encode()).hexdigest()


def _get_market_price(
    session: Session, commodity: str, as_of_date: date
) -> Decimal | None:
    """Try to fetch the D-1 settlement price; return None on failure."""
    try:
        from app.services.price_lookup_service import (
            get_cash_settlement_price_d1,
            resolve_symbol,
        )

        symbol = resolve_symbol(commodity)
        return quantize_price(
            get_cash_settlement_price_d1(session, symbol=symbol, as_of_date=as_of_date)
        )
    except Exception:
        logger.debug(
            "market_price_unavailable commodity=%s date=%s", commodity, as_of_date
        )
        return None


class DealEngineService:
    """Stateless service for Deal operations."""

    # ------------------------------------------------------------------
    # CREATE
    # ------------------------------------------------------------------

    @staticmethod
    def create_deal(session: Session, data: dict) -> Deal:
        """Create a deal and optionally add initial links."""
        links_data = data.pop("links", [])

        deal = Deal(
            reference=_generate_reference(),
            name=data["name"],
            commodity=data["commodity"],
            status=DealStatus.open,
        )
        session.add(deal)
        session.commit()

        # Add initial links (with cross-deal uniqueness validation)
        for link_data in links_data:
            resolved_type = DealLinkedType(link_data["linked_type"])
            linked_id = link_data["linked_id"]

            # Cross-deal uniqueness: entity must not be in another deal
            cross_deal = (
                session.query(DealLink)
                .filter(
                    DealLink.linked_type == resolved_type,
                    DealLink.linked_id == linked_id,
                )
                .first()
            )
            if cross_deal:
                other_deal = session.get(Deal, cross_deal.deal_id)
                other_ref = (
                    other_deal.reference if other_deal else str(cross_deal.deal_id)
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"This {resolved_type.value} is already linked to deal "
                        f"{other_ref}. Each order/hedge may belong to only one deal."
                    ),
                )

            link = DealLink(
                deal_id=deal.id,
                linked_type=resolved_type,
                linked_id=linked_id,
            )
            session.add(link)

        session.commit()

        # Validate hedge-direction constraints after all links are created
        DealEngineService._validate_hedge_direction(session, deal)

        DealEngineService._recompute_tons(session, deal)
        session.commit()
        session.refresh(deal)
        return deal

    # ------------------------------------------------------------------
    # VALIDATION HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_hedge_direction(session: Session, deal: Deal) -> None:
        """Validate hedge-direction rules for all hedge links in a deal.

        Rules:
        - Buy / long hedges require a PO in the deal; qty ≤ PO qty.
        - Sell / short hedges require a SO in the deal; qty ≤ SO qty.
        """
        links = session.query(DealLink).filter(DealLink.deal_id == deal.id).all()

        hedge_links = [
            lk
            for lk in links
            if lk.linked_type in (DealLinkedType.hedge, DealLinkedType.contract)
        ]
        order_links = [
            lk
            for lk in links
            if lk.linked_type
            in (DealLinkedType.sales_order, DealLinkedType.purchase_order)
        ]

        if not hedge_links or not order_links:
            return  # nothing to validate

        for hl in hedge_links:
            contract = session.get(HedgeContract, hl.linked_id)
            if not contract:
                continue

            is_buy = contract.classification == HedgeClassification.long
            expected_type = (
                DealLinkedType.purchase_order if is_buy else DealLinkedType.sales_order
            )
            matching = [ol for ol in order_links if ol.linked_type == expected_type]

            if not matching:
                side_label = "PO (purchase)" if is_buy else "SO (sales)"
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"A {'buy/long' if is_buy else 'sell/short'} hedge contract "
                        f"requires a {side_label} order in the deal."
                    ),
                )

            for mol in matching:
                order = session.get(Order, mol.linked_id)
                if not order:
                    continue
                # Fixed-price orders have no price exposure — hedging is unnecessary
                if order.price_type == PriceType.fixed:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            f"Cannot hedge a fixed-price order. "
                            f"Only variable-price orders have market exposure "
                            f"and require hedging."
                        ),
                    )
                if quantize_mt(contract.quantity_mt) > quantize_mt(order.quantity_mt):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            f"Hedge quantity ({contract.quantity_mt} MT) exceeds "
                            f"order quantity ({quantize_mt(order.quantity_mt)} MT). "
                            f"Hedge must be ≤ the order it covers."
                        ),
                    )

    # ------------------------------------------------------------------
    # LINKS
    # ------------------------------------------------------------------

    @staticmethod
    def add_link(
        session: Session, deal_id: _uuid.UUID, linked_type: str, linked_id: _uuid.UUID
    ) -> DealLink:
        """Add a link to a deal.

        Business rules enforced:
        1. Same order / hedge can only appear in ONE deal (cross-deal uniqueness).
        2. Buy / long hedge contracts may only be linked alongside a PO.
        3. Sell / short hedge contracts may only be linked alongside a SO.
        4. Hedge quantity must not exceed the quantity of the order it hedges.
        """
        deal = DealEngineService.get_by_id(session, deal_id)
        if not deal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found"
            )

        resolved_type = DealLinkedType(linked_type)

        # ── Duplicate within same deal ──
        existing = (
            session.query(DealLink)
            .filter(
                DealLink.deal_id == deal_id,
                DealLink.linked_type == resolved_type,
                DealLink.linked_id == linked_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Link already exists",
            )

        # ── Cross-deal uniqueness: entity must not be in another deal ──
        cross_deal = (
            session.query(DealLink)
            .filter(
                DealLink.linked_type == resolved_type,
                DealLink.linked_id == linked_id,
                DealLink.deal_id != deal_id,
            )
            .first()
        )
        if cross_deal:
            other_deal = session.get(Deal, cross_deal.deal_id)
            other_ref = other_deal.reference if other_deal else str(cross_deal.deal_id)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"This {resolved_type.value} is already linked to deal "
                    f"{other_ref}. Each order/hedge may belong to only one deal."
                ),
            )

        # ── Hedge-direction validation ──
        if resolved_type in (DealLinkedType.hedge, DealLinkedType.contract):
            contract = session.get(HedgeContract, linked_id)
            if contract:
                # Collect existing order links in this deal
                order_links = (
                    session.query(DealLink)
                    .filter(
                        DealLink.deal_id == deal_id,
                        DealLink.linked_type.in_(
                            [
                                DealLinkedType.sales_order,
                                DealLinkedType.purchase_order,
                            ]
                        ),
                    )
                    .all()
                )

                if order_links:
                    is_buy = contract.classification == HedgeClassification.long
                    expected_type = (
                        DealLinkedType.purchase_order
                        if is_buy
                        else DealLinkedType.sales_order
                    )
                    matching_orders = [
                        ol for ol in order_links if ol.linked_type == expected_type
                    ]
                    if not matching_orders:
                        side_label = "PO (purchase)" if is_buy else "SO (sales)"
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=(
                                f"A {'buy/long' if is_buy else 'sell/short'} hedge "
                                f"contract requires a {side_label} order in the deal."
                            ),
                        )

                    # Validate price-type and quantity constraints
                    for mol in matching_orders:
                        order = session.get(Order, mol.linked_id)
                        if not order:
                            continue
                        # Fixed-price orders have no price exposure
                        if order.price_type == PriceType.fixed:
                            raise HTTPException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=(
                                    f"Cannot hedge a fixed-price order. "
                                    f"Only variable-price orders have market "
                                    f"exposure and require hedging."
                                ),
                            )
                        if quantize_mt(contract.quantity_mt) > quantize_mt(
                            order.quantity_mt
                        ):
                            raise HTTPException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=(
                                    f"Hedge quantity ({contract.quantity_mt} MT) "
                                    f"exceeds order quantity "
                                    f"({quantize_mt(order.quantity_mt)} MT). "
                                    f"Hedge must be ≤ the order it covers."
                                ),
                            )

        link = DealLink(
            deal_id=deal_id,
            linked_type=resolved_type,
            linked_id=linked_id,
        )
        session.add(link)
        session.commit()

        DealEngineService._recompute_tons(session, deal)
        session.commit()
        session.refresh(link)
        return link

    @staticmethod
    def remove_link(session: Session, deal_id: _uuid.UUID, link_id: _uuid.UUID) -> None:
        """Remove a link from a deal."""
        deal = DealEngineService.get_by_id(session, deal_id)
        if not deal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found"
            )

        link = (
            session.query(DealLink)
            .filter(DealLink.id == link_id, DealLink.deal_id == deal_id)
            .first()
        )
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Link not found"
            )

        session.delete(link)
        session.flush()

        DealEngineService._recompute_tons(session, deal)
        session.commit()

    # ------------------------------------------------------------------
    # P&L SNAPSHOT
    # ------------------------------------------------------------------

    @staticmethod
    def _order_value(
        order: Order,
        market_price: Decimal | None,
    ) -> Decimal:
        """Return the monetary value for one order (qty × effective price).

        Fixed-price orders always use ``avg_entry_price``.
        Variable-price orders prefer the market settlement price;
        fall back to ``avg_entry_price`` when market data is unavailable.
        """
        qty = quantize_mt(order.quantity_mt)
        if order.price_type == PriceType.fixed:
            return quantize_money(qty * quantize_price(order.avg_entry_price))
        if market_price is not None:
            return quantize_money(qty * quantize_price(market_price))
        return quantize_money(qty * quantize_price(order.avg_entry_price))

    @staticmethod
    def compute_deal_pnl(
        session: Session, deal_id: _uuid.UUID, snapshot_date: date
    ) -> DealPNLSnapshot:
        """Compute deal P&L and persist a snapshot.

        Idempotent: if the set of links hasn't changed for the same date the
        existing snapshot is returned.  When links change a fresh snapshot is
        created (different ``inputs_hash``).
        """
        deal = DealEngineService.get_by_id(session, deal_id)
        if not deal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found"
            )

        links = session.query(DealLink).filter(DealLink.deal_id == deal_id).all()
        inputs_hash = _compute_inputs_hash(
            deal_id, snapshot_date, [lk.id for lk in links]
        )

        existing = (
            session.query(DealPNLSnapshot)
            .filter(DealPNLSnapshot.inputs_hash == inputs_hash)
            .first()
        )
        if existing:
            return existing

        market_price = _get_market_price(session, deal.commodity, snapshot_date)

        physical_revenue = Decimal("0")
        physical_cost = Decimal("0")
        hedge_pnl_realized = Decimal("0")
        hedge_pnl_mtm = Decimal("0")

        for link in links:
            # ── Physical side (orders) ──
            if link.linked_type == DealLinkedType.sales_order:
                order = session.get(Order, link.linked_id)
                if order:
                    physical_revenue += DealEngineService._order_value(
                        order, market_price
                    )

            elif link.linked_type == DealLinkedType.purchase_order:
                order = session.get(Order, link.linked_id)
                if order:
                    physical_cost += DealEngineService._order_value(order, market_price)

            # ── Financial side (hedges / contracts) ──
            # Single MTM formula for all contracts; bucket differs
            # (settled → realized, active → unrealised).
            elif link.linked_type in (DealLinkedType.hedge, DealLinkedType.contract):
                contract = session.get(HedgeContract, link.linked_id)
                if not contract:
                    continue

                tons = quantize_mt(contract.quantity_mt)
                price = quantize_price(contract.fixed_price_value)
                is_sell = contract.classification == HedgeClassification.short

                if market_price is not None:
                    mtm = quantize_money(
                        tons * (price - market_price)
                        if is_sell
                        else tons * (market_price - price)
                    )
                else:
                    mtm = Decimal("0")

                if contract.status == HedgeContractStatus.settled:
                    hedge_pnl_realized += mtm
                else:
                    hedge_pnl_mtm += mtm

        total_pnl = quantize_money(
            physical_revenue - physical_cost + hedge_pnl_realized + hedge_pnl_mtm
        )

        snapshot = DealPNLSnapshot(
            deal_id=deal_id,
            snapshot_date=snapshot_date,
            physical_revenue=physical_revenue,
            physical_cost=physical_cost,
            hedge_pnl_realized=hedge_pnl_realized,
            hedge_pnl_mtm=hedge_pnl_mtm,
            total_pnl=total_pnl,
            inputs_hash=inputs_hash,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        return snapshot

    @staticmethod
    def get_pnl_history(session: Session, deal_id: _uuid.UUID) -> list[DealPNLSnapshot]:
        """Return P&L snapshot history for a deal."""
        deal = DealEngineService.get_by_id(session, deal_id)
        if not deal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found"
            )
        return (
            session.query(DealPNLSnapshot)
            .filter(DealPNLSnapshot.deal_id == deal_id)
            .order_by(DealPNLSnapshot.snapshot_date.desc())
            .all()
        )

    # ------------------------------------------------------------------
    # P&L BREAKDOWN (batch computation with per-item detail)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_pnl_breakdown(
        session: Session,
        deal_ids: list[_uuid.UUID],
        snapshot_date: date,
    ) -> dict:
        """Compute P&L breakdown for multiple deals with line-item detail.

        If *deal_ids* is empty every active deal is included.
        Returns a dict ready to be serialised as ``PnlBreakdownResponse``.
        """
        if deal_ids:
            deals = (
                session.query(Deal)
                .filter(Deal.id.in_(deal_ids), Deal.is_deleted == False)  # noqa: E712
                .order_by(Deal.created_at.desc())
                .all()
            )
        else:
            deals = (
                session.query(Deal)
                .filter(Deal.is_deleted == False)  # noqa: E712
                .order_by(Deal.created_at.desc())
                .all()
            )

        tot_revenue = Decimal("0")
        tot_cost = Decimal("0")
        tot_hedge_real = Decimal("0")
        tot_hedge_mtm = Decimal("0")
        tot_pnl = Decimal("0")
        result_deals: list[dict] = []

        for deal in deals:
            market_price = _get_market_price(session, deal.commodity, snapshot_date)
            links = session.query(DealLink).filter(DealLink.deal_id == deal.id).all()

            physical_revenue = Decimal("0")
            physical_cost = Decimal("0")
            hedge_pnl_realized = Decimal("0")
            hedge_pnl_mtm = Decimal("0")
            physical_items: list[dict] = []
            financial_items: list[dict] = []

            for link in links:
                # ── Physical side ──
                if link.linked_type == DealLinkedType.sales_order:
                    order = session.get(Order, link.linked_id)
                    if order:
                        value = DealEngineService._order_value(order, market_price)
                        physical_revenue += value
                        physical_items.append(
                            {
                                "id": order.id,
                                "order_type": "SO",
                                "commodity": deal.commodity,
                                "quantity_mt": quantize_mt(order.quantity_mt),
                                "price": quantize_price(order.avg_entry_price),
                                "value": value,
                            }
                        )

                elif link.linked_type == DealLinkedType.purchase_order:
                    order = session.get(Order, link.linked_id)
                    if order:
                        value = DealEngineService._order_value(order, market_price)
                        physical_cost += value
                        physical_items.append(
                            {
                                "id": order.id,
                                "order_type": "PO",
                                "commodity": deal.commodity,
                                "quantity_mt": quantize_mt(order.quantity_mt),
                                "price": quantize_price(order.avg_entry_price),
                                "value": -value,
                            }
                        )

                # ── Financial side ──
                # Single MTM formula; settled → realized, active → MTM.
                elif link.linked_type in (
                    DealLinkedType.hedge,
                    DealLinkedType.contract,
                ):
                    contract = session.get(HedgeContract, link.linked_id)
                    if not contract:
                        continue

                    tons = quantize_mt(contract.quantity_mt)
                    price = quantize_price(contract.fixed_price_value)
                    is_sell = contract.classification == HedgeClassification.short

                    if market_price is not None:
                        pnl = quantize_money(
                            tons * (price - market_price)
                            if is_sell
                            else tons * (market_price - price)
                        )
                    else:
                        pnl = Decimal("0")

                    if contract.status == HedgeContractStatus.settled:
                        hedge_pnl_realized += pnl
                    else:
                        hedge_pnl_mtm += pnl

                    financial_items.append(
                        {
                            "id": contract.id,
                            "reference": getattr(contract, "reference", None)
                            or str(contract.id)[:8],
                            "classification": (
                                contract.classification.value
                                if hasattr(contract.classification, "value")
                                else str(contract.classification)
                            ),
                            "status": (
                                contract.status.value
                                if hasattr(contract.status, "value")
                                else str(contract.status)
                            ),
                            "quantity_mt": tons,
                            "entry_price": price,
                            "market_price": market_price,
                            "pnl": pnl,
                        }
                    )

            total_pnl = quantize_money(
                physical_revenue - physical_cost + hedge_pnl_realized + hedge_pnl_mtm
            )

            result_deals.append(
                {
                    "deal_id": deal.id,
                    "deal_reference": deal.reference,
                    "deal_name": deal.name,
                    "commodity": deal.commodity,
                    "physical_revenue": physical_revenue,
                    "physical_cost": physical_cost,
                    "hedge_pnl_realized": hedge_pnl_realized,
                    "hedge_pnl_mtm": hedge_pnl_mtm,
                    "total_pnl": total_pnl,
                    "physical_items": physical_items,
                    "financial_items": financial_items,
                }
            )

            tot_revenue = quantize_money(tot_revenue + physical_revenue)
            tot_cost = quantize_money(tot_cost + physical_cost)
            tot_hedge_real = quantize_money(tot_hedge_real + hedge_pnl_realized)
            tot_hedge_mtm = quantize_money(tot_hedge_mtm + hedge_pnl_mtm)
            tot_pnl = quantize_money(tot_pnl + total_pnl)

        return {
            "deals": result_deals,
            "totals": {
                "physical_revenue": tot_revenue,
                "physical_cost": tot_cost,
                "hedge_pnl_realized": tot_hedge_real,
                "hedge_pnl_mtm": tot_hedge_mtm,
                "total_pnl": tot_pnl,
            },
        }

    # ------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------

    @staticmethod
    def update_deal_status(session: Session, deal_id: _uuid.UUID) -> Deal:
        """Update deal status based on hedge_ratio."""
        deal = DealEngineService.get_by_id(session, deal_id)
        if not deal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found"
            )

        ratio = quantize_ratio(deal.hedge_ratio)
        if ratio <= Decimal("0"):
            deal.status = DealStatus.open
        elif ratio < Decimal("1.00"):
            deal.status = DealStatus.partially_hedged
        else:
            deal.status = DealStatus.fully_hedged

        session.commit()
        session.refresh(deal)
        return deal

    # ------------------------------------------------------------------
    # LIST / GET
    # ------------------------------------------------------------------

    @staticmethod
    def list_deals(
        session: Session,
        commodity: str | None = None,
        status_filter: str | None = None,
    ):
        """Return query for deals with filters."""
        q = session.query(Deal).filter(Deal.is_deleted == False)  # noqa: E712
        if commodity:
            q = q.filter(Deal.commodity == commodity)
        if status_filter:
            q = q.filter(Deal.status == DealStatus(status_filter))
        return q.order_by(Deal.created_at.desc())

    @staticmethod
    def get_by_id(session: Session, deal_id: _uuid.UUID) -> Deal | None:
        return (
            session.query(Deal)
            .filter(Deal.id == deal_id, Deal.is_deleted == False)  # noqa: E712
            .first()
        )

    @staticmethod
    def get_detail(session: Session, deal_id: _uuid.UUID) -> dict:
        """Get deal with links and latest PNL snapshot."""
        deal = DealEngineService.get_by_id(session, deal_id)
        if not deal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found"
            )

        links = session.query(DealLink).filter(DealLink.deal_id == deal_id).all()
        latest_pnl = (
            session.query(DealPNLSnapshot)
            .filter(DealPNLSnapshot.deal_id == deal_id)
            .order_by(DealPNLSnapshot.created_at.desc())
            .first()
        )

        return {
            "id": deal.id,
            "reference": deal.reference,
            "name": deal.name,
            "commodity": deal.commodity,
            "status": deal.status,
            "total_physical_tons": deal.total_physical_tons,
            "total_hedge_tons": deal.total_hedge_tons,
            "hedge_ratio": deal.hedge_ratio,
            "created_at": deal.created_at,
            "updated_at": deal.updated_at,
            "is_deleted": deal.is_deleted,
            "links": links,
            "latest_pnl": latest_pnl,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _recompute_tons(session: Session, deal: Deal) -> None:
        """Recompute physical/hedge tons and ratio from links."""
        links = session.query(DealLink).filter(DealLink.deal_id == deal.id).all()

        physical_tons = Decimal("0")
        hedge_tons = Decimal("0")

        for link in links:
            if link.linked_type in (
                DealLinkedType.sales_order,
                DealLinkedType.purchase_order,
            ):
                order = session.query(Order).filter(Order.id == link.linked_id).first()
                if order:
                    physical_tons = quantize_mt(
                        physical_tons + quantize_mt(order.quantity_mt)
                    )
            elif link.linked_type in (DealLinkedType.hedge, DealLinkedType.contract):
                contract = (
                    session.query(HedgeContract)
                    .filter(HedgeContract.id == link.linked_id)
                    .first()
                )
                if contract:
                    hedge_tons = quantize_mt(
                        hedge_tons + quantize_mt(contract.quantity_mt)
                    )

        deal.total_physical_tons = quantize_mt(physical_tons)
        deal.total_hedge_tons = quantize_mt(hedge_tons)
        deal.hedge_ratio = (
            quantize_ratio(hedge_tons / physical_tons)
            if physical_tons > Decimal("0")
            else Decimal("0.00")
        )

        # Auto-update status
        ratio = deal.hedge_ratio
        if ratio <= Decimal("0"):
            deal.status = DealStatus.open
        elif ratio < Decimal("1.00"):
            deal.status = DealStatus.partially_hedged
        else:
            deal.status = DealStatus.fully_hedged
