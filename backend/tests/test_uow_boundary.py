from __future__ import annotations

from uuid import UUID

from app.models.audit import AuditEvent
from app.models.linkages import HedgeOrderLinkage
from app.services.audit_trail_service import AuditTrailService


def _create_sales_order(client, quantity_mt: float) -> str:
    response = client.post(
        "/orders/sales",
        json={"price_type": "variable", "quantity_mt": quantity_mt},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_hedge_contract(client, quantity_mt: float) -> str:
    # Direction-correct hedge for a sales order per constitution §2.3 + §2.4
    # (PR-4 J-A1-OPUS-03): SO requires a SHORT (fixed_leg=sell) hedge.
    response = client.post(
        "/contracts/hedge",
        json={
            "commodity": "LME_AL",
            "quantity_mt": quantity_mt,
            "legs": [
                {"side": "sell", "price_type": "fixed"},
                {"side": "buy", "price_type": "variable"},
            ],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _linkage_payload(order_id: str, contract_id: str) -> dict:
    return {
        "order_id": order_id,
        "contract_id": contract_id,
        "quantity_mt": 5.0,
    }


def test_post_flush_audit_failure_rolls_back_linkage(
    client, session, monkeypatch
) -> None:
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(AuditTrailService, "record", fail_audit)

    response = client.post("/linkages", json=_linkage_payload(order_id, contract_id))

    assert response.status_code == 500
    assert session.query(HedgeOrderLinkage).count() == 0
    assert (
        session.query(AuditEvent).filter(AuditEvent.entity_type == "linkage").count()
        == 0
    )


def test_post_audit_db_commit_failure_rolls_back_audit_and_linkage(
    client, session, monkeypatch
) -> None:
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)
    audit_calls = 0
    original_record = AuditTrailService.record

    def fail_commit(self):
        raise RuntimeError("db commit failed")

    def record_then_fail_commit(*args, **kwargs):
        nonlocal audit_calls
        audit_calls += 1
        return original_record(*args, **kwargs)

    monkeypatch.setattr(AuditTrailService, "record", record_then_fail_commit)
    monkeypatch.setattr(session.__class__, "commit", fail_commit)

    response = client.post("/linkages", json=_linkage_payload(order_id, contract_id))

    assert response.status_code == 500
    assert audit_calls == 1
    assert session.query(HedgeOrderLinkage).count() == 0
    assert (
        session.query(AuditEvent).filter(AuditEvent.entity_type == "linkage").count()
        == 0
    )


def test_uow_boundary_commits_linkage_and_audit_together(client, session) -> None:
    order_id = _create_sales_order(client, 10.0)
    contract_id = _create_hedge_contract(client, 10.0)

    response = client.post("/linkages", json=_linkage_payload(order_id, contract_id))

    assert response.status_code == 201
    linkage_id = UUID(response.json()["id"])
    assert session.get(HedgeOrderLinkage, linkage_id) is not None
    assert (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_type == "linkage", AuditEvent.entity_id == linkage_id)
        .count()
        == 1
    )


# ────────────────────────────────────────────────────────────────────────
# PR-7 — failure-injection on the newly wired routes (deal create,
# reconcile, hedge task execute). Mirrors the PR-3 cases above to confirm
# the unit_of_work boundary still holds for the freshly audited routes.
# ────────────────────────────────────────────────────────────────────────


def test_post_audit_db_commit_failure_rolls_back_deal(
    client, session, monkeypatch
) -> None:
    """Same posture as the linkage case but for the deal create route."""
    from app.models.deal import Deal

    audit_calls = 0
    original_record = AuditTrailService.record

    def fail_commit(self):
        raise RuntimeError("db commit failed")

    def record_then_fail_commit(*args, **kwargs):
        nonlocal audit_calls
        audit_calls += 1
        return original_record(*args, **kwargs)

    monkeypatch.setattr(AuditTrailService, "record", record_then_fail_commit)
    monkeypatch.setattr(session.__class__, "commit", fail_commit)

    response = client.post(
        "/deals", json={"name": "Should Roll Back", "commodity": "ALUMINUM"}
    )

    assert response.status_code == 500
    assert audit_calls == 1
    assert (
        session.query(Deal).filter(Deal.name == "Should Roll Back").count() == 0
    )
    assert (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_type == "deal")
        .count()
        == 0
    )


def test_post_audit_db_commit_failure_rolls_back_reconcile_run(
    client, session, monkeypatch
) -> None:
    """Reconcile creates a ReconciliationRun anchor — when the final
    commit fails, the anchor must NOT remain in the database."""
    from app.models.reconciliation_run import ReconciliationRun

    audit_calls = 0
    original_record = AuditTrailService.record

    def fail_commit(self):
        raise RuntimeError("db commit failed")

    def record_then_fail_commit(*args, **kwargs):
        nonlocal audit_calls
        audit_calls += 1
        return original_record(*args, **kwargs)

    monkeypatch.setattr(AuditTrailService, "record", record_then_fail_commit)
    monkeypatch.setattr(session.__class__, "commit", fail_commit)

    response = client.post("/exposures/reconcile")

    assert response.status_code == 500
    assert audit_calls == 1
    assert session.query(ReconciliationRun).count() == 0
    assert (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_type == "exposure_reconciliation")
        .count()
        == 0
    )
