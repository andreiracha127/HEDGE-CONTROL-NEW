# W3 — Hedge RFQ Sanctions Gate Re-target + HB-3 Two-Domain Risk Flags (Design)

**Date:** 2026-05-31
**Wave:** W3 of the 7-wave commercial-partners / KYC effort (after W1 #112, W2 #113, W4 #114 merged).
**Branch (to create off `main`):** `w3/hedge-rfq-sanctions-gate`.
**Constitutional anchors:** `docs/governance.md` §445-446 (hedge RFQ sanctions gate), §617-625 (commercial order gate — *out of scope, left intact*), §770 (kyc→sanctions re-target scheduled for W3), §1576-1583 (HB-3 risk_flags two-domain re-alignment).

---

## 1. Goal

Re-target the hedge RFQ admission gate from KYC to **sanctions**, fail-closed, and re-align the HB-3 finance-pipeline `risk_flags` step to a two-domain compliance model. This is a **hard gate** wave (refusal = HTTP 422 + audit), in contrast to the WARN-not-block W4 LEI feature.

After W3, hedge RFQ admission reads `sanctions_status` (not `kyc_status`); `kyc_status` on hedge counterparties becomes a tracked-but-non-gating field on the RFQ path (governance §770 anticipates exactly this).

---

## 2. Scope

### In scope
1. Replace all **six** `assert_kyc_approved` call sites in `backend/app/services/rfq_service.py` with `assert_sanctions_clear`.
2. New module `backend/app/services/sanctions_gate.py` exposing `assert_sanctions_clear`.
3. **Delete** `backend/app/services/kyc_gate.py` and `backend/tests/test_rfq_kyc_gate.py`; update the two comment references that cite `kyc_gate`.
4. Re-align the HB-3 `risk_flags` step (`backend/app/services/finance_pipeline_service.py`) to the two-domain model.
5. Additive Alembic migration `050` adding two `flag_type` enum values.

### Out of scope (explicit non-goals)
- **Commercial order-gate stays as governance §617-625 prescribes** (denies only `sanctions_status == blocked`; `clear`/`flagged` pass the sanctions leg). Tightening it to fail-closed on `flagged`/`unscreened` would contradict binding governance and is recorded as a **candidate follow-up** (§9 below), to be done — if desired — via a dedicated governance amendment + wave.
- No change to the W2 sanctions screening / adjudication / re-screen logic.
- No change to `kyc_status` management routes/service (the field stays writable; it simply stops gating hedge RFQ admission).
- The `service:rfq_outbound` dispatcher (`rfq_orchestrator.py:573-590`) does NOT call the admission guard and is not modified.

---

## 3. Architecture

A thin `sanctions_gate` primitive (one external decision point) is called at each RFQ admission site, exactly mirroring the existing `kyc_gate` shape it replaces. The gate reads the authoritative `sanctions_status` field on `Counterparty`, which already reflects risk_manager adjudication-to-clear (W2 `adjudicate()` writes `entity.sanctions_status` directly — no adjudication-record join is needed). Refusals emit an HMAC audit event on a separate committed session before raising `HTTPException(422)`, so the rejection evidence survives the outer `unit_of_work` rollback.

The HB-3 `risk_flags` step gains a second domain: it surfaces sanctions regressions on hedge counterparties with active deals, and KYC-or-sanctions regressions on commercial partners with active orders.

```
RFQ lifecycle route ──> RFQService.{create|submit_quote|refresh|refresh_counterparty|award}
                              │
                              ├── assert_sanctions_clear(db, counterparty_id, gate_point=…, …)
                              │        │  reads Counterparty.sanctions_status
                              │        │  clear → return Counterparty
                              │        └  not clear → dual-session audit → HTTP 422
                              │
finance_pipeline (scheduler) ──> _step_risk_flags
                                       ├── hedge: sanctions_status != clear  ∧ active deals
                                       └── commercial: kyc_status != approved ∨ sanctions_status != clear  ∧ active orders
```

---

## 4. Component 1 — `sanctions_gate.py` (new)

Mirror `kyc_gate.assert_kyc_approved` field-for-field.

```python
GatePoint = Literal["rfq_invitation", "rfq_quote", "rfq_award"]

_EVENT_TYPE_BY_GATE = {
    "rfq_invitation": "rfq_invitation_rejected_sanctions_not_cleared",
    "rfq_quote":      "rfq_quote_rejected_sanctions_not_cleared",
    "rfq_award":      "rfq_award_rejected_sanctions_not_cleared",
}

def assert_sanctions_clear(
    db: Session,
    counterparty_id: uuid.UUID,
    *,
    gate_point: GatePoint,
    requesting_actor_sub: str | None,
    rfq_id: uuid.UUID | None = None,
    extra_payload: dict | None = None,
) -> Counterparty: ...
```

**Admission rule (fail-closed):** admit iff `cp.sanctions_status == SanctionsStatus.clear`. Deny `blocked`, `flagged` (unadjudicated), and `unscreened`. Adjudication-to-clear is already represented as `sanctions_status == clear` (W2), so no join to `SanctionsAdjudication` is required.

**Entity load:** `CounterpartyService.get_by_id(db, counterparty_id)` (NOT raw `db.get`) so a soft-deleted counterparty fails closed with **404** — identical to `kyc_gate`.

**Refusal path (dual-session, audit-before-raise):**
1. Open a separate `SessionLocal()`; call `AuditTrailService.record(..., commit=True)` with:
   - `entity_type="counterparty"`, `entity_id=counterparty_id`, `event_type=_EVENT_TYPE_BY_GATE[gate_point]`,
   - `payload_obj = {"counterparty_id", "sanctions_status_observed", "requesting_actor_sub", "rfq_id", **(extra_payload or {})}`.
   - At `rfq_invitation` sites, `extra_payload` carries `attempted_purpose ∈ {"rfq_invite", "refresh"}` (governance §446 payload key).
2. Close the audit session; `raise HTTPException(422, detail={"code": event_type, "counterparty_id", "sanctions_status_observed"})`.

The dual-session rationale is the same as `kyc_gate`: the route's `unit_of_work` rolls back the request session on any exception (including `HTTPException`), so the rejection audit must be committed independently.

---

## 5. Component 2 — `rfq_service.py` re-target

Swap the import at line ~53 (`from app.services.kyc_gate import assert_kyc_approved` → `from app.services.sanctions_gate import assert_sanctions_clear`) and update each call site, preserving the in-scope arguments already present:

| Site (approx line) | Method | `gate_point` | `attempted_purpose` (extra_payload) |
|---|---|---|---|
| 580 | `create` | `rfq_invitation` | `rfq_invite` |
| 853 | `submit_quote` | `rfq_quote` | — |
| 1029 | `refresh` | `rfq_invitation` | `refresh` |
| 1297 | `refresh_counterparty` | `rfq_invitation` | `refresh` |
| 1469 | `award` (spread check) | `rfq_award` | — |
| 1583 | `award` (trade check) | `rfq_award` | — |

The exact `attempted_purpose` token at the refresh sites is confirmed against the `RFQInvitationPurpose` enum during planning (§8). Each call already has `counterparty_id`, `actor_sub`, and `rfq.id` in scope per the Codex survey.

---

## 6. Component 3 — delete `kyc_gate.py`

`assert_kyc_approved` is called only from `rfq_service.py` (the six sites) and `test_rfq_kyc_gate.py`. After the re-target it is dead.

- Delete `backend/app/services/kyc_gate.py` and `backend/tests/test_rfq_kyc_gate.py`.
- Repoint the two comment references — `counterparty_service.py:17` and `sanctions_screening_service.py:5` — from `kyc_gate` to `sanctions_gate` (both reference the dual-session pattern, which now lives in `sanctions_gate.py`; the commercial order gate in `order_service.py` also retains the live pattern).
- Update the stale assertions in `backend/tests/test_counterparty_kyc_transition.py` (lines ~103-104 note the W3 re-target; lines ~243-271 mock the KYC gate on `submit_quote`). These move to sanctions or are removed where they assert the now-deleted KYC admission behavior.

---

## 7. Component 4 — HB-3 two-domain `risk_flags`

### Enum (`backend/app/models/finance_pipeline.py`)
Current members: `missing_mtm_price`, `unhedged_exposure_over_guardrail`, `kyc_regression_with_active_deals`, `workflow_approval_pending_past_expiry`.

- **ADD** `sanctions_regression_with_active_deals` (hedge).
- **ADD** `commercial_compliance_regression_with_active_orders` (commercial; KYC or sanctions).
- **KEEP** `kyc_regression_with_active_deals` as a deprecated member that is **no longer emitted** (Postgres enum value removal requires recreating the type and is intentionally avoided).

### Service (`backend/app/services/finance_pipeline_service.py`)
- Replace `_query_kyc_regressions_with_active_deals` with `_query_sanctions_regressions_with_active_deals`: hedge `Counterparty` rows with `sanctions_status != SanctionsStatus.clear`, `is_deleted == False`, restricted to counterparties with active deals (reuse the existing `_active_contracts` / active-counterparty-id derivation).
- Add `_query_commercial_compliance_regressions_with_active_orders`: `CommercialPartner` rows with (`kyc_status != approved` OR `sanctions_status != clear`), `is_deleted == False`, restricted to partners with active orders (active-order predicate finalized in §8).
- `_step_risk_flags` emits one `FinancePipelineRiskFlag` per surfaced anomaly across both domains:
  - hedge → `sanctions_regression_with_active_deals`, payload `{counterparty_id, sanctions_status_observed}`.
  - commercial → **one** `commercial_compliance_regression_with_active_orders` row **per partner** (never two rows for the same partner), payload `{commercial_partner_id, dimensions, kyc_status_observed, sanctions_status_observed}` where `dimensions` is the non-empty subset of `["kyc","sanctions"]` that regressed. A partner regressing on both dimensions yields a single row with `dimensions == ["kyc","sanctions"]`. The payload MUST make every offending dimension reconstructable.
- Zero flags remains a valid outcome and does not block run completion (unchanged HB-3 invariant).

---

## 8. Component 5 — Migration `050` (additive Postgres enum)

- `down_revision = "049_commercial_partners_foundation"`.
- Add the two new values to the `flag_type` enum. On Postgres use explicit `ALTER TYPE … ADD VALUE` (named enum, no double-create, idempotent-safe); on SQLite the column is a string variant, so the upgrade is a no-op there. Must pass the `alembic-fresh-postgres` CI job.
- No data backfill: existing `FinancePipelineRiskFlag` rows are unaffected; the deprecated `kyc_regression_with_active_deals` value remains in the type.

---

## 9. Candidate follow-up (NOT in W3)

**Commercial order-gate fail-closed parity.** Today the order gate (`order_service.py:370-385`) denies only `sanctions_status == blocked`; a `kyc_status == approved` partner that was re-screened to `flagged` post-approval can still create orders. This is a *deliberate* governance choice (§617-625: business continuity on unconfirmed fuzzy matches, resolved via adjudication; outbound RFQ is higher-stakes than an internal order record). Tightening it requires a governance amendment to §617-625 with its own rationale, then a dedicated wave. Recorded here so it is not silently lost.

---

## 10. Error handling

- Refusal is **HTTP 422** with `detail.code = <event_type>` for human-issued paths (and the equivalent application-layer rejection for any service-driven path).
- The rejection audit event is recorded **before** the rejection response, HMAC-signed, on a separate committed session (dual-session), so it survives the request rollback.
- Missing / soft-deleted counterparty → **404** (fail-closed via the service getter).
- No silent fallback: the gate never admits on an indeterminate sanctions state; only `clear` admits.

---

## 11. Testing

- `backend/tests/test_sanctions_gate.py` (new): the primitive — `clear` admits; adjudicated-to-`clear` admits; `flagged`/`unscreened`/`blocked` each deny with the correct per-gate-point event; 404 on soft-deleted/missing; rejection audit row committed on the separate session and present after the simulated rollback.
- `backend/tests/test_rfq_sanctions_gate.py` (new, replaces `test_rfq_kyc_gate.py`): the six admission sites refuse non-`clear` counterparties at create / submit_quote / refresh / refresh_counterparty / award (spread + trade), with the correct event types and 422.
- `backend/tests/test_counterparty_kyc_transition.py`: stale KYC-gate assertions updated/removed.
- HB-3 tests: hedge sanctions regression with active deals → `sanctions_regression_with_active_deals`; commercial KYC-or-sanctions regression with active orders → `commercial_compliance_regression_with_active_orders` (offending dimension in payload); clean dataset → zero flags; deprecated `kyc_regression_with_active_deals` no longer emitted.
- Full backend suite green (modulo the known ~26 pre-existing environmental failures) + `alembic-fresh-postgres` gate green.

### Verification items to resolve during planning (non-blocking)
1. Exact "active orders" predicate for commercial partners (Order model status enum + soft-delete flag).
2. Confirm the `attempted_purpose` token expected at the two refresh sites against `RFQInvitationPurpose`.
3. Sweep for any route-level test asserting the old `*_rejected_kyc_not_approved` codes beyond the two files named in §6.

---

## 12. RBAC / authority (unchanged)

The re-target does not change route gates: RFQ lifecycle routes remain `risk_manager`-authored (and the `service:rfq_outbound` identity for the dispatcher, which does not call the admission guard). `trader` cannot touch RFQs (governance AUTHORIZATION MATRIX). The audit log remains auditor-only.
