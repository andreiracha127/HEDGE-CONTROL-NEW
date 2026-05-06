"""PR-7 — audit emission for deal/exposure economic mutations (J-A1-02).

Each mutating route in scope must persist exactly one HMAC-signed
``AuditEvent`` per successful invocation, and zero rows on failure
(rollback via ``unit_of_work``).

Coverage matrix (post-PR):

| Route                                             | entity_type           | event_type |
|---------------------------------------------------|-----------------------|------------|
| POST /deals                                        | deal                  | created    |
| POST /deals/{deal_id}/links                        | deal_link             | created    |
| DELETE /deals/{deal_id}/links/{link_id}            | deal_link             | deleted    |
| POST /deals/{deal_id}/pnl-snapshot                 | deal_pnl_snapshot     | created    |
| POST /exposures/reconcile                          | exposure_reconciliation | executed |
| POST /exposures/tasks/{task_id}/execute            | hedge_task            | executed   |
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.counterparty import Counterparty
from app.models.deal import Deal, DealLink
from app.models.exposure import HedgeTask, HedgeTaskStatus
from app.models.orders import Order, OrderType, PriceType
from app.models.reconciliation_run import (
    ReconciliationRun,
    ReconciliationRunStatus,
)
from app.services.audit_trail_service import (
    AuditTrailService,
    MissingAuditSigningKey,
    _get_signing_key,
    _reset_signing_key_cache,
    verify_signature,
)


# ───────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────


def _create_counterparty(session: Session) -> uuid.UUID:
    cp = Counterparty(
        type="customer", name=f"Cpty-{uuid.uuid4().hex[:6]}", country="BRA"
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp.id


def _create_order_via_orm(
    session: Session,
    order_type: OrderType,
    qty: float = 100.0,
    price_type: PriceType = PriceType.fixed,
) -> uuid.UUID:
    order = Order(
        order_type=order_type,
        price_type=price_type,
        commodity="ALUMINUM",
        quantity_mt=qty,
        avg_entry_price=2500.0,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order.id


def _create_hedge_via_orm(
    session: Session, cp_id: uuid.UUID, classification: HedgeClassification
) -> uuid.UUID:
    is_long = classification == HedgeClassification.long
    contract = HedgeContract(
        reference=f"HC-{uuid.uuid4().hex[:8].upper()}",
        counterparty_id=str(cp_id),
        commodity="ALUMINUM",
        quantity_mt=50.0,
        fixed_price_value=2450.0,
        fixed_price_unit="USD/MT",
        fixed_leg_side=HedgeLegSide.buy if is_long else HedgeLegSide.sell,
        variable_leg_side=HedgeLegSide.sell if is_long else HedgeLegSide.buy,
        classification=classification,
        premium_discount=5.0,
        settlement_date=date(2025, 9, 30),
        trade_date=date.today(),
        status=HedgeContractStatus.active,
        source_type="manual",
    )
    session.add(contract)
    session.commit()
    session.refresh(contract)
    return contract.id


def _audit_rows(
    session: Session, *, entity_type: str, entity_id: uuid.UUID
) -> list[AuditEvent]:
    return (
        session.query(AuditEvent)
        .filter(
            AuditEvent.entity_type == entity_type,
            AuditEvent.entity_id == entity_id,
        )
        .all()
    )


def _assert_signed(event: AuditEvent) -> None:
    """Every audit row must carry a non-NULL HMAC-SHA256 signature."""
    assert event.signature is not None
    assert len(event.signature) == 32
    key = _get_signing_key()
    assert key is not None
    assert verify_signature(event.checksum, event.signature, key)


# ───────────────────────────────────────────────────────────────────────
# POST /deals
# ───────────────────────────────────────────────────────────────────────


class TestCreateDealAudit:
    def test_create_deal_emits_signed_audit(self, client, session) -> None:
        resp = client.post(
            "/deals", json={"name": "Audit Deal", "commodity": "ALUMINUM"}
        )
        assert resp.status_code == 201
        deal_id = UUID(resp.json()["id"])

        rows = _audit_rows(session, entity_type="deal", entity_id=deal_id)
        assert len(rows) == 1
        _assert_signed(rows[0])
        assert rows[0].event_type == "created"


# ───────────────────────────────────────────────────────────────────────
# POST /deals/{deal_id}/links and DELETE
# ───────────────────────────────────────────────────────────────────────


class TestDealLinksAudit:
    def _create_deal(self, client) -> UUID:
        resp = client.post(
            "/deals", json={"name": "Link Audit", "commodity": "ALUMINUM"}
        )
        assert resp.status_code == 201
        return UUID(resp.json()["id"])

    def test_add_link_emits_signed_audit(self, client, session) -> None:
        deal_id = self._create_deal(client)
        order_id = _create_order_via_orm(session, OrderType.sales)

        resp = client.post(
            f"/deals/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(order_id)},
        )
        assert resp.status_code == 201
        link_id = UUID(resp.json()["id"])

        rows = _audit_rows(session, entity_type="deal_link", entity_id=link_id)
        assert len(rows) == 1
        _assert_signed(rows[0])
        assert rows[0].event_type == "created"

    def test_remove_link_emits_signed_audit_anchored_on_path_param(
        self, client, session
    ) -> None:
        deal_id = self._create_deal(client)
        order_id = _create_order_via_orm(session, OrderType.sales)
        add = client.post(
            f"/deals/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(order_id)},
        )
        assert add.status_code == 201
        link_id = UUID(add.json()["id"])

        resp = client.delete(f"/deals/{deal_id}/links/{link_id}")
        assert resp.status_code == 204

        # Link is gone from the DB.
        assert session.get(DealLink, link_id) is None

        # Audit row exists with entity_id == link_id (anchored on path param).
        rows = _audit_rows(session, entity_type="deal_link", entity_id=link_id)
        # Two rows: one from the create, one from the delete.
        assert any(r.event_type == "deleted" for r in rows)
        deleted_row = next(r for r in rows if r.event_type == "deleted")
        _assert_signed(deleted_row)


# ───────────────────────────────────────────────────────────────────────
# POST /deals/{deal_id}/pnl-snapshot
# ───────────────────────────────────────────────────────────────────────


class TestPNLSnapshotAudit:
    def test_pnl_snapshot_emits_signed_audit(self, client, session) -> None:
        resp = client.post(
            "/deals", json={"name": "PnL Audit", "commodity": "ALUMINUM"}
        )
        deal_id = UUID(resp.json()["id"])

        snap = client.post(f"/deals/{deal_id}/pnl-snapshot")
        assert snap.status_code == 201
        snapshot_id = UUID(snap.json()["id"])

        rows = _audit_rows(
            session, entity_type="deal_pnl_snapshot", entity_id=snapshot_id
        )
        assert len(rows) == 1
        _assert_signed(rows[0])
        assert rows[0].event_type == "created"


# ───────────────────────────────────────────────────────────────────────
# POST /exposures/reconcile (anchored on ReconciliationRun.id)
# ───────────────────────────────────────────────────────────────────────


class TestReconcileAudit:
    def test_reconcile_emits_signed_audit_anchored_on_run(
        self, client, session
    ) -> None:
        resp = client.post("/exposures/reconcile")
        assert resp.status_code == 200

        # Locate the persisted run row.
        runs = session.query(ReconciliationRun).all()
        assert len(runs) == 1
        run = runs[0]
        assert run.status == ReconciliationRunStatus.succeeded

        # Audit row exists with entity_id == run.id.
        rows = _audit_rows(
            session, entity_type="exposure_reconciliation", entity_id=run.id
        )
        assert len(rows) == 1
        _assert_signed(rows[0])
        assert rows[0].event_type == "executed"


# ───────────────────────────────────────────────────────────────────────
# POST /exposures/tasks/{task_id}/execute
# ───────────────────────────────────────────────────────────────────────


class TestExecuteHedgeTaskAudit:
    def _bootstrap_pending_task(self, client, session) -> UUID:
        # Reconcile creates an exposure; create_hedge_tasks creates a
        # pending task. We invoke the service directly because there is
        # no public route that creates tasks.
        order_id = _create_order_via_orm(
            session, OrderType.sales, price_type=PriceType.variable
        )
        client.post("/exposures/reconcile")
        from app.services.exposure_engine import ExposureEngineService

        ExposureEngineService.create_hedge_tasks(session)
        session.commit()
        task = session.query(HedgeTask).filter(HedgeTask.status == HedgeTaskStatus.pending).first()
        assert task is not None
        return task.id

    def test_execute_hedge_task_emits_signed_audit(self, client, session) -> None:
        task_id = self._bootstrap_pending_task(client, session)
        resp = client.post(f"/exposures/tasks/{task_id}/execute")
        assert resp.status_code == 200

        rows = _audit_rows(session, entity_type="hedge_task", entity_id=task_id)
        assert len(rows) == 1
        _assert_signed(rows[0])
        assert rows[0].event_type == "executed"


# ───────────────────────────────────────────────────────────────────────
# Atomicity: failure-injection — service raises after mark_audit_success
# ───────────────────────────────────────────────────────────────────────


class TestFailureInjection:
    def test_audit_record_failure_rolls_back_deal(
        self, client, session, monkeypatch
    ) -> None:
        """If ``AuditTrailService.record`` raises, the entire mutation is
        rolled back: no Deal, no AuditEvent."""

        def fail_record(*args, **kwargs):
            raise RuntimeError("audit write failed")

        monkeypatch.setattr(AuditTrailService, "record", fail_record)

        resp = client.post(
            "/deals", json={"name": "Should Roll Back", "commodity": "ALUMINUM"}
        )
        assert resp.status_code == 500
        assert (
            session.query(Deal).filter(Deal.name == "Should Roll Back").count() == 0
        )
        assert (
            session.query(AuditEvent)
            .filter(AuditEvent.entity_type == "deal")
            .count()
            == 0
        )

    def test_reconcile_audit_failure_rolls_back_run(
        self, client, session, monkeypatch
    ) -> None:
        """If audit emission fails, the ``ReconciliationRun`` row is rolled
        back together with any partial Exposure mutations — no orphan
        anchor."""

        def fail_record(*args, **kwargs):
            raise RuntimeError("audit write failed")

        monkeypatch.setattr(AuditTrailService, "record", fail_record)

        resp = client.post("/exposures/reconcile")
        assert resp.status_code == 500

        # Run row is rolled back — no anchor persists.
        assert session.query(ReconciliationRun).count() == 0
        assert (
            session.query(AuditEvent)
            .filter(AuditEvent.entity_type == "exposure_reconciliation")
            .count()
            == 0
        )


# ───────────────────────────────────────────────────────────────────────
# HMAC fail-closed at route layer (Layer 1 of §3.4)
# ───────────────────────────────────────────────────────────────────────


class TestFailClosedAtRoute:
    def test_create_deal_fails_when_signing_key_missing(self, client, session) -> None:
        """With AUDIT_SIGNING_KEY unset, the audit emission raises
        ``MissingAuditSigningKey`` and the deal mutation is rolled back."""
        previous = os.environ.pop("AUDIT_SIGNING_KEY", None)
        _reset_signing_key_cache()
        try:
            resp = client.post(
                "/deals",
                json={"name": "FailClosed Deal", "commodity": "ALUMINUM"},
            )
            assert resp.status_code >= 500
            # No deal persisted.
            assert (
                session.query(Deal)
                .filter(Deal.name == "FailClosed Deal")
                .count()
                == 0
            )
            # No audit row either.
            assert (
                session.query(AuditEvent)
                .filter(AuditEvent.entity_type == "deal")
                .count()
                == 0
            )
        finally:
            if previous is not None:
                os.environ["AUDIT_SIGNING_KEY"] = previous
            else:
                os.environ["AUDIT_SIGNING_KEY"] = "test-signing-key-for-audit-hmac"
            _reset_signing_key_cache()


# ───────────────────────────────────────────────────────────────────────
# Static assertion: every in-scope route has the audit_event Depends
# ───────────────────────────────────────────────────────────────────────


class TestRouteCoverageStatic:
    """Static check that the in-scope economic mutation routes have an
    ``audit_event`` dependency wired. This guards against future PRs
    silently dropping the dependency."""

    EXPECTED = {
        ("POST", "/deals"),
        ("POST", "/deals/{deal_id}/links"),
        ("DELETE", "/deals/{deal_id}/links/{link_id}"),
        ("POST", "/deals/{deal_id}/pnl-snapshot"),
        ("POST", "/exposures/reconcile"),
        ("POST", "/exposures/tasks/{task_id}/execute"),
    }

    def test_every_in_scope_route_has_audit_event_dependency(self) -> None:
        from app.main import app

        # Build a (method, path) → endpoint map.
        for route in app.routes:
            method_path_pairs = {(m, route.path) for m in getattr(route, "methods", []) or []}
            for mp in method_path_pairs & self.EXPECTED:
                # Check that the endpoint's dependant tree mentions audit_event.
                deps = route.dependant.dependencies if hasattr(route, "dependant") else []
                source_names = []
                for dep in deps:
                    fn = dep.call
                    name = getattr(fn, "__name__", "")
                    qual = getattr(fn, "__qualname__", "")
                    source_names.append(f"{name}|{qual}")
                # The audit_event factory returns a closure whose qualname
                # contains "audit_event".
                joined = " ".join(source_names)
                assert "audit_event" in joined, (
                    f"Route {mp} missing audit_event dependency; deps={source_names}"
                )
