# W3 — Hedge RFQ Sanctions Gate Re-target + HB-3 Two-Domain Risk Flags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-target the hedge RFQ admission gate from KYC to sanctions (fail-closed) across all six `rfq_service.py` sites, replace `kyc_gate.py` with a mirrored `sanctions_gate.py`, and re-align the HB-3 finance-pipeline `risk_flags` step to a two-domain (hedge-sanctions / commercial-kyc-or-sanctions) model.

**Architecture:** A thin `assert_sanctions_clear` primitive (mirroring the existing `assert_kyc_approved` field-for-field) reads `Counterparty.sanctions_status` — which already reflects W2 adjudication-to-clear — and admits only when it is `clear`; refusal emits an HMAC audit event on a separate committed session before raising HTTP 422. The HB-3 step gains a second domain via two new `flag_type` enum values added through an additive Postgres `ALTER TYPE ... ADD VALUE` migration.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, pytest (SQLite in-memory). Postgres in production (alembic-fresh-postgres CI gate).

**Spec:** `docs/superpowers/specs/2026-05-31-w3-hedge-rfq-sanctions-gate-design.md`. **Branch:** `w3/hedge-rfq-sanctions-gate` (already created off `main`; spec committed `7111de1`).

---

## File structure

| File | Responsibility |
|---|---|
| `backend/app/services/sanctions_gate.py` *(create)* | `assert_sanctions_clear` RFQ admission primitive (mirror of `kyc_gate`) |
| `backend/app/services/rfq_service.py` *(modify)* | swap import + 6 call sites `assert_kyc_approved` → `assert_sanctions_clear` |
| `backend/app/services/kyc_gate.py` *(delete)* | dead after re-target |
| `backend/app/services/counterparty_service.py` *(modify)* | repoint one comment from `assert_kyc_approved` → sanctions gate |
| `backend/app/services/sanctions_screening_service.py` *(modify)* | repoint docstring `kyc_gate` → `sanctions_gate` |
| `backend/app/models/finance_pipeline.py` *(modify)* | add 2 `PipelineRiskFlagType` members |
| `backend/app/services/finance_pipeline_service.py` *(modify)* | two-domain risk-flag queries + emission |
| `backend/alembic/versions/050_w3_pipeline_risk_flag_sanctions.py` *(create)* | additive enum migration |
| `backend/tests/test_sanctions_gate.py` *(create)* | unit tests for the primitive |
| `backend/tests/test_rfq_sanctions_gate.py` *(create)* | route-level RFQ admission tests (replaces `test_rfq_kyc_gate.py`) |
| `backend/tests/test_rfq_kyc_gate.py` *(delete)* | superseded |
| `backend/tests/test_counterparty_kyc_transition.py` *(modify)* | update stale comments + make `submit_quote` test sanctions-clear |
| `backend/tests/test_finance_pipeline_hb3.py` *(modify)* | two-domain flag tests |
| various RFQ happy-path test files *(modify)* | mark admission counterparties sanctions-clear (Task 2 sweep) |

**Reference facts (verified against the codebase):**
- `Counterparty.sanctions_status` exists (hedge), enum `SanctionsStatus = {unscreened, clear, flagged, blocked}` in `app/models/counterparty.py`.
- `CommercialPartner` reuses the SAME Python `KycStatus`/`SanctionsStatus` enums from `app/models/counterparty.py`.
- `Order` (`app/models/orders.py`) has **no lifecycle status field**; `counterparty_id` → `commercial_partners.id`; soft-delete is `deleted_at` (nullable). Active orders = `deleted_at IS NULL AND counterparty_id IS NOT NULL`.
- The 6 RFQ call sites use identical kwargs to `assert_kyc_approved`; the re-target is a pure function-name swap.
- Migration head is `049_commercial_partners_foundation`. Enum-add pattern: `op.execute("ALTER TYPE … ADD VALUE IF NOT EXISTS '…'")` guarded by `if bind.dialect.name != "postgresql": return`; downgrade is a no-op (see `alembic/versions/023_add_bank_br_to_counterparty_type.py`).
- conftest helper: `mark_counterparty_sanctions_clear(counterparty_id)` sets `sanctions_status = clear`.

> **Working-directory note for the executor:** the repo ships a `precision_guard` Edit/Write hook that resolves `scripts/hooks/precision_guard.py` relative to the shell CWD. Run all `git`/`pytest`/edit commands from the repo ROOT (`d:/Projetos/Hedge-Control-New`), not from `backend/`, or the hook errors. Prefix pytest with `cd backend && …` inside a single command rather than leaving the shell parked in `backend/`.

---

## Task 1: `sanctions_gate.py` primitive

**Files:**
- Create: `backend/app/services/sanctions_gate.py`
- Test: `backend/tests/test_sanctions_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sanctions_gate.py
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.counterparty import Counterparty, CounterpartyType, KycStatus, SanctionsStatus
from app.services.sanctions_gate import assert_sanctions_clear


def _cp(session, sanctions_status: SanctionsStatus) -> Counterparty:
    cp = Counterparty(
        type=CounterpartyType.broker,
        name="ACME Broker",
        country="BRA",
        kyc_status=KycStatus.approved,
        sanctions_status=sanctions_status,
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp


def test_clear_admits_and_returns_counterparty():
    with SessionLocal() as session:
        cp = _cp(session, SanctionsStatus.clear)
        out = assert_sanctions_clear(
            session, cp.id, gate_point="rfq_invitation", requesting_actor_sub="rm-1"
        )
        assert out.id == cp.id


@pytest.mark.parametrize(
    "st", [SanctionsStatus.flagged, SanctionsStatus.unscreened, SanctionsStatus.blocked]
)
def test_non_clear_denies_with_422(st):
    with SessionLocal() as session:
        cp = _cp(session, st)
        with pytest.raises(HTTPException) as exc:
            assert_sanctions_clear(
                session, cp.id, gate_point="rfq_quote",
                requesting_actor_sub="rm-1", rfq_id=uuid.uuid4(),
            )
        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "rfq_quote_rejected_sanctions_not_cleared"
        assert exc.value.detail["sanctions_status_observed"] == st.value


def test_missing_counterparty_404():
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            assert_sanctions_clear(
                session, uuid.uuid4(), gate_point="rfq_award", requesting_actor_sub="rm"
            )
        assert exc.value.status_code == 404


def test_refusal_audit_survives_rollback():
    with SessionLocal() as session:
        cp = _cp(session, SanctionsStatus.flagged)
        cp_id = cp.id
        with pytest.raises(HTTPException):
            assert_sanctions_clear(
                session, cp_id, gate_point="rfq_invitation", requesting_actor_sub="rm-1",
                rfq_id=uuid.uuid4(), extra_payload={"attempted_purpose": "rfq_invite"},
            )
        session.rollback()  # simulate the outer unit_of_work rollback
    with SessionLocal() as verify:
        ev = (
            verify.query(AuditEvent)
            .filter(AuditEvent.entity_id == cp_id)
            .filter(AuditEvent.event_type == "rfq_invitation_rejected_sanctions_not_cleared")
            .one()
        )
        assert ev.payload["attempted_purpose"] == "rfq_invite"
        assert ev.payload["sanctions_status_observed"] == "flagged"
        assert ev.payload["requesting_actor_sub"] == "rm-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sanctions_gate.py -q`
Expected: FAIL (module `app.services.sanctions_gate` does not exist).

- [ ] **Step 3: Implement the gate (mirror of `kyc_gate.py`)**

```python
# backend/app/services/sanctions_gate.py
"""Sanctions gate primitive for RFQ-lifecycle admission and quote ingestion.

Constitutional anchor: docs/governance.md §445-446 (hedge RFQ sanctions gate).
W3 re-targets the W1 KYC admission gate to sanctions: hedge RFQ admission is
fail-closed unless the counterparty's effective ``sanctions_status`` is
``clear`` — a recorded clear screening OR a risk_manager adjudication-to-clear,
both of which are written directly onto ``Counterparty.sanctions_status`` (W2),
so no adjudication-record join is needed. ``blocked``, unadjudicated ``flagged``,
and ``unscreened`` all deny.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.counterparty import Counterparty, SanctionsStatus
from app.services.audit_trail_service import AuditTrailService
from app.services.counterparty_service import CounterpartyService

GatePoint = Literal["rfq_invitation", "rfq_quote", "rfq_award"]

_EVENT_TYPE_BY_GATE = {
    "rfq_invitation": "rfq_invitation_rejected_sanctions_not_cleared",
    "rfq_quote": "rfq_quote_rejected_sanctions_not_cleared",
    "rfq_award": "rfq_award_rejected_sanctions_not_cleared",
}


def assert_sanctions_clear(
    db: Session,
    counterparty_id: uuid.UUID,
    *,
    gate_point: GatePoint,
    requesting_actor_sub: str | None,
    rfq_id: uuid.UUID | None = None,
    extra_payload: dict | None = None,
) -> Counterparty:
    """Refuse the operation unless counterparty.sanctions_status == clear.

    On refusal:
      1. Emits an HMAC-signed audit event on a SEPARATE committed session
         (dual-session) so the row survives the outer ``unit_of_work``
         rollback that fires on HTTPException.
      2. Raises HTTPException(422).

    Returns the loaded Counterparty when sanctions_status is clear.
    """
    # CounterpartyService.get_by_id (NOT db.get) so soft-deleted rows return
    # None and the gate fails closed with 404.
    cp = CounterpartyService.get_by_id(db, counterparty_id)
    if cp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Counterparty not found",
        )
    if cp.sanctions_status == SanctionsStatus.clear:
        return cp

    event_type = _EVENT_TYPE_BY_GATE[gate_point]
    payload = {
        "counterparty_id": str(counterparty_id),
        "sanctions_status_observed": cp.sanctions_status.value,
        "requesting_actor_sub": requesting_actor_sub,
        "rfq_id": str(rfq_id) if rfq_id is not None else None,
        **(extra_payload or {}),
    }

    audit_session = SessionLocal()
    try:
        AuditTrailService.record(
            audit_session,
            event_id=uuid.uuid4(),
            entity_type="counterparty",
            entity_id=counterparty_id,
            event_type=event_type,
            payload_raw="",  # canonicalized from payload_obj internally
            payload_obj=payload,
            commit=True,  # own session, own commit — survives outer rollback
        )
    finally:
        audit_session.close()

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": event_type,
            "counterparty_id": str(counterparty_id),
            "sanctions_status_observed": cp.sanctions_status.value,
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sanctions_gate.py -q`
Expected: PASS (6 passed — 1 clear + 3 parametrized denies + 404 + rollback).

- [ ] **Step 5: Lint + commit**

```bash
cd backend && ruff check app/services/sanctions_gate.py tests/test_sanctions_gate.py && ruff format --check app/services/sanctions_gate.py tests/test_sanctions_gate.py
cd .. && git add backend/app/services/sanctions_gate.py backend/tests/test_sanctions_gate.py
git commit -m "feat(w3): sanctions_gate.assert_sanctions_clear (mirror of kyc_gate, fail-closed)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Re-target `rfq_service.py` + RFQ tests

**Files:**
- Modify: `backend/app/services/rfq_service.py` (import line ~53 + 6 call sites)
- Create: `backend/tests/test_rfq_sanctions_gate.py`
- Delete: `backend/tests/test_rfq_kyc_gate.py`
- Modify (sweep): RFQ happy-path test files that exercise create/submit_quote/refresh/award

- [ ] **Step 1: Write the failing route-level test**

```python
# backend/tests/test_rfq_sanctions_gate.py
from __future__ import annotations

from uuid import UUID

from app.core.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.counterparty import Counterparty, SanctionsStatus
from conftest import mark_counterparty_sanctions_clear


def _create_counterparty(client, name: str, phone: str = "+5511999990001") -> dict:
    resp = client.post(
        "/counterparties",
        json={"type": "broker", "name": name, "country": "BRA", "whatsapp_phone": phone},
    )
    assert resp.status_code == 201
    return resp.json()


def _approve_kyc(client, cp_id: str) -> None:
    r = client.post(
        f"/counterparties/{cp_id}/kyc-status",
        json={"new_status": "approved", "reason": "Test approval"},
    )
    assert r.status_code == 200


def _set_sanctions(cp_id: str, status_: SanctionsStatus) -> None:
    with SessionLocal() as s:
        cp = s.get(Counterparty, UUID(cp_id))
        cp.sanctions_status = status_
        s.commit()


def test_create_rejects_non_clear_counterparty(client):
    cp = _create_counterparty(client, "Flagged Broker")
    _approve_kyc(client, cp["id"])
    _set_sanctions(cp["id"], SanctionsStatus.flagged)  # approved but flagged
    resp = client.post(
        "/rfqs",
        json={
            "intent": "outright",
            "direction": "buy",
            "commodity": "ALUMINUM",
            "quantity_mt": "25",
            "counterparty_ids": [cp["id"]],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "rfq_invitation_rejected_sanctions_not_cleared"

    with SessionLocal() as s:
        ev = (
            s.query(AuditEvent)
            .filter(AuditEvent.entity_id == UUID(cp["id"]))
            .filter(AuditEvent.event_type == "rfq_invitation_rejected_sanctions_not_cleared")
            .first()
        )
        assert ev is not None
        assert ev.payload["attempted_purpose"] == "rfq_invite"
        assert ev.payload["sanctions_status_observed"] == "flagged"


def test_create_admits_sanctions_clear_counterparty(client):
    cp = _create_counterparty(client, "Clear Broker")
    _approve_kyc(client, cp["id"])
    mark_counterparty_sanctions_clear(cp["id"])
    resp = client.post(
        "/rfqs",
        json={
            "intent": "outright",
            "direction": "buy",
            "commodity": "ALUMINUM",
            "quantity_mt": "25",
            "counterparty_ids": [cp["id"]],
        },
    )
    assert resp.status_code == 201
```

> NOTE: the exact `POST /rfqs` request body must match the current RFQ create schema. Before writing, read `backend/app/schemas/rfq.py` (or the existing `test_rfqs_step1.py` create call) and copy the real field names/values. The two assertions that matter are the 422 + event code on a non-clear counterparty and the 201 on a clear one — keep those, adapt the request body to reality.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_rfq_sanctions_gate.py -q`
Expected: FAIL — currently the RFQ create gates on KYC (not sanctions), so an approved+flagged counterparty is admitted (201, not 422).

- [ ] **Step 3: Swap the import (rfq_service.py ~line 53)**

Change:
```python
from app.services.kyc_gate import assert_kyc_approved
```
to:
```python
from app.services.sanctions_gate import assert_sanctions_clear
```

- [ ] **Step 4: Replace all 6 call sites**

Each call keeps its kwargs **unchanged** — only the function name changes. Replace every occurrence of `assert_kyc_approved(` with `assert_sanctions_clear(` in `rfq_service.py`. The six sites and their (unchanged) gate_points:

| Line (approx) | Method | `gate_point` | `extra_payload` (unchanged) |
|---|---|---|---|
| 580 | `create` | `"rfq_invitation"` | `{"attempted_purpose": "rfq_invite"}` |
| 853 | `submit_quote` | `"rfq_quote"` | `{"rejection_path": …, "inbound_message_id": …}` |
| 1029 | `refresh` | `"rfq_invitation"` | `{"attempted_purpose": "refresh"}` |
| 1297 | `refresh_counterparty` | `"rfq_invitation"` | `{"attempted_purpose": "refresh"}` |
| 1469 | `award` (spread) | `"rfq_award"` | `{"quote_id": …}` |
| 1583 | `award` (trade) | `"rfq_award"` | `{"quote_id": …}` |

Verify zero remaining references: `cd backend && grep -rn "assert_kyc_approved" app/` must return nothing.

- [ ] **Step 5: Delete the old gate test**

```bash
git rm backend/tests/test_rfq_kyc_gate.py
```
(The new `tests/test_rfq_sanctions_gate.py` from Step 1 replaces it.)

- [ ] **Step 6: Run the new gate test to verify it passes**

Run: `cd backend && python -m pytest tests/test_rfq_sanctions_gate.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Sweep RFQ happy-path tests for the gate change**

Run the affected RFQ test files and fix any flow that now hits the sanctions gate. Many files already call `mark_counterparty_sanctions_clear` (W2). The candidates that exercise create/submit_quote/award and may NOT yet mark sanctions-clear:

```bash
cd backend && python -m pytest \
  tests/test_rfq_engine.py tests/test_rfq_orchestrator.py \
  tests/test_inbound_canonical_id.py tests/test_audit_economic_mutations.py \
  tests/test_auth_role_isolation.py tests/test_rbac_matrix_enforcement.py \
  tests/test_rfqs_step1.py tests/test_rfqs_step2.py tests/test_rfqs_step3.py \
  tests/test_outbound_evidence.py tests/test_rfq_actor_jwt_derivation.py -q
```

For each FAILURE where a previously-passing RFQ flow now returns 422 with code `*_rejected_sanctions_not_cleared`: the test's admission counterparty is approved-but-not-sanctions-clear. Make it clear by adding, after the counterparty is created/approved, either:
- route/client tests: `mark_counterparty_sanctions_clear(cp_id)` (import from `conftest`), or
- direct-session tests: set `counterparty.sanctions_status = SanctionsStatus.clear` and commit (import `SanctionsStatus` from `app.models.counterparty`).

Do NOT change a test whose PURPOSE is to assert a kyc/sanctions rejection — only the happy-path admission flows. Re-run until the listed files are green (modulo pre-existing environmental failures).

- [ ] **Step 8: Lint + commit**

```bash
cd backend && ruff check app/services/rfq_service.py tests/test_rfq_sanctions_gate.py && ruff format --check app/services/rfq_service.py tests/test_rfq_sanctions_gate.py
cd .. && git add backend/app/services/rfq_service.py backend/tests/
git commit -m "feat(w3): re-target 6 RFQ admission sites kyc->sanctions; replace rfq kyc-gate test

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Delete `kyc_gate.py` + fix stale references

**Files:**
- Delete: `backend/app/services/kyc_gate.py`
- Modify: `backend/app/services/counterparty_service.py` (comment ~line 15-17)
- Modify: `backend/app/services/sanctions_screening_service.py` (docstring ~line 5)
- Modify: `backend/tests/test_counterparty_kyc_transition.py` (stale comments + submit_quote test)

- [ ] **Step 1: Confirm nothing imports `kyc_gate` anymore**

Run: `cd backend && grep -rn "kyc_gate\|assert_kyc_approved" app/ tests/`
Expected: only the two comment/docstring references (counterparty_service.py, sanctions_screening_service.py) and possibly test_counterparty_kyc_transition.py comments. NO `import` of `assert_kyc_approved` should remain (rfq_service was swapped in Task 2; test_rfq_kyc_gate was deleted).

- [ ] **Step 2: Delete the module**

```bash
git rm backend/app/services/kyc_gate.py
```

- [ ] **Step 3: Repoint the comment in `counterparty_service.py`**

The comment (~lines 14-17) currently reads `the RFQ gate ``assert_kyc_approved`` admits on ``kyc_status``)`. Replace that clause to reflect W3:

```python
# Screening-relevant identity fields. A generic-PATCH change to any of these
# invalidates prior screening evidence (the RFQ gate ``assert_sanctions_clear``
# admits on ``sanctions_status``), so compliance must fail closed on identity edits.
```
(Keep the surrounding lines about `_IDENTITY_FIELDS` unchanged; only fix the gate name + field reference.)

- [ ] **Step 4: Repoint the docstring in `sanctions_screening_service.py`**

The module docstring (~line 5) says `Reuses the ``kyc_gate`` dual-session pattern …`. Change `kyc_gate` → `sanctions_gate`:
```python
sets the entity ``sanctions_status``, and emits HMAC audit events. Reuses the
``sanctions_gate`` dual-session pattern to record provider-error evidence that
survives the request ``unit_of_work`` rollback.
```

- [ ] **Step 5: Update `test_counterparty_kyc_transition.py`**

Read the file. Make two changes:
1. **Stale comments (~lines 102-104, 127, 308):** these describe the W3 re-target as future ("the W1 RFQ gate (assert_kyc_approved) must remain", "W2/W3 own it"). Update them to present reality: the hedge RFQ gate now reads `sanctions_status` via `assert_sanctions_clear`; `kyc_status` no longer gates hedge RFQ admission.
2. **`test_submit_quote_attribution` (~lines 199-267):** this test calls `RFQService.submit_quote`, which now gates on sanctions. After the counterparty is created/approved in this test, mark it sanctions-clear so the quote is admitted. Add (using the counterparty id the test already has):
   - route/client style: `mark_counterparty_sanctions_clear(cp_id)` (import from `conftest`), or
   - direct-session: `counterparty.sanctions_status = SanctionsStatus.clear; session.commit()`.

Match whichever counterparty-construction style the test already uses.

- [ ] **Step 6: Run the affected tests**

Run: `cd backend && python -m pytest tests/test_counterparty_kyc_transition.py -q`
Expected: PASS (the submit_quote attribution test now admits the sanctions-clear counterparty; other tests unaffected).

- [ ] **Step 7: Commit**

```bash
git add -A backend/app/services backend/tests/test_counterparty_kyc_transition.py
git commit -m "refactor(w3): delete dead kyc_gate.py; repoint references to sanctions_gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: HB-3 enum members + migration 050

**Files:**
- Modify: `backend/app/models/finance_pipeline.py` (`PipelineRiskFlagType`)
- Create: `backend/alembic/versions/050_w3_pipeline_risk_flag_sanctions.py`
- Test: `backend/tests/test_alembic_chain.py` (existing single-head guard — just run it)

- [ ] **Step 1: Add the two enum members (model)**

In `backend/app/models/finance_pipeline.py`, extend `PipelineRiskFlagType` (keep existing members; mark the old hedge one deprecated in a comment):

```python
class PipelineRiskFlagType(enum.Enum):
    missing_mtm_price = "missing_mtm_price"
    unhedged_exposure_over_guardrail = "unhedged_exposure_over_guardrail"
    kyc_regression_with_active_deals = "kyc_regression_with_active_deals"  # deprecated (W3): no longer emitted
    workflow_approval_pending_past_expiry = "workflow_approval_pending_past_expiry"
    sanctions_regression_with_active_deals = "sanctions_regression_with_active_deals"
    commercial_compliance_regression_with_active_orders = "commercial_compliance_regression_with_active_orders"
```

- [ ] **Step 2: Write the additive migration**

```python
# backend/alembic/versions/050_w3_pipeline_risk_flag_sanctions.py
"""W3: add sanctions + commercial-compliance values to pipeline_risk_flag_type.

Two-domain HB-3 risk_flags: hedge sanctions regressions and commercial
KYC-or-sanctions regressions. Additive only — the deprecated
``kyc_regression_with_active_deals`` value is left in place (PostgreSQL cannot
remove enum values without recreating the type).

Revision ID: 050_w3_pipeline_risk_flag_sanctions
Revises: 049_commercial_partners_foundation
Create Date: 2026-05-31 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "050_w3_pipeline_risk_flag_sanctions"
down_revision: Union[str, None] = "049_commercial_partners_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # ALTER TYPE ... ADD VALUE; values are not used within this migration's
    # transaction, so this is safe on PG 12+. SQLite stores the column as a
    # string variant, so no DDL is needed there. Mirrors the 023 pattern.
    op.execute(
        "ALTER TYPE pipeline_risk_flag_type ADD VALUE IF NOT EXISTS "
        "'sanctions_regression_with_active_deals'"
    )
    op.execute(
        "ALTER TYPE pipeline_risk_flag_type ADD VALUE IF NOT EXISTS "
        "'commercial_compliance_regression_with_active_orders'"
    )


def downgrade() -> None:
    # PostgreSQL does not support removing values from an enum type.
    pass
```

- [ ] **Step 3: Verify single-head + chain**

Run: `cd backend && python -m pytest tests/test_alembic_chain.py -q`
Expected: PASS (single head = `050_w3_pipeline_risk_flag_sanctions`).

- [ ] **Step 4: Verify the model import still loads**

Run: `cd backend && python -c "from app.models.finance_pipeline import PipelineRiskFlagType; print([m.value for m in PipelineRiskFlagType])"`
Expected: prints all 6 values including the two new ones.

- [ ] **Step 5: Commit**

```bash
cd backend && ruff check app/models/finance_pipeline.py alembic/versions/050_w3_pipeline_risk_flag_sanctions.py && ruff format --check app/models/finance_pipeline.py alembic/versions/050_w3_pipeline_risk_flag_sanctions.py
cd .. && git add backend/app/models/finance_pipeline.py backend/alembic/versions/050_w3_pipeline_risk_flag_sanctions.py
git commit -m "feat(w3): add two-domain pipeline_risk_flag_type enum values + migration 050

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: HB-3 two-domain risk-flag queries + emission

**Files:**
- Modify: `backend/app/services/finance_pipeline_service.py`
- Test: `backend/tests/test_finance_pipeline_hb3.py`

- [ ] **Step 1: Write the failing tests**

Add these tests to `backend/tests/test_finance_pipeline_hb3.py` (the file already imports `Counterparty`, `CounterpartyType`, `KycStatus`, `FinancePipelineRiskFlag`, `PipelineRiskFlagType`, `FinancePipelineService`, and defines `_active_contract_for_counterparty`):

```python
def test_hedge_sanctions_regression_flag_with_active_deal(session) -> None:
    from app.models.counterparty import SanctionsStatus

    cp = Counterparty(
        type=CounterpartyType.broker,
        name="Flagged Hedge Broker",
        country="BRA",
        kyc_status=KycStatus.approved,
        sanctions_status=SanctionsStatus.flagged,
    )
    session.add(cp)
    session.commit()
    _active_contract_for_counterparty(session, str(cp.id))

    run = FinancePipelineService.run_daily_pipeline(session, date(2026, 3, 3))

    flags = (
        session.query(FinancePipelineRiskFlag)
        .filter_by(run_id=run.id, subject_entity_id=cp.id)
        .all()
    )
    assert any(
        f.flag_type == PipelineRiskFlagType.sanctions_regression_with_active_deals
        and f.payload["sanctions_status"] == "flagged"
        for f in flags
    )
    # The deprecated kyc flag is NOT emitted for hedge anymore.
    assert all(
        f.flag_type != PipelineRiskFlagType.kyc_regression_with_active_deals for f in flags
    )


def test_commercial_compliance_regression_flag_with_active_order(session) -> None:
    from decimal import Decimal

    from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind
    from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus
    from app.models.orders import Order, OrderType, PriceType

    partner = CommercialPartner(
        kind=CommercialPartnerKind.customer,
        name="Pending Customer",
        country="BRA",
        kyc_status=KycStatus.pending,  # regression dimension: kyc
        sanctions_status=SanctionsStatus.clear,
        risk_rating=RiskRating.medium,
    )
    session.add(partner)
    session.commit()
    session.refresh(partner)
    order = Order(
        order_type=OrderType.sales,
        price_type=PriceType.fixed,
        commodity="ALUMINUM",
        quantity_mt=Decimal("10.000"),
        counterparty_id=partner.id,
    )
    session.add(order)
    session.commit()

    run = FinancePipelineService.run_daily_pipeline(session, date(2026, 3, 4))

    flag = (
        session.query(FinancePipelineRiskFlag)
        .filter_by(
            run_id=run.id,
            subject_entity_id=partner.id,
            flag_type=PipelineRiskFlagType.commercial_compliance_regression_with_active_orders,
        )
        .one()
    )
    assert flag.payload["dimensions"] == ["kyc"]
    assert flag.payload["kyc_status_observed"] == "pending"


def test_commercial_clean_partner_with_active_order_yields_no_flag(session) -> None:
    from decimal import Decimal

    from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind
    from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus
    from app.models.orders import Order, OrderType, PriceType

    partner = CommercialPartner(
        kind=CommercialPartnerKind.supplier,
        name="Clean Supplier",
        country="BRA",
        kyc_status=KycStatus.approved,
        sanctions_status=SanctionsStatus.clear,
        risk_rating=RiskRating.medium,
    )
    session.add(partner)
    session.commit()
    session.refresh(partner)
    session.add(
        Order(
            order_type=OrderType.purchase,
            price_type=PriceType.fixed,
            commodity="ALUMINUM",
            quantity_mt=Decimal("10.000"),
            counterparty_id=partner.id,
        )
    )
    session.commit()

    run = FinancePipelineService.run_daily_pipeline(session, date(2026, 3, 5))
    flags = (
        session.query(FinancePipelineRiskFlag)
        .filter_by(
            run_id=run.id,
            subject_entity_id=partner.id,
            flag_type=PipelineRiskFlagType.commercial_compliance_regression_with_active_orders,
        )
        .all()
    )
    assert flags == []
```

> NOTE: confirm `run_daily_pipeline(session, date(...))` is the correct minimal invocation (the existing tests call it both with and without `trigger_source=`). If the `session` fixture or run signature differs, match the existing passing tests in this file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_finance_pipeline_hb3.py -k "sanctions_regression or commercial_compliance or commercial_clean" -q`
Expected: FAIL (the service still emits the old kyc flag and never emits the two new flag types).

- [ ] **Step 3: Add the two query helpers + imports**

In `backend/app/services/finance_pipeline_service.py`, add imports near the other model imports:
```python
from sqlalchemy import or_

from app.models.commercial_partner import CommercialPartner
from app.models.counterparty import SanctionsStatus  # KycStatus already imported
from app.models.orders import Order
```

Add two static methods (place next to where `_query_kyc_regressions_with_active_deals` is):

```python
    @staticmethod
    def _query_sanctions_regressions_with_active_deals(db: Session) -> list[Counterparty]:
        active_counterparty_ids = {
            uuid.UUID(contract.counterparty_id)
            for contract in FinancePipelineService._active_contracts(db)
            if contract.counterparty_id
            and FinancePipelineService._is_uuid(contract.counterparty_id)
        }
        if not active_counterparty_ids:
            return []
        return (
            db.query(Counterparty)
            .filter(
                Counterparty.id.in_(active_counterparty_ids),
                Counterparty.sanctions_status != SanctionsStatus.clear,
                Counterparty.is_deleted.is_(False),
            )
            .order_by(Counterparty.created_at.asc(), Counterparty.id.asc())
            .all()
        )

    @staticmethod
    def _query_commercial_compliance_regressions_with_active_orders(
        db: Session,
    ) -> list[CommercialPartner]:
        active_partner_ids = {
            order.counterparty_id
            for order in db.query(Order).filter(
                Order.deleted_at.is_(None),
                Order.counterparty_id.isnot(None),
            )
        }
        if not active_partner_ids:
            return []
        return (
            db.query(CommercialPartner)
            .filter(
                CommercialPartner.id.in_(active_partner_ids),
                or_(
                    CommercialPartner.kyc_status != KycStatus.approved,
                    CommercialPartner.sanctions_status != SanctionsStatus.clear,
                ),
                CommercialPartner.is_deleted.is_(False),
            )
            .order_by(CommercialPartner.created_at.asc(), CommercialPartner.id.asc())
            .all()
        )
```

- [ ] **Step 4: Re-wire `_step_risk_flags` (replace the kyc loop, add the commercial loop)**

In `_step_risk_flags`, DELETE the existing hedge kyc loop:
```python
        for counterparty in FinancePipelineService._query_kyc_regressions_with_active_deals(db):
            if FinancePipelineService._emit_risk_flag(
                db,
                run_id=run.id,
                flag_type=PipelineRiskFlagType.kyc_regression_with_active_deals,
                severity=PipelineRiskFlagSeverity.critical,
                subject_entity_type="counterparty",
                subject_entity_id=counterparty.id,
                payload={"kyc_status": counterparty.kyc_status.value},
            ):
                flags_written += 1
```
and REPLACE it with the two-domain loops:
```python
        for counterparty in FinancePipelineService._query_sanctions_regressions_with_active_deals(db):
            if FinancePipelineService._emit_risk_flag(
                db,
                run_id=run.id,
                flag_type=PipelineRiskFlagType.sanctions_regression_with_active_deals,
                severity=PipelineRiskFlagSeverity.critical,
                subject_entity_type="counterparty",
                subject_entity_id=counterparty.id,
                payload={"sanctions_status": counterparty.sanctions_status.value},
            ):
                flags_written += 1

        for partner in FinancePipelineService._query_commercial_compliance_regressions_with_active_orders(db):
            dimensions = []
            if partner.kyc_status != KycStatus.approved:
                dimensions.append("kyc")
            if partner.sanctions_status != SanctionsStatus.clear:
                dimensions.append("sanctions")
            if FinancePipelineService._emit_risk_flag(
                db,
                run_id=run.id,
                flag_type=PipelineRiskFlagType.commercial_compliance_regression_with_active_orders,
                severity=PipelineRiskFlagSeverity.critical,
                subject_entity_type="commercial_partner",
                subject_entity_id=partner.id,
                payload={
                    "dimensions": dimensions,
                    "kyc_status_observed": partner.kyc_status.value,
                    "sanctions_status_observed": partner.sanctions_status.value,
                },
            ):
                flags_written += 1
```

- [ ] **Step 5: Delete the now-dead `_query_kyc_regressions_with_active_deals`**

Remove the `_query_kyc_regressions_with_active_deals` static method (no longer referenced). Confirm: `cd backend && grep -rn "_query_kyc_regressions_with_active_deals" app/ tests/` returns nothing.

- [ ] **Step 6: Update the existing four-flag test**

`test_risk_flags_step_detects_four_bound_flag_types` (in `test_finance_pipeline_hb3.py`) asserts `kyc_regression_with_active_deals` is emitted for a hedge counterparty with `kyc_status=expired`. That flag is no longer emitted. Update this test: change the hedge counterparty to also carry `sanctions_status=SanctionsStatus.flagged`, and assert `sanctions_regression_with_active_deals` is in the produced `flag_types` set instead of `kyc_regression_with_active_deals`. (Import `SanctionsStatus` from `app.models.counterparty`.)

- [ ] **Step 7: Run the HB-3 tests**

Run: `cd backend && python -m pytest tests/test_finance_pipeline_hb3.py -q`
Expected: PASS (new two-domain tests + updated four-flag test all green).

- [ ] **Step 8: Lint + commit**

```bash
cd backend && ruff check app/services/finance_pipeline_service.py tests/test_finance_pipeline_hb3.py && ruff format --check app/services/finance_pipeline_service.py tests/test_finance_pipeline_hb3.py
cd .. && git add backend/app/services/finance_pipeline_service.py backend/tests/test_finance_pipeline_hb3.py
git commit -m "feat(w3): HB-3 two-domain risk_flags (hedge sanctions + commercial kyc/sanctions)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Full-suite gate + PR

**Files:** none (verification + PR)

- [ ] **Step 1: Full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all W3 tests pass; only the known ~26 pre-existing environmental failures remain (auth-`APP_ENV`, internal-test-gating, whatsapp, webhook, service-token, and the `TestRouteCoverageStatic` inventory test which fails locally only without `APP_ENV=test`). Confirm zero W3-caused failures: every failing node ID must be in the pre-existing set, not in any RFQ / sanctions_gate / finance_pipeline test touched by W3.

- [ ] **Step 2: CI-env spot check (route inventory + gate tests)**

Run: `cd backend && APP_ENV=test DATABASE_URL="sqlite+pysqlite:///:memory:" AUDIT_SIGNING_KEY="test-key-1234567" python -m pytest "tests/test_audit_economic_mutations.py::TestRouteCoverageStatic" tests/test_rfq_sanctions_gate.py tests/test_sanctions_gate.py -q`
Expected: all pass.

- [ ] **Step 3: Confirm no OpenAPI / frontend impact**

W3 adds no routes and changes no response models (only internal rejection event types + risk-flag enum). No `schema.d.ts` regen is needed. (If `npm run api:types:check` is part of CI and flags drift, investigate — but none is expected.)

- [ ] **Step 4: Push the branch**

```bash
git push -u origin w3/hedge-rfq-sanctions-gate
```
Note: the local pre-push hook has been disabled (no `core.hooksPath`), so this pushes directly. If a hook is re-enabled and fails on Anthropic API credits, this is a code/spec push with no `*-dispatch.md` in range — `git push --no-verify` requires explicit orchestrator authorization.

- [ ] **Step 5: Open the PR**

```bash
gh pr create --base main --title "W3: Hedge RFQ Sanctions Gate Re-target + HB-3 Two-Domain Risk Flags" --body "Implements docs/superpowers/specs/2026-05-31-w3-hedge-rfq-sanctions-gate-design.md.

- Re-targets all 6 hedge RFQ admission sites from KYC to sanctions (fail-closed: only sanctions_status=clear admits; blocked/flagged/unscreened deny with HTTP 422 + audit-before-raise). Governance section 445-446.
- New sanctions_gate.assert_sanctions_clear (mirror of kyc_gate); kyc_gate.py deleted.
- HB-3 risk_flags re-aligned to two domains: hedge sanctions_regression_with_active_deals + commercial_compliance_regression_with_active_orders (kyc OR sanctions). Old kyc_regression_with_active_deals deprecated (kept in enum, no longer emitted). Governance section 1576-1583.
- Additive Postgres enum migration 050 (down_revision 049). No new API surface.
- Commercial order-gate intentionally left as governance section 617 prescribes (denies only blocked); fail-closed parity recorded as a candidate follow-up in spec section 9."
```
Then await Codex review (the `+1` reaction is the acceptance signal; `eyes` is processing, not acceptance).

---

## Self-review (completed by plan author)

**Spec coverage:** §2 gate primitive → T1; §5 RFQ retarget (6 sites) → T2; §6 delete kyc_gate + comment repoints + stale test → T3; §7 HB-3 enum + service + payload `dimensions` → T4 (enum) + T5 (service/queries/tests); §8 migration 050 → T4; §9 commercial order-gate follow-up → not implemented (correctly out of scope, recorded); §10 error semantics (422 + dual-session + 404) → T1; §11 testing (sanctions_gate unit, rfq route tests, HB-3 two-domain, full suite + fresh-postgres) → T1/T2/T5/T6; §12 RBAC unchanged → no task needed. Verification items: active-orders predicate resolved (`deleted_at IS NULL`, no status field) → T5; `attempted_purpose` tokens (`rfq_invite`/`refresh`) confirmed against `RFQInvitationPurpose` → T2 table; route-test sweep → T2 Step 7. ✔

**Placeholder scan:** the two `> NOTE:` blocks (T2 Step 1 RFQ create body, T5 Step 1 run signature) point the implementer at the real schema/fixtures to copy — not placeholders for missing logic; the asserted behavior is fully specified. No "TBD"/"add error handling"/uncoded steps. ✔

**Type consistency:** `assert_sanctions_clear(db, counterparty_id, *, gate_point, requesting_actor_sub, rfq_id=None, extra_payload=None) -> Counterparty` consistent T1/T2. `GatePoint` literals + `_EVENT_TYPE_BY_GATE` event strings (`rfq_{invitation,quote,award}_rejected_sanctions_not_cleared`) consistent T1/T2. `SanctionsStatus.clear` admit predicate consistent T1/T5. New enum members `sanctions_regression_with_active_deals` / `commercial_compliance_regression_with_active_orders` spelled identically in T4 (model), T4 (migration), T5 (service + tests). `Order.counterparty_id` / `Order.deleted_at` / no-status consistent T5. `CommercialPartner` constructor fields (`kind/name/country/kyc_status/sanctions_status/risk_rating`) match the W4-verified shape. ✔
