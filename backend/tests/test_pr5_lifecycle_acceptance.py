"""PR-5 §6 acceptance tests for J-A1-OPUS-02 — snapshot lifecycle filters.

Covers §6.1 (Order lifecycle), §6.2 (HedgeContract lifecycle), §6.3
([BEHAVIOR_SHIFT] linkage from dead hedge), §6.3.5 ([BEHAVIOR_SHIFT]
linkage from soft-deleted order, §3.5 dual-filter), §6.3.6
(_get_linked_qty_map dual-filter parity, §3.9), §6.4 (multi-commodity
isolation post-#16), §6.5 (no false 409 on dead orders), §6.6 (reconcile
filter + retirement sweep, §3.7 + §3.8). §6.3.7 lives in
test_compute_net_exposure.py. Each fixture carries the §2.5 / §2.1
formula derivation as a comment next to the expected output.
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
from app.models.exposure import Exposure
from app.models.linkages import HedgeOrderLinkage
from app.models.orders import Order, OrderType, PriceType
from app.services.exposure_engine import ExposureEngineService
from app.services.exposure_service import ExposureService


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _seed_so(session, qty: Decimal, commodity: str = "ALUMINUM",
             price_type: PriceType = PriceType.variable) -> Order:
    order = Order(
        order_type=OrderType.sales,
        price_type=price_type,
        commodity=commodity,
        quantity_mt=qty,
    )
    session.add(order)
    session.flush()
    return order


def _seed_po(session, qty: Decimal, commodity: str = "ALUMINUM") -> Order:
    order = Order(
        order_type=OrderType.purchase,
        price_type=PriceType.variable,
        commodity=commodity,
        quantity_mt=qty,
    )
    session.add(order)
    session.flush()
    return order


def _seed_hedge(
    session,
    qty: Decimal,
    classification: HedgeClassification = HedgeClassification.short,
    commodity: str = "ALUMINUM",
    status: HedgeContractStatus = HedgeContractStatus.active,
) -> HedgeContract:
    if classification == HedgeClassification.short:
        fixed_side, var_side = HedgeLegSide.sell, HedgeLegSide.buy
    else:
        fixed_side, var_side = HedgeLegSide.buy, HedgeLegSide.sell
    contract = HedgeContract(
        commodity=commodity,
        classification=classification,
        quantity_mt=qty,
        status=status,
        fixed_leg_side=fixed_side,
        variable_leg_side=var_side,
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


def _row_for(rows: list[dict], commodity: str) -> dict | None:
    return next((r for r in rows if r["commodity"] == commodity), None)


# ======================================================================
# §6.1 — Order lifecycle exclusion
# ======================================================================


class TestOrderLifecycleExclusion:
    def test_soft_deleted_so_excluded_from_commercial(self, session):
        """Per §2.5: Commercial Active Aluminum
        = sum of variable-price SO where deleted_at IS NULL = 0
        """
        so = _seed_so(session, Decimal("100.000"))
        so.deleted_at = datetime.now(timezone.utc)
        session.flush()

        commercial = ExposureService.compute_commercial_snapshot(session)
        aluminum = _row_for(commercial, "ALUMINUM")
        assert aluminum is None or aluminum["commercial_active_mt"] == Decimal("0.000")

    def test_soft_deleted_so_excluded_from_global(self, session):
        """Per §2.5: Global Active Aluminum
        = Commercial Active + Hedge Short live = 0 + 0 = 0
        """
        so = _seed_so(session, Decimal("100.000"))
        so.deleted_at = datetime.now(timezone.utc)
        session.flush()

        global_rows = ExposureService.compute_global_snapshot(session)
        aluminum = _row_for(global_rows, "ALUMINUM")
        assert aluminum is None or aluminum["global_active_mt"] == Decimal("0.000")

    def test_mixed_live_and_deleted_so_only_live_counts(self, session):
        """Per §2.5: 100 + 0 (dead) = 100"""
        so_live = _seed_so(session, Decimal("100.000"))
        so_dead = _seed_so(session, Decimal("50.000"))
        so_dead.deleted_at = datetime.now(timezone.utc)
        session.flush()

        commercial = ExposureService.compute_commercial_snapshot(session)
        aluminum = _row_for(commercial, "ALUMINUM")
        assert aluminum is not None
        assert aluminum["commercial_active_mt"] == Decimal("100.000")

    def test_soft_deleted_po_excluded_from_global_passive(self, session):
        """Deleted PO does not inflate passive."""
        po = _seed_po(session, Decimal("80.000"))
        po.deleted_at = datetime.now(timezone.utc)
        session.flush()

        global_rows = ExposureService.compute_global_snapshot(session)
        aluminum = _row_for(global_rows, "ALUMINUM")
        assert aluminum is None or aluminum["global_passive_mt"] == Decimal("0.000")


# ======================================================================
# §6.2 — HedgeContract lifecycle exclusion
# ======================================================================


class TestHedgeContractLifecycleExclusion:
    def test_active_hedge_contributes(self, session):
        """Per §2.5: Global Active Aluminum
        = Commercial Active + Hedge Short live = 0 + 100 = 100
        """
        _seed_hedge(session, Decimal("100.000"))
        global_rows = ExposureService.compute_global_snapshot(session)
        aluminum = _row_for(global_rows, "ALUMINUM")
        assert aluminum is not None
        assert aluminum["hedge_short_mt"] == Decimal("100.000")
        assert aluminum["global_active_mt"] == Decimal("100.000")

    def test_partially_settled_hedge_still_contributes(self, session):
        """Partial settlement leaves open exposure — contributes 100."""
        _seed_hedge(
            session,
            Decimal("100.000"),
            status=HedgeContractStatus.partially_settled,
        )
        global_rows = ExposureService.compute_global_snapshot(session)
        aluminum = _row_for(global_rows, "ALUMINUM")
        assert aluminum is not None
        assert aluminum["hedge_short_mt"] == Decimal("100.000")

    def test_settled_hedge_contributes_zero(self, session):
        """Per §2.5: Hedge Short live = 0 (settled is not live)"""
        _seed_hedge(session, Decimal("100.000"), status=HedgeContractStatus.settled)
        global_rows = ExposureService.compute_global_snapshot(session)
        aluminum = _row_for(global_rows, "ALUMINUM")
        assert aluminum is None or aluminum["hedge_short_mt"] == Decimal("0.000")

    def test_cancelled_hedge_contributes_zero(self, session):
        _seed_hedge(session, Decimal("100.000"), status=HedgeContractStatus.cancelled)
        global_rows = ExposureService.compute_global_snapshot(session)
        aluminum = _row_for(global_rows, "ALUMINUM")
        assert aluminum is None or aluminum["hedge_short_mt"] == Decimal("0.000")

    def test_active_but_soft_deleted_hedge_contributes_zero(self, session):
        """deleted_at overrides status — deleted means dead."""
        hedge = _seed_hedge(session, Decimal("100.000"))
        hedge.deleted_at = datetime.now(timezone.utc)
        session.flush()

        global_rows = ExposureService.compute_global_snapshot(session)
        aluminum = _row_for(global_rows, "ALUMINUM")
        assert aluminum is None or aluminum["hedge_short_mt"] == Decimal("0.000")


# ======================================================================
# §6.3 — Linkage from dead hedge does not reduce commercial
# (BEHAVIOR_SHIFT, documented in PR)
# ======================================================================


class TestBehaviorShiftLinkageFromDeadHedge:
    def test_settling_hedge_restores_commercial_residual(self, session):
        """[BEHAVIOR_SHIFT]: settling a hedge linked to a SO causes that
        commodity's commercial exposure to increase — correct, the order
        is no longer hedged.

        Pre-fix:  commercial Aluminum.active = 0 always.
        Post-fix:
          Initial (active hedge):  100 - 100 = 0
          After settle:            100 - 0   = 100  (linkage no longer reduces)
        """
        so = _seed_so(session, Decimal("100.000"))
        hedge = _seed_hedge(session, Decimal("100.000"))
        _link(session, so, hedge, Decimal("100.000"))

        commercial_before = ExposureService.compute_commercial_snapshot(session)
        aluminum_before = _row_for(commercial_before, "ALUMINUM")
        assert aluminum_before["commercial_active_mt"] == Decimal("0.000")

        hedge.status = HedgeContractStatus.settled
        session.flush()

        commercial_after = ExposureService.compute_commercial_snapshot(session)
        aluminum_after = _row_for(commercial_after, "ALUMINUM")
        assert aluminum_after["commercial_active_mt"] == Decimal("100.000")

    def test_soft_deleting_hedge_restores_commercial_residual(self, session):
        """Same outcome as settle — deleted_at means dead."""
        so = _seed_so(session, Decimal("100.000"))
        hedge = _seed_hedge(session, Decimal("100.000"))
        _link(session, so, hedge, Decimal("100.000"))

        hedge.deleted_at = datetime.now(timezone.utc)
        session.flush()

        commercial = ExposureService.compute_commercial_snapshot(session)
        aluminum = _row_for(commercial, "ALUMINUM")
        assert aluminum["commercial_active_mt"] == Decimal("100.000")


# ======================================================================
# §6.3.5 — Linkage from soft-deleted order does not reduce live hedge residual
# (P1 Codex catch — §3.5 dual filter)
# ======================================================================


class TestSection6_3_5_DualFilter:
    def test_live_hedge_with_dead_order_linkage_reappears(self, session):
        """Per §2.5: Hedge Short live unlinked
        = total_live_hedge_short - linked_to_live_orders
        After SO soft-delete: total_live_hedge_short = 100,
                              linked_to_live_orders = 0
                              (linkage's order is dead per §3.5)
        => global Aluminum.hedge_short_unlinked = 100 - 0 = 100

        Failure mode prevented: without the §3.5 dual filter, the linkage
        from the dead order still reduces residual to zero, and the
        residual-zero hedge is excluded — both the dead order AND the
        live hedge silently disappear from /exposures/global.
        """
        so = _seed_so(session, Decimal("100.000"))
        hedge = _seed_hedge(session, Decimal("100.000"))
        _link(session, so, hedge, Decimal("100.000"))

        # Initial: linkage absorbs both sides → both hedge_short and
        # commercial residual = 0.
        before = ExposureService.compute_global_snapshot(session)
        before_aluminum = _row_for(before, "ALUMINUM")
        assert before_aluminum["hedge_short_mt"] == Decimal("0.000")

        so.deleted_at = datetime.now(timezone.utc)
        session.flush()

        after = ExposureService.compute_global_snapshot(session)
        after_aluminum = _row_for(after, "ALUMINUM")
        assert after_aluminum is not None, (
            "Live hedge must reappear in /exposures/global after its only "
            "linkage's order is soft-deleted (per §3.5 dual filter)."
        )
        assert after_aluminum["hedge_short_mt"] == Decimal("100.000")
        # Per §2.5: Global Active = Commercial + Hedge Short live = 0 + 100
        assert after_aluminum["global_active_mt"] == Decimal("100.000")


# ======================================================================
# §6.3.6 — _get_linked_qty_map dual-filter parity (P1 Codex catch — §3.9)
# ======================================================================


class TestSection6_3_6_LinkedQtyMapParity:
    def test_settled_hedge_restores_open_tons(self, session):
        """Per §2.1 + §3.9 dual filter:
          open_tons = order_qty - linked_qty_from_LIVE_hedges
        After settle: linked_qty_from_LIVE_hedges = 0
          open_tons = 100 - 0 = 100
        """
        so = _seed_so(session, Decimal("100.000"))
        hedge = _seed_hedge(session, Decimal("100.000"))
        _link(session, so, hedge, Decimal("100.000"))

        ExposureEngineService.reconcile_from_orders(session)
        existing = (
            session.query(Exposure).filter(Exposure.source_id == so.id).one()
        )
        assert existing.open_tons == Decimal("0.000")  # 100 - 100 = 0

        hedge.status = HedgeContractStatus.settled
        session.flush()
        ExposureEngineService.reconcile_from_orders(session)

        live = (
            session.query(Exposure)
            .filter(
                Exposure.source_id == so.id,
                Exposure.is_deleted == False,  # noqa: E712
            )
            .one()
        )
        assert live.open_tons == Decimal("100.000")

    def test_soft_deleted_hedge_restores_open_tons(self, session):
        """Per §3.9 dual filter (deleted_at IS NULL clause):
          linked_qty_from_LIVE_hedges = 0  (hedge has deleted_at set)
          open_tons = 100 - 0 = 100
        """
        so = _seed_so(session, Decimal("100.000"))
        hedge = _seed_hedge(session, Decimal("100.000"))
        _link(session, so, hedge, Decimal("100.000"))
        ExposureEngineService.reconcile_from_orders(session)

        hedge.deleted_at = datetime.now(timezone.utc)
        session.flush()
        ExposureEngineService.reconcile_from_orders(session)

        live = (
            session.query(Exposure)
            .filter(
                Exposure.source_id == so.id,
                Exposure.is_deleted == False,  # noqa: E712
            )
            .one()
        )
        assert live.open_tons == Decimal("100.000")

    def test_soft_deleted_order_retired_not_recreated(self, session):
        """§3.8 retirement composes with §3.9 filter:
          stale_exposure.is_deleted == True
          no new Exposure row created for the dead order
        """
        so = _seed_so(session, Decimal("100.000"))
        ExposureEngineService.reconcile_from_orders(session)

        so.deleted_at = datetime.now(timezone.utc)
        session.flush()
        ExposureEngineService.reconcile_from_orders(session)
        ExposureEngineService.reconcile_from_orders(session)

        rows = session.query(Exposure).filter(Exposure.source_id == so.id).all()
        assert len(rows) == 1
        assert rows[0].is_deleted is True

    def test_caller_contract_keys_are_str(self, session):
        """Per §3.9 caller-contract invariant:
          reconcile_from_orders does linked_map.get(str(order.id), Decimal("0"))
        UUID keys would 100%-miss and inflate Exposure.open_tons.
        Constitutional formula:
          open_tons = order_qty - linked_map.get(str(order.id), 0)
                    = 100 - 40 = 60   (NOT 100, which would mean miss)
        """
        so = _seed_so(session, Decimal("100.000"))
        hedge = _seed_hedge(session, Decimal("100.000"))
        _link(session, so, hedge, Decimal("40.000"))

        linked_map = ExposureEngineService._get_linked_qty_map(session)
        assert all(isinstance(k, str) for k in linked_map.keys())

        ExposureEngineService.reconcile_from_orders(session)
        exposure = (
            session.query(Exposure)
            .filter(
                Exposure.source_id == so.id,
                Exposure.is_deleted == False,  # noqa: E712
            )
            .one()
        )
        assert exposure.open_tons == Decimal("60.000")  # not 100


# ======================================================================
# §6.4 — Multi-commodity isolation preserved (post-#16)
# ======================================================================


class TestMultiCommodityIsolation:
    def test_settled_copper_hedge_excluded_aluminum_unaffected(self, session):
        """Per §2.5:
          Aluminum: 100 + 80 = 180  (live hedge contributes)
          Copper:   50  + 0  = 50   (settled Cu hedge excluded)
        """
        _seed_so(session, Decimal("100.000"), commodity="ALUMINUM")
        _seed_so(session, Decimal("50.000"), commodity="COPPER")
        _seed_hedge(session, Decimal("80.000"), commodity="ALUMINUM")
        _seed_hedge(
            session,
            Decimal("30.000"),
            commodity="COPPER",
            status=HedgeContractStatus.settled,
        )

        global_rows = ExposureService.compute_global_snapshot(session)
        aluminum = _row_for(global_rows, "ALUMINUM")
        copper = _row_for(global_rows, "COPPER")

        assert aluminum is not None
        assert aluminum["global_active_mt"] == Decimal("180.000")
        assert copper is not None
        assert copper["global_active_mt"] == Decimal("50.000")


# ======================================================================
# §6.5 — No false 409 from _validate_residuals_non_negative on dead orders
# ======================================================================


class TestNoFalse409OnDeadOrders:
    def test_soft_deleted_over_linked_so_does_not_409(self, session):
        """Soft-delete an order whose residual would be negative.
        compute_commercial_snapshot does NOT raise 409 — the dead order
        is filtered out before validation.
        """
        so = _seed_so(session, Decimal("10.000"))
        # Two live hedges so the §3.4 join survives, total linkage 12
        # against order qty 10 (would otherwise be -2 residual).
        h1 = _seed_hedge(session, Decimal("7.000"))
        h2 = _seed_hedge(session, Decimal("5.000"))
        _link(session, so, h1, Decimal("7.000"))
        _link(session, so, h2, Decimal("5.000"))

        # While order is live, validation correctly raises
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            ExposureService.compute_commercial_snapshot(session)
        assert exc.value.status_code == 409

        # Soft-delete the order — validation must skip the dead row.
        so.deleted_at = datetime.now(timezone.utc)
        session.flush()
        # Should not raise
        ExposureService.compute_commercial_snapshot(session)


# ======================================================================
# §6.6 — Reconcile filter (§3.7) + retirement sweep (§3.8 Option A)
# ======================================================================


class TestReconcileLifecycleAndRetirement:
    def test_filter_soft_deleted_order_does_not_create_exposure(self, session):
        """§3.7: soft-deleted variable-price order does NOT cause reconcile
        to create or update an Exposure row."""
        so = _seed_so(session, Decimal("100.000"))
        so.deleted_at = datetime.now(timezone.utc)
        session.flush()

        ExposureEngineService.reconcile_from_orders(session)
        assert (
            session.query(Exposure).filter(Exposure.source_id == so.id).count()
            == 0
        )

    def test_filter_live_order_still_produces_exposure(self, session):
        """§3.7: live order produces Exposure as before."""
        so = _seed_so(session, Decimal("100.000"))
        ExposureEngineService.reconcile_from_orders(session)
        assert session.query(Exposure).filter(Exposure.source_id == so.id).one()

    def test_retirement_sweep_marks_pre_existing_row_as_deleted(self, session):
        """§3.8 (P2 Codex catch): pre-existing Exposure row retired when
        its source Order is soft-deleted. Per §2.1 (Exposure is state):
        state must reflect current Order lifecycle.

        After Option A retirement:
          exposure.is_deleted == True
          exposure.deleted_at is not None
        compute_net_exposure (which filters Exposure.is_deleted.is_(False))
        no longer counts it. Per §4 / §10 invariant + §3.10 zero-residual
        skip, ALUMINUM does NOT appear as a zero-valued row.
        """
        so = _seed_so(session, Decimal("100.000"))
        ExposureEngineService.reconcile_from_orders(session)
        exposure = (
            session.query(Exposure).filter(Exposure.source_id == so.id).one()
        )
        assert exposure.is_deleted is False

        so.deleted_at = datetime.now(timezone.utc)
        session.flush()
        ExposureEngineService.reconcile_from_orders(session)

        session.refresh(exposure)
        assert exposure.is_deleted is True
        assert exposure.deleted_at is not None

        result = ExposureEngineService.compute_net_exposure(
            session, commodity="aluminum"
        )
        commodities_in_response = {row["commodity"] for row in result}
        assert "ALUMINUM" not in commodities_in_response, (
            "Retired Exposure row's commodity should NOT appear in net "
            f"exposure response after §3.8 retirement sweep. Got: {result}"
        )

    def test_retirement_is_idempotent(self, session):
        """A retired Exposure row from a soft-deleted order is NOT re-created
        or un-retired by a subsequent reconcile while the source order is
        still soft-deleted."""
        so = _seed_so(session, Decimal("100.000"))
        ExposureEngineService.reconcile_from_orders(session)
        so.deleted_at = datetime.now(timezone.utc)
        session.flush()
        ExposureEngineService.reconcile_from_orders(session)
        ExposureEngineService.reconcile_from_orders(session)

        rows = session.query(Exposure).filter(Exposure.source_id == so.id).all()
        assert len(rows) == 1
        assert rows[0].is_deleted is True

    def test_reversibility_undelete_creates_fresh_exposure(self, session):
        """§3.8 reversibility: when Order.deleted_at is cleared, the next
        reconcile creates a FRESH Exposure row. Implementation choice
        documented in §9 PR body: existing-row lookup filters
        is_deleted == False, so the retired row stays as audit history
        and a fresh live row is created on revival.
        """
        so = _seed_so(session, Decimal("100.000"))
        ExposureEngineService.reconcile_from_orders(session)
        so.deleted_at = datetime.now(timezone.utc)
        session.flush()
        ExposureEngineService.reconcile_from_orders(session)

        so.deleted_at = None
        session.flush()
        ExposureEngineService.reconcile_from_orders(session)

        rows = (
            session.query(Exposure)
            .filter(Exposure.source_id == so.id)
            .all()
        )
        assert len(rows) == 2
        retired = [r for r in rows if r.is_deleted]
        live = [r for r in rows if not r.is_deleted]
        assert len(retired) == 1
        assert len(live) == 1
        assert live[0].open_tons == Decimal("100.000")
