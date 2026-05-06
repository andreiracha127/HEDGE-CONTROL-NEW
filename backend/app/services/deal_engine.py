"""Deal Engine service — CRUD + links + P&L snapshots (component 1.5).

P&L logic
---------
Physical P&L  = SO revenue − PO cost
  * Fixed-price orders  → qty × avg_entry_price
  * Variable-price orders → qty × settlement_price (market)

Financial P&L = hedge positions linked to the deal
  Active hedges use a single MTM formula (last settlement price):
      sell/short → tons × (entry_price − market_price)
      buy/long   → tons × (market_price − entry_price)
  Non-active hedges (settled / partially_settled / cancelled)
  contribute **zero unrealized MTM** and require NO current price
  lookup — their realized P&L is locked in at settlement and
  captured by the cashflow ledger / ``compute_pl`` path. This
  mirrors the existing ``compute_pl`` rule and is the Codex P2
  fix for PR #22 (settled hedge must not block snapshot
  creation on missing current quote).

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
    price_references: dict[str, dict[str, str]] | None,
) -> str:
    """SHA-256 hash uniquely identifying P&L compute inputs.

    Includes the full ``price_references`` mapping (one entry per
    unique commodity actually consumed; ``None`` when no market price
    was consulted). All inner values are strings (Decimal-as-str,
    ISO-date-as-str) so JSON serialization is deterministic across
    Python / library versions. ``sort_keys=True`` ensures both the
    outer commodity keys AND the inner per-entry keys are sorted —
    necessary for byte-equal hashes on logically equal inputs.

    Caller-side discipline (PR-8 §3.4.2): build the dict with strings
    BEFORE hashing and BEFORE persisting; never feed Decimals.
    """
    data = json.dumps(
        {
            "deal_id": str(deal_id),
            "snapshot_date": str(snapshot_date),
            "links": sorted(str(lid) for lid in link_ids),
            "price_references": price_references,
        },
        sort_keys=True,
    )
    return hashlib.sha256(data.encode()).hexdigest()


def _get_market_quote(session: Session, commodity: str, as_of_date: date):
    """Fetch the D-1 settlement price as a PriceQuote (provenance-aware).

    Hard-fail behavior (PR-8 J-A1-01): on no-data the
    ``PriceReferenceUnprovable`` exception propagates — callers must
    NOT swallow it. Infrastructure errors (DB / network) likewise
    propagate as 5xx; only the domain "not provable" case maps to 422
    at the route layer.

    Symbol resolution failures (unmapped commodity) raise
    ``HTTPException(400)`` from ``resolve_symbol`` and propagate too;
    ``compute_deal_pnl`` should never have been called for a deal
    whose commodity has no mapping.
    """
    from app.services.price_lookup_service import (
        get_cash_settlement_price_d1_with_provenance,
        resolve_symbol,
    )

    symbol = resolve_symbol(commodity)
    quote = get_cash_settlement_price_d1_with_provenance(
        session, symbol=symbol, as_of_date=as_of_date
    )
    return quote


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
        session.flush()

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

        session.flush()

        # Validate hedge-direction constraints after all links are created
        DealEngineService._validate_hedge_direction(session, deal)

        DealEngineService._recompute_tons(session, deal)
        session.flush()
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
        session.flush()

        DealEngineService._recompute_tons(session, deal)
        session.flush()
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
        session.flush()

    # ------------------------------------------------------------------
    # P&L SNAPSHOT
    # ------------------------------------------------------------------

    @staticmethod
    def _order_value(
        order: Order,
        market_price: Decimal | None,
    ) -> Decimal:
        """Return the monetary value for one order (qty × effective price).

        Fixed-price orders always use ``avg_entry_price`` (the contract
        price — not a fallback). Variable-price orders REQUIRE a
        proven market price; passing ``market_price=None`` for a
        variable-price order is a hard-fail (PR-8 J-A1-01) — no
        silent fallback to ``avg_entry_price``.

        Raises
        ------
        PriceReferenceUnprovable
            When ``order.price_type == PriceType.variable`` and
            ``market_price`` is None — the contract has no fixed price
            to fall back on; valuation requires market evidence.
        """
        from app.services.price_lookup_service import PriceReferenceUnprovable

        qty = quantize_mt(order.quantity_mt)
        if order.price_type == PriceType.fixed:
            return quantize_money(qty * quantize_price(order.avg_entry_price))
        if market_price is None:
            raise PriceReferenceUnprovable(
                f"variable-price order {order.id} cannot be valued: "
                f"no market price for {order.commodity} on snapshot date",
                commodity=order.commodity,
            )
        return quantize_money(qty * quantize_price(market_price))

    @staticmethod
    def compute_deal_pnl(
        session: Session, deal_id: _uuid.UUID, snapshot_date: date
    ) -> DealPNLSnapshot:
        """Compute deal P&L and persist a snapshot.

        Hard-fail policy (PR-8 J-A1-01): when a variable-price physical
        leg or an ACTIVE hedge requires a market price that cannot be
        proven (no row within the 5-day lookback), this raises
        :class:`PriceReferenceUnprovable` and persists NO snapshot —
        the unit_of_work boundary rolls back any partial work. Fixed-
        price-only deals with no active hedges persist a snapshot
        with ``price_references = NULL`` (no market price was
        consulted; NULL is the honest representation).

        Settled / partially_settled / cancelled hedges contribute
        zero unrealized MTM and require NO current price lookup
        (Codex P2 PR #22 — mirrors ``compute_pl``'s "non-active →
        unrealized=0" rule). Realized P&L from settlement is locked
        in at settlement time and recorded by the cashflow ledger /
        ``compute_pl`` path; ``compute_deal_pnl`` only re-aggregates
        what the snapshot ledger already knows for non-active hedges
        and does not synthesize a new market value.

        Idempotency (post-PR-8 only): identical
        ``(deal_id, snapshot_date, links, price_references)`` tuples
        produce the same ``inputs_hash`` and return the existing
        snapshot. A correction to ANY commodity's price changes the
        inner dict and therefore the hash, producing a new row;
        legacy (pre-PR-8) snapshots have an old-format hash and are
        intentionally not reachable by post-PR-8 lookups (per dispatch
        §3.4.3 — backfilling them would silently bind to current
        link sets and serve stale P&L).

        Idempotency under price-source repair (Codex P2 follow-up,
        re-revised — collect-then-decide / fail-closed on partial
        success): the live market lookup runs FIRST and is performed
        for EVERY commodity needing a price (collect successes and
        ``PriceReferenceUnprovable`` failures separately — never break
        the loop on the first failure). Three outcomes:

        * **All commodities priced fresh** → standard path. The freshly
          built ``price_references`` drives the hash; on a price
          correction the hash differs from the existing row's hash and
          a new row is persisted alongside the old (forensic trail
          preserved).
        * **Partial success** (some commodities priced fresh, at least
          one unprovable) → fail closed. Reusing a candidate would
          silently serve stale data for the partially-corrected
          commodities (e.g. ALU was corrected and fetched, COPPER is
          missing, the candidate's stored ALU price is now stale);
          building a fresh snapshot is impossible because the
          unprovable commodity has no value. Both options are unsafe,
          so we propagate the first ``PriceReferenceUnprovable`` (→
          422). This is the strict interpretation: even when the
          fresh value happens to equal the candidate's stored value,
          we fail closed because we cannot prove the unprovable
          commodity is consistent without a live quote.
        * **Total unavailability** (no commodity could be priced
          fresh) → repair scenario (e.g. upstream price feed wiped).
          Probe existing snapshots: each candidate's hash is recomputed
          from the current link set + its persisted
          ``price_references``, and the first match is returned. If
          none matches, the original ``PriceReferenceUnprovable``
          propagates (→ 422). The candidate fallback is honest here
          because we have ZERO fresh evidence to be stale relative to.

        Earlier variants of this algorithm broke the loop on the first
        failure and fell through to the candidate probe; that path
        discarded the partial successes and could match a candidate
        whose stored ``price_references`` contained the now-stale
        corrected commodity value, returning stale P&L silently
        (Codex P2 on PR #22). The collect-then-decide structure closes
        that gap.
        """
        from app.services.price_lookup_service import (
            PriceQuote,
            PriceReferenceUnprovable,
        )

        deal = DealEngineService.get_by_id(session, deal_id)
        if not deal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found"
            )

        links = session.query(DealLink).filter(DealLink.deal_id == deal_id).all()
        link_ids = [lk.id for lk in links]

        # ── Step 1-2: walk links once to determine which commodities
        #             actually require a market lookup (variable-price
        #             physical legs + ACTIVE hedges only). Fixed-price
        #             legs, orphan-link rows, and non-active hedges
        #             (settled / partially_settled / cancelled) do not
        #             — settled hedges contribute realized P&L locked
        #             in at settlement, not unrealized MTM, so a
        #             missing current quote MUST NOT block snapshot
        #             creation (Codex P2 PR #22; mirrors compute_pl's
        #             "non-active hedge → zero unrealized MTM" rule).
        commodities_needing_price: set[str] = set()
        # We also pre-resolve order/contract objects to avoid double
        # session.get() calls below.
        resolved_orders: dict[_uuid.UUID, Order] = {}
        resolved_contracts: dict[_uuid.UUID, HedgeContract] = {}

        for link in links:
            if link.linked_type in (
                DealLinkedType.sales_order,
                DealLinkedType.purchase_order,
            ):
                order = session.get(Order, link.linked_id)
                if order is None:
                    continue
                resolved_orders[link.id] = order
                if order.price_type == PriceType.variable:
                    commodities_needing_price.add(order.commodity)
            elif link.linked_type in (
                DealLinkedType.hedge,
                DealLinkedType.contract,
            ):
                contract = session.get(HedgeContract, link.linked_id)
                if contract is None:
                    continue
                # Cancelled hedges contribute 0 P&L and need no price.
                if contract.status == HedgeContractStatus.cancelled:
                    continue
                resolved_contracts[link.id] = contract
                # Only ACTIVE hedges require a current market quote.
                # Settled / partially_settled hedges have zero
                # unrealized MTM (their realized P&L is locked at
                # settlement and captured separately by the cashflow
                # ledger / compute_pl path); a missing current quote
                # for them must not block snapshot creation.
                if contract.status == HedgeContractStatus.active:
                    commodities_needing_price.add(contract.commodity)

        # ── Step 3-4: one lookup per unique commodity. The live
        #             lookup runs FIRST so price corrections produce a
        #             fresh hash and a new row (forensic trail).
        #             Collect successes AND unprovable failures
        #             separately — never break the loop on the first
        #             failure. The collect-then-decide structure is
        #             required to detect the partial-success case
        #             (some commodities priced fresh, at least one
        #             unprovable) which MUST fail closed; an earlier
        #             try/except-around-the-loop variant could match
        #             a candidate whose stored price_references held
        #             the now-stale corrected commodity value and
        #             return stale P&L silently (Codex P2 on PR #22).
        #
        #             ``sorted(...)`` is preserved so error reporting
        #             is deterministic across runs (the FIRST failure
        #             in commodity-name order is the one propagated).
        #             Only domain-level ``PriceReferenceUnprovable`` is
        #             collected — infrastructure errors (DB, network,
        #             unexpected) propagate immediately as 5xx, which
        #             is the existing contract.
        quotes_by_commodity: dict[str, PriceQuote] = {}
        unprovable_errors: list[tuple[str, PriceReferenceUnprovable]] = []
        for commodity in sorted(commodities_needing_price):
            try:
                quotes_by_commodity[commodity] = _get_market_quote(
                    session, commodity, snapshot_date
                )
            except PriceReferenceUnprovable as exc:
                unprovable_errors.append((commodity, exc))

        if unprovable_errors and quotes_by_commodity:
            # Partial success → fail closed. We cannot honestly serve
            # any answer: a candidate snapshot's stored
            # price_references for a fresh-and-corrected commodity is
            # stale by definition, and a fresh build is impossible
            # because at least one commodity has no value. Even when
            # the fresh value happens to equal the candidate's stored
            # value, we still fail closed — we cannot prove the
            # unprovable commodity is consistent without a live quote.
            # Propagate the first PriceReferenceUnprovable (preserves
            # original error context); the route maps it to 422.
            raise unprovable_errors[0][1]

        if unprovable_errors:
            # Total unavailability → repair scenario. ZERO fresh
            # quotes obtained, so probing existing snapshots is
            # honest: there is no fresh evidence to be stale relative
            # to. Each candidate's hash is recomputed from the current
            # link set + its persisted price_references; the first
            # match is returned. Legacy (pre-PR-8) rows have their
            # hash computed in the old format (no price_references
            # key) so candidate_hash will not equal their stored
            # inputs_hash — intentionally not reusable per §3.4.3
            # (legacy rows are sealed). If no candidate matches, the
            # original PriceReferenceUnprovable propagates (→ 422).
            #
            # Codex P2 follow-up (2026-05-06): order by ``created_at``
            # DESC (with ``id`` DESC as a millisecond-tie tiebreaker) so
            # that when a deal/date carries multiple post-PR-8
            # snapshots whose stored ``price_references`` each still
            # hash-match the current link set (e.g. a price correction
            # produced a newer row before the feed went down), we
            # always reuse the NEWEST forensic record. Without an
            # explicit ORDER BY the database is free to return rows in
            # any order and the loop could silently regress to a
            # pre-correction P&L by returning ``snap_old`` instead of
            # ``snap_new``. The DB performs the sort (predictable, no
            # in-memory reshuffle) and the loop still returns on the
            # first hash match — which is now guaranteed to be the
            # newest reusable snapshot.
            candidate_snapshots = (
                session.query(DealPNLSnapshot)
                .filter(
                    DealPNLSnapshot.deal_id == deal_id,
                    DealPNLSnapshot.snapshot_date == snapshot_date,
                )
                .order_by(
                    DealPNLSnapshot.created_at.desc(),
                    DealPNLSnapshot.id.desc(),
                )
                .all()
            )
            for candidate in candidate_snapshots:
                candidate_hash = _compute_inputs_hash(
                    deal_id,
                    snapshot_date,
                    link_ids,
                    candidate.price_references,
                )
                if candidate_hash == candidate.inputs_hash:
                    return candidate
            raise unprovable_errors[0][1]

        # ── Step 5: build the canonical price_references dict with
        #            string values BEFORE hashing and BEFORE persisting
        #            (caller-side discipline §3.4.2). NULL when nothing
        #            consumed a market price.
        if quotes_by_commodity:
            price_references: dict[str, dict[str, str]] | None = {
                commodity: {
                    "value": str(quote.value),
                    "source": quote.source,
                    "settlement_date": quote.settlement_date.isoformat(),
                }
                for commodity, quote in sorted(quotes_by_commodity.items())
            }
        else:
            price_references = None

        # Hash AFTER price_references is fully built (§3.4.2).
        inputs_hash = _compute_inputs_hash(
            deal_id,
            snapshot_date,
            link_ids,
            price_references,
        )

        # Standard hash-match lookup — preserves the global
        # "same inputs → same row" idempotency guarantee for repeated
        # POSTs that produce identical price_references (the live
        # lookup succeeded and yielded the same value as the prior
        # call, so the inputs are byte-for-byte identical).
        existing = (
            session.query(DealPNLSnapshot)
            .filter(DealPNLSnapshot.inputs_hash == inputs_hash)
            .first()
        )
        if existing:
            return existing

        # ── Step 6: compute MTMs using the per-commodity dict.
        physical_revenue = Decimal("0")
        physical_cost = Decimal("0")
        hedge_pnl_realized = Decimal("0")
        hedge_pnl_mtm = Decimal("0")

        for link in links:
            # ── Physical side (orders) ──
            if link.linked_type in (
                DealLinkedType.sales_order,
                DealLinkedType.purchase_order,
            ):
                order = resolved_orders.get(link.id)
                if order is None:
                    continue
                if order.price_type == PriceType.variable:
                    quote = quotes_by_commodity.get(order.commodity)
                    market_price = (
                        quantize_price(quote.value) if quote is not None else None
                    )
                else:
                    market_price = None  # fixed-price ignores market_price
                value = DealEngineService._order_value(order, market_price)
                if link.linked_type == DealLinkedType.sales_order:
                    physical_revenue += value
                else:
                    physical_cost += value

            # ── Financial side (hedges / contracts) ──
            # Single MTM formula; settled → realized, active → MTM.
            elif link.linked_type in (
                DealLinkedType.hedge,
                DealLinkedType.contract,
            ):
                contract = resolved_contracts.get(link.id)
                if contract is None:
                    # Cancelled or missing — neither contributes to P&L.
                    continue

                tons = quantize_mt(contract.quantity_mt)
                price = quantize_price(contract.fixed_price_value)
                is_sell = contract.classification == HedgeClassification.short

                if contract.status != HedgeContractStatus.active:
                    # Settled / partially_settled hedges: zero
                    # unrealized MTM. Realized P&L from settlement
                    # is locked in at settlement time and captured
                    # by the cashflow ledger (see compute_pl) — not
                    # recomputed here from a current market price.
                    # Mirrors the existing compute_pl semantics:
                    # ``contract.status != active → unrealized=0``.
                    mtm = Decimal("0")
                else:
                    quote = quotes_by_commodity.get(contract.commodity)
                    if quote is None:
                        # Defensive: step 3 should have raised. Re-raise
                        # here rather than fall back to Decimal("0") —
                        # never silently zero an ACTIVE hedge MTM.
                        raise PriceReferenceUnprovable(
                            f"hedge contract {contract.id} cannot be MTM-valued: "
                            f"no market price for {contract.commodity} on "
                            f"snapshot date",
                            commodity=contract.commodity,
                        )
                    market_price = quantize_price(quote.value)

                    mtm = quantize_money(
                        tons * (price - market_price)
                        if is_sell
                        else tons * (market_price - price)
                    )

                if contract.status == HedgeContractStatus.settled:
                    hedge_pnl_realized += mtm
                else:
                    hedge_pnl_mtm += mtm

        total_pnl = quantize_money(
            physical_revenue - physical_cost + hedge_pnl_realized + hedge_pnl_mtm
        )

        # ── Step 7: persist with the canonical dict.
        snapshot = DealPNLSnapshot(
            deal_id=deal_id,
            snapshot_date=snapshot_date,
            physical_revenue=physical_revenue,
            physical_cost=physical_cost,
            hedge_pnl_realized=hedge_pnl_realized,
            hedge_pnl_mtm=hedge_pnl_mtm,
            total_pnl=total_pnl,
            inputs_hash=inputs_hash,
            price_references=price_references,
        )
        session.add(snapshot)
        session.flush()
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

        from app.services.price_lookup_service import PriceQuote

        for deal in deals:
            # Per-leg market price uses the LEG's commodity, not the
            # deal-level commodity (a deal may link orders/hedges in a
            # different commodity from ``deal.commodity`` — the deal
            # model only carries a string label, not a hard constraint).
            # Mirror the per-commodity algorithm in ``compute_deal_pnl``:
            # walk links once, collect unique commodities that need a
            # market lookup, then resolve one quote per commodity. Any
            # missing price hard-fails the whole breakdown (consistent
            # with §3.3 of the dispatch — no partial-success path; the
            # endpoint maps PriceReferenceUnprovable to 422).
            links = session.query(DealLink).filter(DealLink.deal_id == deal.id).all()

            commodities_needing_price: set[str] = set()
            resolved_orders: dict[_uuid.UUID, Order] = {}
            resolved_contracts: dict[_uuid.UUID, HedgeContract] = {}
            for link in links:
                if link.linked_type in (
                    DealLinkedType.sales_order,
                    DealLinkedType.purchase_order,
                ):
                    order = session.get(Order, link.linked_id)
                    if order is None:
                        continue
                    resolved_orders[link.id] = order
                    if order.price_type == PriceType.variable:
                        commodities_needing_price.add(order.commodity)
                elif link.linked_type in (
                    DealLinkedType.hedge,
                    DealLinkedType.contract,
                ):
                    contract = session.get(HedgeContract, link.linked_id)
                    if contract is None:
                        continue
                    if contract.status == HedgeContractStatus.cancelled:
                        # Cancelled hedges contribute 0 P&L; excluded
                        # from resolved_contracts so the valuation pass
                        # below short-circuits to pnl=0.
                        continue
                    resolved_contracts[link.id] = contract
                    # Only ACTIVE hedges require a current market quote.
                    # Settled / partially_settled hedges have zero
                    # unrealized MTM (Codex P2 PR #22 — settled hedges
                    # must not be blocked by a missing current quote;
                    # mirrors compute_pl's "non-active → unrealized=0"
                    # rule).
                    if contract.status == HedgeContractStatus.active:
                        commodities_needing_price.add(contract.commodity)

            # One lookup per unique commodity; PriceReferenceUnprovable
            # propagates from any missing commodity → 422 at the route.
            quotes_by_commodity: dict[str, PriceQuote] = {}
            for commodity in sorted(commodities_needing_price):
                quotes_by_commodity[commodity] = _get_market_quote(
                    session, commodity, snapshot_date
                )

            physical_revenue = Decimal("0")
            physical_cost = Decimal("0")
            hedge_pnl_realized = Decimal("0")
            hedge_pnl_mtm = Decimal("0")
            physical_items: list[dict] = []
            financial_items: list[dict] = []

            for link in links:
                # ── Physical side ──
                if link.linked_type == DealLinkedType.sales_order:
                    order = resolved_orders.get(link.id)
                    if order:
                        if order.price_type == PriceType.variable:
                            quote = quotes_by_commodity.get(order.commodity)
                            order_market_price = (
                                quantize_price(quote.value)
                                if quote is not None
                                else None
                            )
                        else:
                            order_market_price = None
                        value = DealEngineService._order_value(
                            order, order_market_price
                        )
                        physical_revenue += value
                        physical_items.append(
                            {
                                "id": order.id,
                                "order_type": "SO",
                                "commodity": order.commodity,
                                "quantity_mt": quantize_mt(order.quantity_mt),
                                "price": quantize_price(order.avg_entry_price),
                                "value": value,
                            }
                        )

                elif link.linked_type == DealLinkedType.purchase_order:
                    order = resolved_orders.get(link.id)
                    if order:
                        if order.price_type == PriceType.variable:
                            quote = quotes_by_commodity.get(order.commodity)
                            order_market_price = (
                                quantize_price(quote.value)
                                if quote is not None
                                else None
                            )
                        else:
                            order_market_price = None
                        value = DealEngineService._order_value(
                            order, order_market_price
                        )
                        physical_cost += value
                        physical_items.append(
                            {
                                "id": order.id,
                                "order_type": "PO",
                                "commodity": order.commodity,
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

                    # Non-active hedges contribute zero unrealized
                    # MTM and require no current quote (Codex P2
                    # PR #22):
                    #   * cancelled → no P&L at all
                    #   * settled / partially_settled → realized
                    #     P&L locked in at settlement (captured by
                    #     compute_pl / cashflow ledger), zero
                    #     unrealized MTM here
                    # Only ACTIVE hedges MUST have a per-commodity
                    # market price; a missing one would have raised
                    # PriceReferenceUnprovable above.
                    if contract.status != HedgeContractStatus.active:
                        pnl = Decimal("0")
                        hedge_market_price: Decimal | None = None
                    else:
                        quote = quotes_by_commodity.get(contract.commodity)
                        if quote is None:
                            # Defensive: the per-commodity loop above
                            # should have raised. Re-raise rather than
                            # silently zero an ACTIVE hedge MTM.
                            from app.services.price_lookup_service import (
                                PriceReferenceUnprovable,
                            )

                            raise PriceReferenceUnprovable(
                                f"hedge contract {contract.id} cannot be "
                                f"MTM-valued: no market price for "
                                f"{contract.commodity} on snapshot date",
                                commodity=contract.commodity,
                            )
                        hedge_market_price = quantize_price(quote.value)
                        pnl = quantize_money(
                            tons * (price - hedge_market_price)
                            if is_sell
                            else tons * (hedge_market_price - price)
                        )

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
                            "market_price": hedge_market_price,
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

        session.flush()
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
