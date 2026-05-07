"""PR-5 §6.3.7 — compute_net_exposure parity with global snapshot.

Covers J-A1-OPUS-02 §3.10 (residual-subtraction rewrite of
compute_net_exposure's hedge-side aggregation): a live hedge linked to a
soft-deleted order must reappear in /exposures/net with full residual,
matching /exposures/global. Includes the partly-linked Codex case
(100 MT hedge + 40 MT live linkage → 60 MT residual contribution) AND the
zero-residual response-shape invariant (a fully-linked commodity must NOT
emit a zero-valued row) AND cross-endpoint parity with compute_global_snapshot.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.linkages import HedgeOrderLinkage
from app.models.orders import Order, OrderType, PriceType
from app.services.exposure_engine import ExposureEngineService
from app.services.exposure_service import ExposureService


def _seed_so(session, qty: Decimal, commodity: str = "ALUMINUM") -> Order:
    order = Order(
        order_type=OrderType.sales,
        price_type=PriceType.variable,
        commodity=commodity,
        quantity_mt=qty,
    )
    session.add(order)
    session.flush()
    return order


def _seed_short_hedge(
    session, qty: Decimal, commodity: str = "ALUMINUM"
) -> HedgeContract:
    contract = HedgeContract(
        commodity=commodity,
        classification=HedgeClassification.short,
        quantity_mt=qty,
        status=HedgeContractStatus.active,
        fixed_leg_side=HedgeLegSide.sell,
        variable_leg_side=HedgeLegSide.buy,
    )
    session.add(contract)
    session.flush()
    return contract


def _link(session, order: Order, contract: HedgeContract, qty: Decimal) -> None:
    session.add(
        HedgeOrderLinkage(
            order_id=order.id,
            contract_id=contract.id,
            quantity_mt=qty,
        )
    )
    session.flush()


def _commodities_in(rows: list[dict]) -> set[str]:
    return {row["commodity"] for row in rows}


def _row_for(rows: list[dict], commodity: str) -> dict:
    return next(r for r in rows if r["commodity"] == commodity)


# =====================================================================
# §6.3.7 — net-vs-global parity after order soft-delete
# =====================================================================


def test_net_exposure_after_so_soft_delete_shows_full_hedge_residual(session):
    """§6.3.7 (P1, Codex catch): live hedge linked to a soft-deleted order
    reappears in net with FULL residual (matches §3.5 / §6.3.5).

    Per §2.5 + §3.10 inner-set narrowing:
      Hedge in net = total_live_hedge - linked_to_LIVE_orders
                   = 100 - 0 = 100  (linkage's order is soft-deleted)
    Net (positive = Vendido/short):
      net_tons = (SO_open - PO_open) + global_short - global_long
               = (0 - 0) + 100 - 0 = 100
    """
    so = _seed_so(session, Decimal("100.000"))
    hedge = _seed_short_hedge(session, Decimal("100.000"))
    _link(session, so, hedge, Decimal("100.000"))

    # Soft-delete the SO.
    so.deleted_at = datetime.now(timezone.utc)
    session.flush()

    result = ExposureEngineService.compute_net_exposure(
        session, commodity="aluminum"
    )
    aluminum = _row_for(result, "ALUMINUM")
    assert aluminum["short_tons"] == Decimal("100.000")
    assert aluminum["long_tons"] == Decimal("0.000")
    assert aluminum["net_tons"] == Decimal("100.000")


def test_net_exposure_with_live_so_omits_fully_linked_hedge(session):
    """§6.3.7: live SO + live hedge + full linkage → hedge residual is 0,
    so it does NOT contribute to short_tons.

    Per §2.5 + §3.10 residual subtraction:
      linked_to_LIVE_orders = 100  (live SO linkage counted)
      residual_contract_qty = 100 - 100 = 0
      Hedge contribution to short_tons = sum(residual) = 0
    Combined with the §3.10 zero-residual continue guard, ALUMINUM does
    NOT appear in the response (no live SO open exposure either).
    """
    so = _seed_so(session, Decimal("100.000"))
    hedge = _seed_short_hedge(session, Decimal("100.000"))
    _link(session, so, hedge, Decimal("100.000"))

    result = ExposureEngineService.compute_net_exposure(session)
    # Aluminum has no commercial Exposure rows (reconcile not invoked) and
    # the hedge fully linked → residual 0 → zero-residual skip drops it.
    assert "ALUMINUM" not in _commodities_in(result)


def test_net_exposure_partly_linked_hedge_contributes_remainder(session):
    """§6.3.7 (P1, Codex catch): 100 MT hedge + 40 MT linkage to live SO
    → hedge contributes 60 MT residual (NOT 0, NOT 100).

    Per §3.10 residual subtraction (constitutional formula):
      residual_contract_qty = quantity_mt - SUM(live linkages)
                            = 100 - 40 = 60
    Hedge contribution to short_tons = sum(residual) = 60
    """
    so = _seed_so(session, Decimal("100.000"))
    hedge = _seed_short_hedge(session, Decimal("100.000"))
    _link(session, so, hedge, Decimal("40.000"))

    result = ExposureEngineService.compute_net_exposure(
        session, commodity="aluminum"
    )
    aluminum = _row_for(result, "ALUMINUM")
    assert aluminum["short_tons"] == Decimal("60.000")


def test_net_exposure_zero_residual_group_omits_commodity_row(session):
    """§6.3.7 (P2, Codex catch — response-shape invariant): a commodity
    whose only live hedge is fully linked to a live order MUST NOT appear
    as a zero-valued row.

    Asserting "aluminum" not in result is a TRAP — result is a
    list[dict], the string is never == a dict, so the assertion is
    trivially true. Build a keyed set of commodities present and assert
    against THAT.

    Per §3.10 response-shape invariant (constitutional):
      if SUM(residual) == 0 across all live <commodity> hedges
        → no <commodity> row in response (shape preserved per §4 / §10)
        NOT a zero-valued row.
    Fixture: live SO Aluminum 100 + live Hedge Short Aluminum 100 +
    linkage 100 (residual = 0). No other live Aluminum SO/PO.
    """
    so = _seed_so(session, Decimal("100.000"))
    hedge = _seed_short_hedge(session, Decimal("100.000"))
    _link(session, so, hedge, Decimal("100.000"))

    result = ExposureEngineService.compute_net_exposure(session)
    commodities_in_response = _commodities_in(result)
    assert "ALUMINUM" not in commodities_in_response, (
        "Aluminum should NOT appear in net-exposure response when its only "
        f"live hedges are fully linked to live orders. Got: {result}"
    )


def test_net_exposure_no_double_count_when_order_archived_before_reconcile(
    session,
):
    """Codex P2: when an Order is archived without an immediate reconcile,
    the §3.10 inner subquery already drops linkages from the dead order
    (so the live hedge contributes full residual). Without a matching
    read-side filter on the commercial side, the stale Exposure row
    (still is_deleted=False until next reconcile) would also be counted —
    double-counting the same physical order.

    Per Codex case (verbatim):
      100 MT order with a 40 MT hedge linkage, then archived without
      reconcile. Pre-fix: commercial open_tons = 60 + hedge residual = 100
      → reported 160 instead of 100. Post-fix: commercial side filtered
      by Order.deleted_at.is_(None), so only hedge contribution survives.

    Per §3.10 + Codex P2:
      Hedge contribution = 100 - 0 = 100  (linkage's order is dead)
      Commercial contribution = 0  (Exposure's source Order is archived)
      net_tons = (0 - 0) + 100 - 0 = 100
    """
    so = _seed_so(session, Decimal("100.000"))
    hedge = _seed_short_hedge(session, Decimal("100.000"))
    _link(session, so, hedge, Decimal("40.000"))

    # Reconcile produces a live Exposure row (open_tons = 60).
    ExposureEngineService.reconcile_from_orders(session)

    # Archive the order WITHOUT re-running reconcile — simulates the
    # window between archive_order and the next reconcile sweep.
    so.deleted_at = datetime.now(timezone.utc)
    session.flush()

    result = ExposureEngineService.compute_net_exposure(
        session, commodity="aluminum"
    )
    aluminum = _row_for(result, "ALUMINUM")
    assert aluminum is not None
    # Commercial side filtered out (stale Exposure has dead source Order).
    assert aluminum["short_original"] == Decimal("0.000")
    assert aluminum["short_hedged"] == Decimal("0.000")
    # Hedge contributes its full residual (linkage's order is dead per §3.10).
    assert aluminum["short_tons"] == Decimal("100.000")
    # Net = 100 (only the live hedge), NOT 160 (double-counted).
    assert aluminum["net_tons"] == Decimal("100.000")


def test_net_exposure_cross_endpoint_parity_with_global_snapshot(session):
    """§6.3.7 (institutional invariant): for any hedge fixture, the hedge's
    contribution to compute_net_exposure equals compute_global_snapshot's
    per-contract residual sum byte-for-byte.

    Per §3.10 invariant: net and global must agree per-contract.
    Fixture exercises a partly-linked hedge to a live SO, plus a fully-
    linked hedge to a soft-deleted SO (which §3.5 / §3.10 both restore
    to FULL residual).
    """
    so_live = _seed_so(session, Decimal("100.000"))
    so_dead = _seed_so(session, Decimal("100.000"))
    hedge_a = _seed_short_hedge(session, Decimal("100.000"))
    hedge_b = _seed_short_hedge(session, Decimal("100.000"))

    _link(session, so_live, hedge_a, Decimal("40.000"))
    _link(session, so_dead, hedge_b, Decimal("100.000"))
    so_dead.deleted_at = datetime.now(timezone.utc)
    session.flush()

    # Hedge A residual = 100 - 40 = 60
    # Hedge B residual = 100 - 0 = 100  (linkage's order is dead)
    # Total ALUMINUM hedge_short residual = 160
    net_rows = ExposureEngineService.compute_net_exposure(session)
    global_rows = ExposureService.compute_global_snapshot(session)

    net_aluminum = _row_for(net_rows, "ALUMINUM")
    global_aluminum = _row_for(global_rows, "ALUMINUM")

    # Cross-endpoint parity: net.short_tons == global.hedge_short_mt
    assert net_aluminum["short_tons"] == global_aluminum["hedge_short_mt"]
    assert net_aluminum["short_tons"] == Decimal("160.000")
