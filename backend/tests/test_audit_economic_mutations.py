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
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.cashflow import (
    CashFlowBaselineSnapshot,
    CashFlowLedgerEntry,
    HedgeContractSettlementEvent,
)
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.counterparty import Counterparty
from app.models.deal import Deal, DealLink
from app.models.exposure import HedgeTask, HedgeTaskStatus
from app.models.finance_pipeline import FinancePipelineRun
from app.models.market_data import CashSettlementPrice
from app.models.mtm import MTMSnapshot
from app.models.orders import Order, OrderType, PriceType, SoPoLink
from app.models.pl import PLSnapshot
from app.models.quotes import QuoteState, RFQQuote
from app.models.reconciliation_run import (
    ReconciliationRun,
    ReconciliationRunStatus,
)
from app.models.rfqs import RFQ, RFQInvitation, RFQInvitationPurpose, RFQState
from app.services import westmetall_cash_settlement
from app.services.audit_trail_service import (
    AuditTrailService,
    _get_signing_key,
    _reset_signing_key_cache,
    verify_signature,
)


@pytest.fixture(autouse=True)
def _westmetall_service_actor(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_ACTOR_SUB", "service:westmetall_ingest")


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
        order_id = _create_order_via_orm(session, OrderType.sales)
        link_resp = client.post(
            f"/deals/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(order_id)},
        )
        assert link_resp.status_code == 201

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


class TestA5RouteWorkerCoverage:
    def test_counterparty_create_update_delete_emit_signed_audit(
        self, client, session
    ) -> None:
        created = client.post(
            "/counterparties",
            json={"type": "broker", "name": "A5 CP", "country": "BRA"},
        )
        assert created.status_code == 201, created.text
        cp_id = UUID(created.json()["id"])

        updated = client.patch(f"/counterparties/{cp_id}", json={"city": "Sao Paulo"})
        assert updated.status_code == 200, updated.text

        deleted = client.delete(f"/counterparties/{cp_id}")
        assert deleted.status_code == 200, deleted.text

        rows = _audit_rows(session, entity_type="counterparty", entity_id=cp_id)
        assert [row.event_type for row in rows] == ["created", "updated", "deleted"]
        for row in rows:
            _assert_signed(row)

    def test_counterparty_create_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        with _without_signing_key():
            resp = client.post(
                "/counterparties",
                json={"type": "broker", "name": "A5 CP Rollback", "country": "BRA"},
            )

        assert resp.status_code >= 500
        assert (
            session.query(Counterparty)
            .filter(Counterparty.name == "A5 CP Rollback")
            .count()
            == 0
        )

    def test_counterparty_update_delete_roll_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        cp_id = UUID(_create_counterparty_via_api(client, name="A5 CP Stable"))

        with _without_signing_key():
            update = client.patch(f"/counterparties/{cp_id}", json={"city": "Rio"})
        assert update.status_code >= 500
        session.expire_all()
        assert session.get(Counterparty, cp_id).city is None

        with _without_signing_key():
            delete = client.delete(f"/counterparties/{cp_id}")
        assert delete.status_code >= 500
        session.expire_all()
        persisted = session.get(Counterparty, cp_id)
        assert persisted is not None
        assert persisted.is_deleted is False

    def test_sopo_link_create_emits_signed_audit_and_rolls_back_on_audit_failure(
        self, client, session
    ) -> None:
        so = _create_variable_sales_order(client)
        po_resp = client.post(
            "/orders/purchase",
            json={"price_type": "fixed", "quantity_mt": 5.0, "avg_entry_price": 101.0},
        )
        assert po_resp.status_code == 201, po_resp.text
        po = po_resp.json()

        created = client.post(
            "/orders/links",
            json={
                "sales_order_id": so["id"],
                "purchase_order_id": po["id"],
                "linked_tons": 2.0,
            },
        )
        assert created.status_code == 201, created.text
        link_id = UUID(created.json()["id"])
        rows = _audit_rows(session, entity_type="sopo_link", entity_id=link_id)
        assert len(rows) == 1
        assert rows[0].event_type == "created"
        _assert_signed(rows[0])

        so2 = _create_variable_sales_order(client)
        po2_resp = client.post(
            "/orders/purchase",
            json={"price_type": "fixed", "quantity_mt": 5.0, "avg_entry_price": 102.0},
        )
        assert po2_resp.status_code == 201, po2_resp.text
        with _without_signing_key():
            failed = client.post(
                "/orders/links",
                json={
                    "sales_order_id": so2["id"],
                    "purchase_order_id": po2_resp.json()["id"],
                    "linked_tons": 1.0,
                },
            )
        assert failed.status_code >= 500
        session.expire_all()
        assert (
            session.query(SoPoLink)
            .filter(SoPoLink.sales_order_id == UUID(so2["id"]))
            .count()
            == 0
        )

    def test_finance_pipeline_manual_run_emits_audit_and_rolls_back_on_failure(
        self, client, session
    ) -> None:
        ok = client.post("/finance/pipeline/run", json={"run_date": "2026-05-11"})
        assert ok.status_code == 201, ok.text
        run_id = UUID(ok.json()["id"])
        rows = _audit_rows(
            session, entity_type="finance_pipeline_run", entity_id=run_id
        )
        assert len(rows) == 1
        assert rows[0].event_type == "manual_run_triggered"
        _assert_signed(rows[0])

        with _without_signing_key():
            failed = client.post(
                "/finance/pipeline/run", json={"run_date": "2026-05-12"}
            )
        assert failed.status_code >= 500
        session.expire_all()
        assert (
            session.query(FinancePipelineRun)
            .filter(FinancePipelineRun.run_date == date(2026, 5, 12))
            .count()
            == 0
        )

    def test_finance_pipeline_pl_snapshot_rolls_back_when_audit_fails(
        self, client, session, monkeypatch
    ) -> None:
        from app.schemas.pl import PLResultResponse

        _insert_price(session, settlement_date=date(2026, 5, 12), price_usd="110")
        _create_hedge_contract_via_api(client)

        def fake_compute_pl(*args, **kwargs):
            _ = args, kwargs
            return PLResultResponse(realized_pl=Decimal("0"), unrealized_mtm=Decimal("1"))

        monkeypatch.setattr(
            "app.services.pl_snapshot_service.compute_pl",
            fake_compute_pl,
        )

        with _without_signing_key():
            failed = client.post(
                "/finance/pipeline/run", json={"run_date": "2026-05-12"}
            )

        assert failed.status_code >= 500
        session.expire_all()
        assert (
            session.query(FinancePipelineRun)
            .filter(FinancePipelineRun.run_date == date(2026, 5, 12))
            .count()
            == 0
        )
        assert session.query(PLSnapshot).count() == 0

    def test_westmetall_single_and_bulk_emit_signed_audit_metadata(
        self, client, session, monkeypatch
    ) -> None:
        _mock_westmetall_html(monkeypatch, [("30.01.2026", "2,567.50")])
        single = client.post(
            "/market-data/westmetall/aluminum/cash-settlement/ingest",
            json={"settlement_date": "2026-01-30"},
        )
        assert single.status_code == 200, single.text
        single_price = (
            session.query(CashSettlementPrice)
            .filter(CashSettlementPrice.settlement_date == date(2026, 1, 30))
            .one()
        )
        single_rows = _audit_rows(
            session, entity_type="cash_settlement_price", entity_id=single_price.id
        )
        assert len(single_rows) == 1
        assert single_rows[0].event_type == "market_data_ingested"
        _assert_signed(single_rows[0])

        _mock_westmetall_html(
            monkeypatch,
            [("02.02.2026", "2,600.00"), ("03.02.2026", "2,610.00")],
        )
        bulk = client.post(
            "/market-data/westmetall/aluminum/cash-settlement/ingest-bulk",
            json={"start_date": "2026-02-02", "end_date": "2026-02-03"},
        )
        assert bulk.status_code == 200, bulk.text
        assert bulk.json()["ingested_count"] == 2
        bulk_rows = (
            session.query(AuditEvent)
            .filter(
                AuditEvent.entity_type == "cash_settlement_price",
                AuditEvent.event_type == "market_data_ingested",
                AuditEvent.entity_id != single_price.id,
            )
            .all()
        )
        assert len(bulk_rows) == 1
        metadata = bulk_rows[0].payload["metadata"]
        assert metadata["provider"] == "westmetall"
        assert metadata["instrument"] == "LME_ALU_CASH_SETTLEMENT_DAILY"
        assert metadata["tier_at_ingest_time"] == "trusted"
        assert metadata["is_canonical"] is True
        assert metadata["replay_key"]["batch_id"] == str(bulk_rows[0].entity_id)
        _assert_signed(bulk_rows[0])

    def test_westmetall_rollback_rolls_back_and_idempotent_skip_emits_audit(
        self, client, session, monkeypatch
    ) -> None:
        _mock_westmetall_html(monkeypatch, [("30.01.2026", "2,567.50")])
        with _without_signing_key():
            failed = client.post(
                "/market-data/westmetall/aluminum/cash-settlement/ingest",
                json={"settlement_date": "2026-01-30"},
            )
        assert failed.status_code >= 500
        session.expire_all()
        assert session.query(CashSettlementPrice).count() == 0
        assert session.query(AuditEvent).count() == 0

        ok = client.post(
            "/market-data/westmetall/aluminum/cash-settlement/ingest",
            json={"settlement_date": "2026-01-30"},
        )
        assert ok.status_code == 200
        skipped = client.post(
            "/market-data/westmetall/aluminum/cash-settlement/ingest",
            json={"settlement_date": "2026-01-30"},
        )
        assert skipped.status_code == 200
        assert skipped.json()["skipped_count"] == 1
        assert session.query(AuditEvent).count() == 2


# ───────────────────────────────────────────────────────────────────────
# Static assertion: every in-scope route has the audit_event Depends
# ───────────────────────────────────────────────────────────────────────


class TestRouteCoverageStatic:
    """Every mutating route must be inventory-classified.

    Routes classified as covered institutional mutations must wire the
    route-level ``audit_event`` dependency. Behavioral tests above prove rows
    are actually emitted for the newly covered A5-2 families.
    """

    CLASSIFICATION = {
        ("POST", "/counterparties"): "covered institutional mutation",
        ("PATCH", "/counterparties/{counterparty_id}"): "covered institutional mutation",
        ("DELETE", "/counterparties/{counterparty_id}"): "covered institutional mutation",
        ("POST", "/orders/sales"): "covered institutional mutation",
        ("POST", "/orders/purchase"): "covered institutional mutation",
        ("POST", "/orders/links"): "covered institutional mutation",
        ("PATCH", "/orders/{order_id}/archive"): "covered institutional mutation",
        ("POST", "/exposures/reconcile"): "covered institutional mutation",
        ("POST", "/exposures/tasks/{task_id}/execute"): "covered institutional mutation",
        ("POST", "/deals"): "covered institutional mutation",
        ("POST", "/deals/pnl-breakdown"): "non-mutating analytical command",
        ("POST", "/deals/{deal_id}/links"): "covered institutional mutation",
        ("DELETE", "/deals/{deal_id}/links/{link_id}"): "covered institutional mutation",
        ("POST", "/deals/{deal_id}/pnl-snapshot"): "covered institutional mutation",
        ("POST", "/contracts/hedge"): "covered institutional mutation",
        ("PATCH", "/contracts/hedge/{contract_id}/archive"): "covered institutional mutation",
        ("PATCH", "/contracts/hedge/{contract_id}"): "covered institutional mutation",
        ("PATCH", "/contracts/hedge/{contract_id}/status"): "covered institutional mutation",
        ("DELETE", "/contracts/hedge/{contract_id}"): "covered institutional mutation",
        ("POST", "/linkages"): "covered institutional mutation",
        ("POST", "/rfqs"): "covered institutional mutation",
        ("POST", "/rfqs/preview-text"): "non-mutating preview command",
        ("POST", "/rfqs/{rfq_id}/quotes"): "covered institutional mutation",
        ("POST", "/rfqs/{rfq_id}/actions/reject"): "covered institutional mutation",
        ("POST", "/rfqs/{rfq_id}/actions/cancel"): "covered institutional mutation",
        ("POST", "/rfqs/{rfq_id}/actions/reject-quote"): "covered institutional mutation",
        ("POST", "/rfqs/{rfq_id}/actions/refresh-counterparty"): "covered institutional mutation",
        ("POST", "/rfqs/{rfq_id}/actions/refresh"): "covered institutional mutation",
        ("POST", "/rfqs/{rfq_id}/actions/award"): "covered institutional mutation",
        ("PATCH", "/rfqs/{rfq_id}/archive"): "covered institutional mutation",
        ("POST", "/cashflow/baseline/snapshots"): "covered institutional mutation",
        ("POST", "/cashflow/contracts/{contract_id}/settle"): "covered institutional mutation",
        ("POST", "/pl/snapshots"): "covered institutional mutation",
        ("POST", "/scenario/what-if/run"): "explicitly out of A5 mutation scope: analytical scenario",
        (
            "POST",
            "/market-data/westmetall/aluminum/cash-settlement/ingest",
        ): "covered institutional mutation",
        (
            "POST",
            "/market-data/westmetall/aluminum/cash-settlement/ingest-bulk",
        ): "covered institutional mutation",
        ("POST", "/mtm/snapshots"): "covered institutional mutation",
        ("POST", "/webhooks/whatsapp"): "explicitly out of A5 route audit scope: inbound delivery evidence",
        (
            "POST",
            "/csp/report",
        ): "explicitly out of A5 route audit scope: CSP violation reports (unauth, CSRF-exempt)",
        ("POST", "/auth/session"): "explicitly out of A5 route audit scope: auth session cookie exchange",
        ("POST", "/auth/refresh"): "explicitly out of A5 route audit scope: auth session refresh",
        ("POST", "/auth/logout"): "explicitly out of A5 route audit scope: auth session logout",
        ("POST", "/finance/pipeline/run"): "covered institutional mutation",
    }

    def test_mutating_route_inventory_is_classified_and_audited(self) -> None:
        from app.main import app

        actual = set()
        for route in app.routes:
            method_path_pairs = {(m, route.path) for m in getattr(route, "methods", []) or []}
            actual |= {
                mp
                for mp in method_path_pairs
                if mp[0] in {"POST", "PUT", "PATCH", "DELETE"}
            }

        assert actual == set(self.CLASSIFICATION), (
            "Mutating route inventory changed; classify the new route explicitly"
        )

        for route in app.routes:
            method_path_pairs = {(m, route.path) for m in getattr(route, "methods", []) or []}
            covered = {
                mp
                for mp in method_path_pairs & actual
                if self.CLASSIFICATION[mp] == "covered institutional mutation"
            }
            if not covered:
                continue
            deps = route.dependant.dependencies if hasattr(route, "dependant") else []
            source_names = []
            for dep in deps:
                fn = dep.call
                name = getattr(fn, "__name__", "")
                qual = getattr(fn, "__qualname__", "")
                source_names.append(f"{name}|{qual}")
            joined = " ".join(source_names)
            assert "audit_event" in joined, (
                f"Route {covered} missing audit_event dependency; deps={source_names}"
            )


@contextmanager
def _without_signing_key():
    previous = os.environ.pop("AUDIT_SIGNING_KEY", None)
    _reset_signing_key_cache()
    try:
        yield
    finally:
        if previous is not None:
            os.environ["AUDIT_SIGNING_KEY"] = previous
        else:
            os.environ["AUDIT_SIGNING_KEY"] = "test-signing-key-for-audit-hmac"
        _reset_signing_key_cache()


def _create_counterparty_via_api(
    client,
    *,
    name: str = "CP-A",
    phone: str = "+5511999990001",
) -> str:
    resp = client.post(
        "/counterparties",
        json={
            "type": "broker",
            "name": name,
            "country": "BRA",
            "whatsapp_phone": phone,
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _create_global_rfq(client, cp_ids: list[str]) -> dict:
    resp = client.post(
        "/rfqs",
        json={
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": "5.000",
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id} for cp_id in cp_ids],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_quote_via_api(
    client,
    *,
    rfq_id: str,
    counterparty_id: str,
    price: str = "100.000",
) -> dict:
    resp = client.post(
        f"/rfqs/{rfq_id}/quotes",
        json={
            "rfq_id": rfq_id,
            "counterparty_id": counterparty_id,
            "fixed_price_value": price,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _insert_price(
    session: Session,
    *,
    settlement_date: date,
    price_usd: Decimal | str,
    symbol: str = "LME_ALU_CASH_SETTLEMENT_DAILY",
) -> None:
    session.add(
        CashSettlementPrice(
            source="westmetall",
            symbol=symbol,
            settlement_date=settlement_date,
            price_usd=Decimal(str(price_usd)),
            source_url="https://example.test/source",
            html_sha256="0" * 64,
            fetched_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
    )
    session.commit()


def _create_variable_sales_order(client, avg_entry_price: float = 100.0) -> dict:
    response = client.post(
        "/orders/sales",
        json={
            "price_type": "variable",
            "quantity_mt": 5.0,
            "pricing_convention": "AVG",
            "avg_entry_price": avg_entry_price,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_hedge_contract_via_api(client) -> str:
    response = client.post(
        "/contracts/hedge",
        json={
            "commodity": "LME_AL",
            "quantity_mt": 12.0,
            "legs": [
                {"side": "buy", "price_type": "fixed"},
                {"side": "sell", "price_type": "variable"},
            ],
            "fixed_price_value": "100",
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _settlement_payload(source_event_id: str) -> dict:
    return {
        "source_event_id": source_event_id,
        "cashflow_date": date(2026, 1, 15).isoformat(),
        "legs": [
            {"leg_id": "FIXED", "direction": "OUT", "amount": "1200.000000"},
            {"leg_id": "FLOAT", "direction": "IN", "amount": "1320.000000"},
        ],
    }


class _FakeWestmetallResponse:
    def __init__(self, html: bytes) -> None:
        self.content = html
        self.status_code = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")


def _mock_westmetall_html(monkeypatch, rows: list[tuple[str, str]]) -> None:
    table_rows = "\n".join(
        f"<tr><td>{settlement_date}</td><td>{price}</td></tr>"
        for settlement_date, price in rows
    )
    html = (
        b"<html><body><table><tr><th>Date</th><th>Cash Settlement</th></tr>"
        + table_rows.encode("utf-8")
        + b"</table></body></html>"
    )

    def _fake_get(url: str, timeout: float):
        _ = url, timeout
        return _FakeWestmetallResponse(html)

    monkeypatch.setattr(westmetall_cash_settlement.httpx, "get", _fake_get)


class TestA5FailClosedMutationFamilies:
    def test_order_archive_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        order = _create_variable_sales_order(client)
        order_id = UUID(order["id"])

        with _without_signing_key():
            resp = client.patch(f"/orders/{order_id}/archive")

        assert resp.status_code >= 500
        session.expire_all()
        persisted = session.get(Order, order_id)
        assert persisted is not None
        assert persisted.deleted_at is None

    def test_rfq_create_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        cp_id = _create_counterparty_via_api(client)

        with _without_signing_key():
            resp = client.post(
                "/rfqs",
                json={
                    "intent": "GLOBAL_POSITION",
                    "commodity": "LME_AL",
                    "quantity_mt": "5.000",
                    "delivery_window_start": "2026-03-01",
                    "delivery_window_end": "2026-03-31",
                    "direction": "BUY",
                    "order_id": None,
                    "invitations": [{"counterparty_id": cp_id}],
                },
            )

        assert resp.status_code >= 500
        session.expire_all()
        assert session.query(RFQ).count() == 0
        assert session.query(RFQInvitation).count() == 0

    def test_rfq_quote_submit_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        cp_id = _create_counterparty_via_api(client)
        rfq = _create_global_rfq(client, [cp_id])

        with _without_signing_key():
            resp = client.post(
                f"/rfqs/{rfq['id']}/quotes",
                json={
                    "rfq_id": rfq["id"],
                    "counterparty_id": cp_id,
                    "fixed_price_value": "100.000",
                    "fixed_price_unit": "USD/MT",
                    "float_pricing_convention": "avg",
                    "received_at": datetime(
                        2026, 2, 1, tzinfo=timezone.utc
                    ).isoformat(),
                },
            )

        assert resp.status_code >= 500
        session.expire_all()
        assert session.query(RFQQuote).count() == 0
        assert session.get(RFQ, UUID(rfq["id"])).state == RFQState.sent

    def test_rfq_reject_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        cp_id = _create_counterparty_via_api(client)
        rfq = _create_global_rfq(client, [cp_id])
        _create_quote_via_api(client, rfq_id=rfq["id"], counterparty_id=cp_id)

        with _without_signing_key():
            resp = client.post(
                f"/rfqs/{rfq['id']}/actions/reject",
                json={},
            )

        assert resp.status_code >= 500
        session.expire_all()
        assert session.get(RFQ, UUID(rfq["id"])).state == RFQState.quoted

    def test_rfq_cancel_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        cp_id = _create_counterparty_via_api(client)
        rfq = _create_global_rfq(client, [cp_id])

        with _without_signing_key():
            resp = client.post(
                f"/rfqs/{rfq['id']}/actions/cancel",
                json={},
            )

        assert resp.status_code >= 500
        session.expire_all()
        assert session.get(RFQ, UUID(rfq["id"])).state == RFQState.sent

    def test_rfq_reject_quote_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        cp_id = _create_counterparty_via_api(client)
        rfq = _create_global_rfq(client, [cp_id])
        quote = _create_quote_via_api(client, rfq_id=rfq["id"], counterparty_id=cp_id)
        quote_id = UUID(quote["id"])

        with _without_signing_key():
            resp = client.post(
                f"/rfqs/{rfq['id']}/actions/reject-quote?quote_id={quote['id']}",
                json={},
            )

        assert resp.status_code >= 500
        session.expire_all()
        persisted_quote = session.get(RFQQuote, quote_id)
        assert persisted_quote is not None
        assert persisted_quote.state == QuoteState.active
        reject_rows = (
            session.query(RFQInvitation)
            .filter(RFQInvitation.purpose == RFQInvitationPurpose.reject_quote)
            .count()
        )
        assert reject_rows == 0

    def test_rfq_refresh_counterparty_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        cp_id = _create_counterparty_via_api(client)
        rfq = _create_global_rfq(client, [cp_id])

        with _without_signing_key():
            resp = client.post(
                f"/rfqs/{rfq['id']}/actions/refresh-counterparty",
                json={"counterparty_id": cp_id},
            )

        assert resp.status_code >= 500
        session.expire_all()
        refresh_rows = (
            session.query(RFQInvitation)
            .filter(RFQInvitation.purpose == RFQInvitationPurpose.refresh)
            .count()
        )
        assert refresh_rows == 0

    def test_rfq_refresh_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        cp_id = _create_counterparty_via_api(client)
        rfq = _create_global_rfq(client, [cp_id])

        with _without_signing_key():
            resp = client.post(
                f"/rfqs/{rfq['id']}/actions/refresh",
                json={},
            )

        assert resp.status_code >= 500
        session.expire_all()
        refresh_rows = (
            session.query(RFQInvitation)
            .filter(RFQInvitation.purpose == RFQInvitationPurpose.refresh)
            .count()
        )
        assert refresh_rows == 0

    def test_rfq_award_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        cp_id = _create_counterparty_via_api(client)
        rfq = _create_global_rfq(client, [cp_id])
        _create_quote_via_api(client, rfq_id=rfq["id"], counterparty_id=cp_id)

        with _without_signing_key():
            resp = client.post(
                f"/rfqs/{rfq['id']}/actions/award",
                json={},
            )

        assert resp.status_code >= 500
        session.expire_all()
        persisted_rfq = session.get(RFQ, UUID(rfq["id"]))
        assert persisted_rfq is not None
        assert persisted_rfq.state == RFQState.quoted
        assert (
            session.query(HedgeContract)
            .filter(HedgeContract.rfq_id == UUID(rfq["id"]))
            .count()
            == 0
        )

    def test_rfq_archive_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        cp_id = _create_counterparty_via_api(client)
        rfq = _create_global_rfq(client, [cp_id])
        closed = client.post(f"/rfqs/{rfq['id']}/actions/cancel", json={})
        assert closed.status_code == 200

        with _without_signing_key():
            resp = client.patch(
                f"/rfqs/{rfq['id']}/archive",
                json={},
            )

        assert resp.status_code >= 500
        session.expire_all()
        persisted_rfq = session.get(RFQ, UUID(rfq["id"]))
        assert persisted_rfq is not None
        assert persisted_rfq.deleted_at is None
        assert persisted_rfq.state == RFQState.closed

    def test_mtm_snapshot_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        _insert_price(session, settlement_date=date(2026, 1, 30), price_usd="110")
        contract_id = _create_hedge_contract_via_api(client)

        with _without_signing_key():
            resp = client.post(
                "/mtm/snapshots",
                json={
                    "object_type": "hedge_contract",
                    "object_id": contract_id,
                    "as_of_date": "2026-02-01",
                    "correlation_id": "a5-mtm",
                },
            )

        assert resp.status_code >= 500
        session.expire_all()
        assert session.query(MTMSnapshot).count() == 0

    def test_pl_snapshot_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        _insert_price(session, settlement_date=date(2026, 1, 14), price_usd="110")
        _insert_price(session, settlement_date=date(2026, 1, 30), price_usd="110")
        contract_id = _create_hedge_contract_via_api(client)
        settlement = client.post(
            f"/cashflow/contracts/{contract_id}/settle",
            json=_settlement_payload(str(uuid.uuid4())),
        )
        assert settlement.status_code == 201, settlement.text

        with _without_signing_key():
            resp = client.post(
                "/pl/snapshots",
                json={
                    "entity_type": "hedge_contract",
                    "entity_id": contract_id,
                    "period_start": "2026-01-01",
                    "period_end": "2026-01-31",
                },
            )

        assert resp.status_code >= 500
        session.expire_all()
        assert session.query(PLSnapshot).count() == 0

    def test_cashflow_baseline_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        _insert_price(session, settlement_date=date(2026, 1, 30), price_usd="110")
        _create_variable_sales_order(client, avg_entry_price=100.0)

        with _without_signing_key():
            resp = client.post(
                "/cashflow/baseline/snapshots",
                json={"as_of_date": "2026-02-01", "correlation_id": "a5-cf"},
            )

        assert resp.status_code >= 500
        session.expire_all()
        assert session.query(CashFlowBaselineSnapshot).count() == 0

    def test_cashflow_settlement_rolls_back_when_signing_key_missing(
        self, client, session
    ) -> None:
        _insert_price(session, settlement_date=date(2026, 1, 14), price_usd="110")
        contract_id = _create_hedge_contract_via_api(client)

        with _without_signing_key():
            resp = client.post(
                f"/cashflow/contracts/{contract_id}/settle",
                json=_settlement_payload(str(uuid.uuid4())),
            )

        assert resp.status_code >= 500
        session.expire_all()
        persisted_contract = session.get(HedgeContract, UUID(contract_id))
        assert persisted_contract is not None
        assert persisted_contract.status == HedgeContractStatus.active
        assert session.query(HedgeContractSettlementEvent).count() == 0
        assert session.query(CashFlowLedgerEntry).count() == 0
