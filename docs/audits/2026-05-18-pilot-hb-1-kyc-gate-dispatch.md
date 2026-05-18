# HB-1 — Counterparty KYC Gate Implementation Dispatch

Cycle: Pilot Hard Blockers (June 2026 launch)
Wave: HB-1
Constitutional anchor: `docs/governance.md` "Counterparty KYC gate (binding, Pilot Hard Blocker 1)" subsection inside AUTHORIZATION MATRIX (landed via PR #93, merge commit `d4e946eb`)
Pilot brief anchor: `docs/2026-05-tech-lead-executive-analysis.md` §2 HB-1 (landed via PR #89, scope-bound via PR #92)
Findings closed by this wave: HB-1 (sole)
Status: DRAFT

---

## §1 Scope

This PR implements the Counterparty KYC gate constitutionally bound in the merged amendment. Three service-layer guards refuse RFQ-lifecycle operations when the target counterparty's `kyc_status != approved`: (a) admission-purpose `RFQInvitation` row creation (`rfq_invite` and `refresh`), (b) quote ingestion (both the human-issued `POST /rfqs/{rfq_id}/quotes` and the LLM-parsed inbound path downstream of `webhook_processor`), (c) award (`POST /rfqs/{rfq_id}/actions/award`). One new authenticated mutation endpoint (`POST /counterparties/{counterparty_id}/kyc-status`) provides the risk_manager-only transition path with mandatory reason. Four new HMAC-signed audit event types capture every gate rejection and every status transition. Outbox/notification `RFQInvitationPurpose` values (`reject_quote`, `award_notify`, `reject_notify`) are EXEMPT — they persist regardless of `kyc_status` per the amendment's partition rule. Backend-only change set; minimum-viable frontend consumer patch ships in the same PR to keep the new endpoint end-to-end testable.

## §2 Boundary

This PR does NOT:

- Add an Alembic migration. The `Counterparty.kyc_status` column and `KycStatus` enum already exist (`backend/app/models/counterparty.py:23-27` for the enum; `:66-70` for the mapped column with `nullable=False`, `default=KycStatus.pending`). The amendment's Schema clause binds NO migration as a requirement. Adding one is a P1 Tipo II self-defeat.
- Implement the full KYC documentary suite (`KycDocument`, `CreditCheck`, `KycCheck` models). These remain P1 post-pilot per `docs/GAP_ANALYSIS_LEGACY_VS_NEW.md` §2.1.
- Gate outbox/notification `RFQInvitationPurpose` writes (`reject_quote`, `award_notify`, `reject_notify`). The amendment partitions the enum explicitly: these three are EXEMPT. The guard MUST NOT intercept invocations at `rfq_service.py:1188` (reject_quote), `rfq_orchestrator.py:1826` (award_notify), `rfq_orchestrator.py:1901` (reject_notify).
- Implement workflow approval / multi-signatory authorization for `kyc_status` transitions. HB-2 (Workflow Approvals) is the right home for threshold-based two-signatory rules; HB-1 binds risk_manager-only single-actor mutations with mandatory reason.
- Persist the 8 pilot counterparties' `kyc_status = approved`. That is operational pre-condition for pilot launch (recorded in pilot brief §7 risk_manager sign-off), executed via the new `POST /counterparties/{counterparty_id}/kyc-status` endpoint BEFORE pilot day 1. The PR's acceptance criteria do not gate on those 8 rows existing in any database state.
- Modify the trader's per-type Counterparty CRUD on customer/supplier rows for non-KYC fields (contact, address, payment terms, etc.). Trader retains those mutations per the matrix; only `kyc_status` is carved out.
- Add KYC validation on Counterparty creation. The amendment leaves default `kyc_status = pending` intact — counterparties enter the platform un-admitted by design, and the new transition endpoint is the only path to `approved`. POST /counterparties continues to accept new rows at default state.

## §3 Pre-step (manual)

Empty. The amendment's Schema clause prescribes no schema change; no env-var rotation, no dashboard config, no manual SQL is required before the executor writes code.

(The operational pre-condition of persisting the 8 pilot counterparties' `kyc_status = approved` happens AFTER this PR merges, via the new endpoint shipped here. It belongs to pilot launch operations, not to the executor's pre-step.)

## §4 Backend changes

### §4.1 New helper: `assert_kyc_approved` in `backend/app/services/kyc_gate.py` (new file)

Create a new module `backend/app/services/kyc_gate.py` holding the gate primitive and gate exception. Centralizing the helper means every gate site emits the same audit shape and raises the same HTTPException — no per-site drift.

```python
# backend/app/services/kyc_gate.py
"""KYC gate primitive for RFQ-lifecycle admission and quote ingestion.

Constitutional anchor: docs/governance.md "Counterparty KYC gate
(binding, Pilot Hard Blocker 1)" subsection of AUTHORIZATION MATRIX.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.counterparty import Counterparty, KycStatus
from app.services.audit_trail_service import AuditTrailService
from app.utils.payload_canonical import dumps_canonical  # if not present, use json.dumps with sort_keys=True

GatePoint = Literal["rfq_invitation", "rfq_quote", "rfq_award"]

_EVENT_TYPE_BY_GATE = {
    "rfq_invitation": "rfq_invitation_rejected_kyc_not_approved",
    "rfq_quote": "rfq_quote_rejected_kyc_not_approved",
    "rfq_award": "rfq_award_rejected_kyc_not_approved",
}


def assert_kyc_approved(
    db: Session,
    counterparty_id: uuid.UUID,
    *,
    gate_point: GatePoint,
    requesting_actor_sub: str | None,
    rfq_id: uuid.UUID | None = None,
    extra_payload: dict | None = None,
) -> Counterparty:
    """Refuse the operation if counterparty.kyc_status != approved.

    On refusal:
      1. Records an HMAC-signed audit event with the per-gate event_type.
      2. Raises HTTPException(422) for human-issued paths; service-driven
         callers (e.g. service:rfq_outbound) translate the same exception
         to their application-layer rejection.

    Returns the loaded Counterparty when status is approved.
    """
    cp = db.get(Counterparty, counterparty_id)
    if cp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Counterparty not found",
        )
    if cp.kyc_status == KycStatus.approved:
        return cp

    event_type = _EVENT_TYPE_BY_GATE[gate_point]
    payload = {
        "counterparty_id": str(counterparty_id),
        "kyc_status_observed": cp.kyc_status.value,
        "requesting_actor_sub": requesting_actor_sub,
        "rfq_id": str(rfq_id) if rfq_id is not None else None,
        **(extra_payload or {}),
    }
    AuditTrailService.record(
        db,
        event_id=uuid.uuid4(),
        entity_type="counterparty",
        entity_id=counterparty_id,
        event_type=event_type,
        payload_raw=dumps_canonical(payload),
        payload_obj=payload,
        commit=False,  # caller's unit_of_work handles transaction boundary
    )
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": event_type,
            "counterparty_id": str(counterparty_id),
            "kyc_status_observed": cp.kyc_status.value,
        },
    )
```

Verification of imports against current HEAD:
- `AuditTrailService.record` signature at `backend/app/services/audit_trail_service.py:74-119` accepts `commit: bool = True`; the executor MUST pass `commit=False` so the rejection audit row lands in the same transaction the gate caller manages, allowing the HTTPException rollback to drop the failed mutation while keeping the rejection evidence visible after the route's `unit_of_work` flush. Confirm the `unit_of_work` pattern preserves the audit row on HTTPException at the route boundary; if the existing pattern rolls back the audit row too, the executor MUST emit the audit event in a separate session/transaction (see `webhook_processor` for the dual-session pattern).
- `dumps_canonical` import path: if `app/utils/payload_canonical.py` does not exist at HEAD (executor MUST verify with `find_symbol` first), substitute the existing canonicalization helper already used by `AuditTrailService.record` internally — `normalize_payload_raw` at `backend/app/services/audit_trail_service.py` (the body of `record()` calls it; cite the file for the executor). Do NOT invent a new helper.
- `Literal` typing import is stdlib `typing.Literal`.

### §4.2 Gate sites in `backend/app/services/rfq_service.py`

Five guard insertions, all calling `assert_kyc_approved` BEFORE the `RFQInvitation` row construction (for admission purposes) or BEFORE the quote persistence / award update (for quote and award). Cite line numbers refer to HEAD `d4e946eb` (post-amendment-merge baseline); the executor MUST re-verify offsets on branch HEAD.

#### §4.2.1 `RFQService.create` (lines 455-711)

The method's loop at lines ~625-647 iterates pre-resolved counterparties and constructs `RFQInvitation` rows with `purpose=RFQInvitationPurpose.rfq_invite` (line 640). Insert the gate IMMEDIATELY before line 630 (the `row = RFQInvitation(` line). On a single-counterparty loop iteration that fails the gate, the gate raises HTTPException(422) and the surrounding `unit_of_work` rolls back the partial RFQ row + any earlier invitation rows; the audit event for the rejection persists. If the institutional intent is "create the RFQ but skip the failing counterparties", that is OUT of HB-1 scope — HB-1 binds fail-closed-per-call. The dispatch executor MUST NOT implement skip-and-continue.

Concrete shape:
```python
# Inside the loop iterating resolved counterparties, before the
# RFQInvitation construction at line ~630:
assert_kyc_approved(
    session,
    cp.id,
    gate_point="rfq_invitation",
    requesting_actor_sub=actor_sub,  # threaded from route
    rfq_id=rfq.id if rfq.id else None,  # rfq may not be flushed yet
    extra_payload={"attempted_purpose": "rfq_invite"},
)
row = RFQInvitation(
    rfq_id=rfq.id,
    ...
    purpose=RFQInvitationPurpose.rfq_invite,
    ...
)
```

Method signature change: `RFQService.create` MUST accept an `actor_sub: str` keyword argument so the gate has the requesting actor identity to log. Trace every call site of `RFQService.create` (route handler at `backend/app/api/routes/rfqs.py:102` POST `""`) and thread `actor_sub: str = Depends(get_current_actor_sub)` through. Cite `backend/app/core/auth.py:417-433` for the `get_current_actor_sub` definition.

#### §4.2.2 `RFQService.refresh` (lines 974-1097)

`RFQInvitation` row at line ~1047 with `purpose=RFQInvitationPurpose.refresh` (line 1057). Insert the gate IMMEDIATELY before line 1047. Same `actor_sub` threading rule. The `extra_payload` for the rejection audit MUST set `"attempted_purpose": "refresh"`.

#### §4.2.3 `RFQService.refresh_counterparty` (lines 1269-1382)

`RFQInvitation` row at line ~1332 with `purpose=RFQInvitationPurpose.refresh` (line 1342). Insert the gate IMMEDIATELY before line 1332. Same threading rule. `extra_payload`: `"attempted_purpose": "refresh"`.

#### §4.2.4 `RFQService.submit_quote` (lines 816-919)

Gate the quote ingestion: load the inbound quote's claimed `counterparty_id` from `payload`, call `assert_kyc_approved` with `gate_point="rfq_quote"`. Place the gate at the top of the method body, AFTER any payload validation that surfaces parser errors but BEFORE any persistence side effect. The `extra_payload` for the audit MUST include:
- `rejection_path`: `"human_post"` for the route-issued path, `"webhook_inbound_llm"` for the LLM-parsed path
- `inbound_message_id`: nullable; populated only when the call originated from `webhook_processor` (the human path passes `None`)
- `requesting_actor_sub` from the call site; populated for human path (risk_manager sub), nullable for inbound/LLM path

Method signature: add `actor_sub: str | None = None` and `inbound_message_id: uuid.UUID | None = None` kwargs. Default `None` for both keeps backward compatibility with any internal caller that does not need them, but the human-issued route MUST pass `actor_sub`, and the webhook path MUST pass `inbound_message_id`.

Route handler at `backend/app/api/routes/rfqs.py:266` (POST `/{rfq_id}/quotes`) MUST be amended to thread `actor_sub = Depends(get_current_actor_sub)` and pass it into `RFQService.submit_quote(..., actor_sub=actor_sub)`. Webhook caller in `backend/app/services/webhook_processor.py` MUST pass `inbound_message_id=delivery.inbound_message_id` (or the equivalent — executor verifies the actual webhook persistence flow).

#### §4.2.5 `RFQService.award` (lines 1384-1619)

Gate at the top of the award path, AFTER the awarded `quote` is loaded but BEFORE any state mutation on `RFQ` or `HedgeContract`. The amendment requires re-checking `kyc_status` at award moment even if the original invitation was created when approved — so the gate cannot be skipped just because an invitation succeeded earlier.

```python
# After loading the awarded quote and its counterparty:
assert_kyc_approved(
    session,
    quote.counterparty_id,
    gate_point="rfq_award",
    requesting_actor_sub=actor_sub,
    rfq_id=rfq.id,
    extra_payload={"quote_id": str(quote.id)},
)
```

Route at `backend/app/api/routes/rfqs.py:474` (POST `/{rfq_id}/actions/award`) MUST thread `actor_sub` per the same pattern. Verify the existing route already uses `Depends(get_current_actor_sub)` (per Cluster 2 backend hardening per `feedback_executor_false_completion_pattern` memory references); if so, the change is purely a kwarg pass-through.

### §4.3 New endpoint: `POST /counterparties/{counterparty_id}/kyc-status`

Authoritative path for `kyc_status` transitions. Risk_manager-only per the amendment's "Status transitions" subsection.

#### §4.3.1 New schema in `backend/app/schemas/counterparty.py`

```python
class KycStatusTransitionRequest(BaseModel):
    new_status: KycStatus
    reason: str = Field(min_length=8, max_length=512)
```

Verify against existing `backend/app/schemas/counterparty.py` — if `KycStatus` is not yet re-exported from the schemas module, add the import from `backend/app/models/counterparty.py`.

#### §4.3.2 New service method `CounterpartyService.set_kyc_status`

```python
@staticmethod
def set_kyc_status(
    db: Session,
    counterparty_id: uuid.UUID,
    *,
    new_status: KycStatus,
    reason: str,
    actor_sub: str,
) -> Counterparty:
    cp = db.get(Counterparty, counterparty_id)
    if cp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Counterparty not found",
        )
    previous_status = cp.kyc_status
    cp.kyc_status = new_status

    payload = {
        "counterparty_id": str(counterparty_id),
        "previous_status": previous_status.value,
        "new_status": new_status.value,
        "transition_actor_sub": actor_sub,
        "reason": reason,
    }
    AuditTrailService.record(
        db,
        event_id=uuid.uuid4(),
        entity_type="counterparty",
        entity_id=counterparty_id,
        event_type="counterparty_kyc_status_changed",
        payload_raw=dumps_canonical(payload),
        payload_obj=payload,
        commit=False,
    )
    return cp
```

Insert in `backend/app/services/counterparty_service.py` between `update` (lines 70-88) and `soft_delete` (lines 90-101). Same `dumps_canonical` import discipline as §4.1.

#### §4.3.3 New route in `backend/app/api/routes/counterparties.py`

```python
@router.post(
    "/{counterparty_id}/kyc-status",
    response_model=CounterpartyRead,
    status_code=status.HTTP_200_OK,
)
@limiter.limit(RATE_LIMIT_MUTATION)
def transition_kyc_status(
    counterparty_id: UUID,
    payload: KycStatusTransitionRequest,
    request: Request,
    _: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    with unit_of_work(session, request=request):
        cp = CounterpartyService.set_kyc_status(
            session,
            counterparty_id,
            new_status=payload.new_status,
            reason=payload.reason,
            actor_sub=actor_sub,
        )
    return CounterpartyRead.model_validate(cp)
```

Per the amendment, `require_role("risk_manager")` is the ONLY allowed gate. `require_any_role("trader", "risk_manager")` would admit trader and silently break the amendment. The executor MUST NOT use `require_any_role` here.

### §4.4 Reject `kyc_status` in existing PATCH `/counterparties/{counterparty_id}`

The existing PATCH endpoint (at `backend/app/api/routes/counterparties.py`, current handler — executor verifies file:line via `find_symbol`) accepts a `CounterpartyUpdate` payload. If the payload includes a `kyc_status` field today (executor verifies the schema), the request MUST be rejected with HTTP 422 directing the caller to use the new dedicated endpoint. The rejection path emits an audit event of type `counterparty_kyc_status_change_via_wrong_endpoint` with payload `{counterparty_id, attempted_status, requesting_actor_sub}` for traceability.

If `CounterpartyUpdate` does NOT expose `kyc_status` at HEAD (likely, since trader is supposed to have per-type CRUD without KYC mutation rights), this is a no-op — verify and skip. Either way, the schema MUST NOT add `kyc_status` as a settable field.

### §4.5 Service-identity scope clarification (defensive note, not a code change)

Per the amendment, `service:rfq_outbound` is the service identity for the outbound worker. The gate applies to it via §4.2.1/§4.2.2/§4.2.3 (same `RFQService.create`/`refresh`/`refresh_counterparty` code paths). If the outbound worker invokes the service methods with its own JWT context, `actor_sub` will resolve to `service:rfq_outbound` and the audit row will attribute the rejection to the service. No additional code change required IF the outbound worker is already authenticating via the service-identity JWT pattern (Cluster 2 backend hardening). Executor verifies via `grep -rn "service:rfq_outbound" backend/app/` and confirms.

## §5 Database / Alembic changes

NONE.

The amendment's Schema clause is binding: "NO alembic migration is required for the gate itself. The `Counterparty.kyc_status` column and `KycStatus` enum already exist (introduced in the Phase A1 Counterparty model creation). The HB-1 implementation dispatch therefore prescribes service-layer guards + audit-event wiring + tests; it does NOT prescribe a model or migration change for the gate."

Verification: `cd backend && python -m alembic heads` MUST return `045_market_data_governance_columns (head)` both BEFORE and AFTER this PR. The acceptance criteria §10 makes this measurable.

If the executor finds an institutional need for a migration (e.g. an index on `kyc_status` for query performance at pilot scale), that is a separate ticket post-pilot — HB-1 is fail-closed on schema changes within this PR's scope.

## §6 Frontend changes (minimum-viable consumer)

Per `feedback_dispatch_transport_partner_clause`: §4.3.3 ships a new backend endpoint. To keep the contract end-to-end testable in the same PR, ship the minimum-viable frontend consumer.

### §6.1 Regenerate API types

`cd frontend-svelte && npm run api:types` — picks up the new `POST /counterparties/{counterparty_id}/kyc-status` route + `KycStatusTransitionRequest` schema in `frontend-svelte/src/lib/api/schema.d.ts`. Commit the regenerated file.

CI guard `npm run api:types:check` MUST pass on push.

### §6.2 KYC status transition UI (minimum viable)

In the existing Counterparty detail page (`frontend-svelte/src/routes/(protected)/counterparties/[id]/+page.svelte` — executor verifies path), add a risk_manager-only section with:
- Current `kyc_status` display
- Dropdown for `new_status` (one of `approved`, `pending`, `expired`, `rejected`)
- Mandatory text input for `reason` (client-side validation: minimum 8 characters)
- "Apply transition" button that calls `POST /counterparties/{id}/kyc-status` via the typed client (`src/lib/api/client.ts`)

UI visibility gating:
- The transition section is rendered ONLY when the logged-in user has the `risk_manager` role (read from the Clerk session/JWT claims via the existing role-check helper in `frontend-svelte/src/lib/auth/`).
- Trader and auditor sessions MUST NOT see the section — render nothing for them (NOT a disabled button; the absence avoids existence-leak of the capability).

Error handling: on HTTP 422 from the backend (e.g. reason too short), display the backend's error detail inline. On 403 (server-side role check), display a generic "permission denied" toast — this path should be unreachable for risk_managers but is the defense-in-depth for token tampering.

### §6.3 KYC-rejection feedback on RFQ flows (out of HB-1)

The frontend pages that trigger RFQ create / quote submission / award (under `frontend-svelte/src/routes/(protected)/rfq/`) MAY receive a 422 with `code: rfq_*_rejected_kyc_not_approved` from the new gate. They MUST handle the 422 gracefully (display the backend's `detail` to the user) but DO NOT need new UI flows for the rejection state — the existing error-display pattern in those pages suffices. If the existing pattern silently swallows 422s (unlikely but executor verifies), that is a defensive fix the executor includes in this PR; otherwise no change.

## §7 Tests

### §7.1 New test file `backend/tests/test_rfq_kyc_gate.py`

Comprehensive coverage for all five service-layer gate sites, all four KycStatus members, and the audit-event recording contract. Minimum suite:

- `test_create_rejects_pending_counterparty` — RFQService.create raises 422 + audit event `rfq_invitation_rejected_kyc_not_approved` recorded with `attempted_purpose: rfq_invite`
- `test_create_rejects_expired_counterparty` — same as above but status=expired
- `test_create_rejects_rejected_counterparty` — same as above but status=rejected
- `test_create_admits_approved_counterparty` — happy path, RFQ + invitation rows persist, no rejection audit emitted
- `test_create_rolls_back_partial_invitations` — multi-counterparty create where one counterparty fails the gate; the entire RFQ rolls back; only the one rejection audit persists
- `test_refresh_rejects_non_approved_counterparty` — RFQService.refresh raises 422; audit `attempted_purpose: refresh`
- `test_refresh_counterparty_rejects_non_approved` — RFQService.refresh_counterparty raises 422; audit `attempted_purpose: refresh`
- `test_submit_quote_rejects_non_approved_human_path` — POST /rfqs/{id}/quotes returns 422 + audit `rejection_path: human_post` + `requesting_actor_sub` populated
- `test_submit_quote_rejects_non_approved_inbound_path` — webhook-driven submit_quote call returns rejection + audit `rejection_path: webhook_inbound_llm` + `inbound_message_id` populated, `requesting_actor_sub: null`
- `test_award_rejects_non_approved_at_award_moment` — RFQ + invitation created when counterparty was approved; counterparty then transitioned to expired; award returns 422 + audit `rfq_award_rejected_kyc_not_approved`
- `test_award_admits_when_still_approved` — happy path; award proceeds; no rejection audit
- `test_gate_audit_event_is_hmac_signed` — verifies the audit row's `signature` field is populated and validates via `AuditTrailService.verify_event`

Use the existing test-isolation pattern: `tests/conftest.py` autouse fixture provides a fresh SQLite-in-memory DB; helpers in `backend/tests/auth_token_helpers.py` mint test JWTs with the required role claim.

### §7.2 New test file `backend/tests/test_counterparty_kyc_transition.py`

Coverage for the new `POST /counterparties/{counterparty_id}/kyc-status` endpoint:

- `test_risk_manager_can_transition_pending_to_approved` — happy path; audit `counterparty_kyc_status_changed` with `previous_status: pending`, `new_status: approved`, `transition_actor_sub` populated, `reason` echoed
- `test_risk_manager_can_transition_approved_to_expired` — revocation path
- `test_risk_manager_can_transition_approved_to_rejected` — revocation path
- `test_risk_manager_can_transition_expired_to_approved` — renewal path (explicit, no auto-promotion)
- `test_risk_manager_can_transition_rejected_to_approved` — reinstatement path
- `test_trader_cannot_transition` — token with `{trader}` role → 403 from the route gate, NO audit event recorded (route gate fires before service)
- `test_auditor_cannot_transition` — token with `{auditor}` role → 403, NO audit event
- `test_mixed_role_token_rejected_at_jwt_layer` — `{trader, auditor}` token → 401 from JWT validator before route reached
- `test_reason_minimum_length_enforced` — reason length 7 → 422 from Pydantic Field validator; NO audit event (validation fails before service called)
- `test_reason_maximum_length_enforced` — reason length 513 → 422
- `test_nonexistent_counterparty_returns_404` — random UUID → 404, NO audit event
- `test_transition_audit_event_is_hmac_signed` — verifies signature

### §7.3 RBAC matrix tests in `backend/tests/test_rbac_matrix_enforcement.py`

Append entries for the new route. Per the existing test pattern (which the executor sweeps via `grep -n "counterparties" backend/tests/test_rbac_matrix_enforcement.py`):

- `POST /counterparties/{id}/kyc-status` — accept: risk_manager. Reject: trader (403), auditor (403), service-identities (403), unauthenticated (401).

### §7.4 Trader per-type CRUD regression (defensive)

Add a test asserting that the existing PATCH `/counterparties/{counterparty_id}` continues to admit trader on customer/supplier rows for non-KYC fields. This guards against the dispatch's exception clause (§4.4) accidentally over-broadening to reject all trader PATCH calls.

- `test_trader_can_patch_customer_contact_info` — sanity check that the trader's existing per-type CRUD still works on non-KYC fields.

### §7.5 Frontend tests

Vitest coverage for the new component (`Counterparties.test.ts` or a new spec file). Minimum:
- `kyc_status` section renders for risk_manager
- `kyc_status` section does NOT render for trader or auditor
- "Apply transition" button calls the typed client with the correct payload shape
- Reason < 8 chars disables submit button client-side

E2E Playwright is NOT required for this PR — the surface is institutional/internal and the backend tests cover the contract. If the executor finds the existing E2E suite has a counterparty-flow scenario, extending it is encouraged but not blocking.

## §8 Audit-trail emission

Four new audit `event_type` values land in this PR. All emitted via `AuditTrailService.record(...)` (cite `backend/app/services/audit_trail_service.py:74-119` for the signature). All HMAC-signed by the existing recorder (`AUDIT_SIGNING_KEY` required in prod/staging per `app/services/audit_trail_service.py` MissingAuditSigningKey hard-fail).

| event_type | emitted from | entity_type | payload shape (binding per amendment) |
|---|---|---|---|
| `rfq_invitation_rejected_kyc_not_approved` | `assert_kyc_approved` (§4.1) called from §4.2.1/2/3 | `counterparty` | `{counterparty_id, kyc_status_observed, requesting_actor_sub, rfq_id (nullable), attempted_purpose ∈ {rfq_invite, refresh}}` |
| `rfq_quote_rejected_kyc_not_approved` | `assert_kyc_approved` called from §4.2.4 | `counterparty` | `{counterparty_id, kyc_status_observed, rfq_id, inbound_message_id (nullable for human path), rejection_path ∈ {human_post, webhook_inbound_llm}, requesting_actor_sub (nullable for inbound/LLM path)}` |
| `rfq_award_rejected_kyc_not_approved` | `assert_kyc_approved` called from §4.2.5 | `counterparty` | `{counterparty_id, kyc_status_observed, rfq_id, quote_id, requesting_actor_sub}` |
| `counterparty_kyc_status_changed` | `CounterpartyService.set_kyc_status` (§4.3.2) | `counterparty` | `{counterparty_id, previous_status, new_status, transition_actor_sub, reason}` |

Defensive emission for §4.4 (existing PATCH attempt to set kyc_status):

| event_type | emitted from | entity_type | payload shape |
|---|---|---|---|
| `counterparty_kyc_status_change_via_wrong_endpoint` | PATCH `/counterparties/{id}` rejection path (§4.4) | `counterparty` | `{counterparty_id, attempted_status, requesting_actor_sub}` |

This last event is added only if the executor's verification of `CounterpartyUpdate` schema finds that `kyc_status` is currently exposed there. If not exposed, the event type is unused and not added.

Audit emission timing rule (binding): the rejection audit MUST land in the audit table BEFORE the HTTPException is raised. The amendment's wording — "MUST be recorded BEFORE the rejection response is returned" — is reproduced verbatim in §8 to guide the executor. Per §4.1, the emission uses `commit=False` so that the outer `unit_of_work` flushes the rejection row alongside the rollback of the failed mutation. If the executor finds that the existing `unit_of_work` pattern rolls back the audit row on HTTPException, the executor MUST switch to a dual-session pattern (separate `Session` for audit emission with its own commit, mirroring `webhook_processor` for the rejection-evidence persistence) and document the choice in the PR body.

No companion audit-trail evidence PR ships separately for HB-1 — the audit events are internal to this dispatch's scope.

## §9 Docs

No `docs/governance.md` change. The constitutional amendment was merged in PR #93 and is the source of truth for this dispatch.

No `docs/systemconstitucion.md` change.

No `docs/runbook-railway.md` change (no infra change in this PR).

`CLAUDE.md` change: NOT REQUIRED. The KYC gate is a constitutional rule already covered by the AUTHORIZATION MATRIX in `docs/governance.md`; CLAUDE.md does not need to repeat it.

`docs/GAP_ANALYSIS_LEGACY_VS_NEW.md` change: NOT REQUIRED in this PR. After merge, the next GAP refresh will move §2.1 KYC Gate from "ABSENT" to "LANDED (HB-1)" — that update is part of the HB-1 closure memo, not this PR.

`docs/2026-05-tech-lead-executive-analysis.md` (pilot brief) change: NOT REQUIRED. The brief's §2 HB-1 already prescribes this scope; the executor PR closes the HB rather than amending the brief. Brief §7 sign-off acknowledges HB-1 closed when this PR merges.

## §10 Acceptance criteria

Every item below is verifiable post-merge by running the cited command against the merged HEAD.

1. **Alembic head unchanged.** `cd backend && python -m alembic heads` returns exactly `045_market_data_governance_columns (head)`. No new revision file under `backend/alembic/versions/`. (Enforces §5.)
2. **Gate primitive exists.** `find_symbol assert_kyc_approved` returns a single match at `backend/app/services/kyc_gate.py`. (Enforces §4.1.)
3. **All 5 admission-purpose call sites use the gate.** `grep -nE "assert_kyc_approved|RFQInvitationPurpose\.(rfq_invite|refresh)" backend/app/services/rfq_service.py` shows the gate call IMMEDIATELY preceding each of the 3 admission-purpose `RFQInvitation` constructions; `grep -nE "assert_kyc_approved" backend/app/services/rfq_service.py` returns ≥5 occurrences (3 for invitation create paths + 1 for submit_quote + 1 for award). (Enforces §4.2.)
4. **Outbox purposes remain ungated.** `grep -nB5 "RFQInvitationPurpose\.(reject_quote|award_notify|reject_notify)" backend/app/services/rfq_service.py backend/app/services/rfq_orchestrator.py` shows NO `assert_kyc_approved` call in the 5 preceding lines of each outbox-purpose row construction at `rfq_service.py:1188`, `rfq_orchestrator.py:1826`, `rfq_orchestrator.py:1901`. (Enforces §2 boundary + amendment partition rule.)
5. **New endpoint exists.** `grep -n "kyc-status" backend/app/api/routes/counterparties.py` returns the new route decorator. (Enforces §4.3.3.)
6. **New endpoint is risk_manager-only.** `grep -nB3 "kyc-status" backend/app/api/routes/counterparties.py` shows `require_role("risk_manager")` in the preceding decorator stack — NOT `require_any_role(...)`. (Enforces §4.3.3 amendment rule.)
7. **Four audit event types are emitted from code.** `grep -rnE "rfq_invitation_rejected_kyc_not_approved|rfq_quote_rejected_kyc_not_approved|rfq_award_rejected_kyc_not_approved|counterparty_kyc_status_changed" backend/app/` returns ≥4 occurrences (one per event type, possibly more if multiple call sites for one type — but each type must appear at least once). (Enforces §8.)
8. **Backend tests pass.** `cd backend && python -m pytest tests/test_rfq_kyc_gate.py tests/test_counterparty_kyc_transition.py tests/test_rbac_matrix_enforcement.py -v` exits 0 with ≥20 new test cases (per §7.1+§7.2+§7.3+§7.4).
9. **Full suite green.** `cd backend && python -m pytest -q` exits 0; the count of passing tests is at least `<baseline + 20>` where baseline is the pre-merge count.
10. **OpenAPI regen + frontend type drift check pass.** `cd frontend-svelte && npm run api:types && git diff --exit-code src/lib/api/schema.d.ts` shows the regenerated file matches the committed file. `npm run api:types:check` passes. (Enforces Rule 36.)
11. **Frontend vitest passes.** `cd frontend-svelte && npm run test` exits 0 with the new KYC-section test cases included.
12. **Frontend build passes.** `cd frontend-svelte && npm run build` exits 0; ECharts bundle-size budget (`scripts/check-bundle-size.sh`) still passes.
13. **Pre-push hook v2 clean.** The hook run on the final implementation push produces 0 P1 findings.
14. **AugmentCode + Greptile gates green.** Per `reference-review-gates-2026-05-17`: Greptile +1 reaction on the implementation PR + all inline comments resolved + `Greptile Review` CI check green + AugmentCode catches absorbed.
15. **8 pilot counterparties admission readiness (operational, NOT a code gate).** Verifiable by Andrei post-merge via: `gh pr merge` of this PR, then risk_manager calls `POST /counterparties/{id}/kyc-status` (via Swagger or the new frontend UI) for each of the 8 counterparties enumerated in `docs/2026-05-tech-lead-executive-analysis.md` §4 with `new_status=approved, reason=<pilot pre-approval per §7 sign-off>`. This is recorded in the pilot brief's §7 sign-off notes, NOT in the PR.

## §11 Workflow

1. Executor session opens isolated branch from current main HEAD `725f76809` (or whatever main is at session-start; executor verifies with `git fetch origin && git log origin/main -1`).
2. Executor reads this dispatch end-to-end, reads `docs/governance.md` "Counterparty KYC gate" subsection in full, reads the cited code excerpts in `backend/app/services/rfq_service.py` / `backend/app/services/counterparty_service.py` / `backend/app/services/audit_trail_service.py` / `backend/app/core/auth.py` / `backend/app/models/counterparty.py` to verify identifiers and line offsets at branch HEAD.
3. Executor implements §4.1 (new module) first, then §4.2.1 → §4.2.5 (gate sites) in order, then §4.3 (new endpoint + schema + service method), then §4.4 (PATCH rejection), then §4.5 (verification, no code change).
4. Executor runs `cd backend && ruff check . && ruff format . && python -m pytest -x -q` after the backend changes land.
5. Executor implements §6 (frontend changes), runs `cd frontend-svelte && npm run check && npm run test && npm run build`.
6. Executor pushes the branch. Pre-push hook v2 reviews the dispatch — wait, this PR doesn't modify the dispatch; hook may or may not fire depending on whether the executor edited `docs/audits/`. If the executor adds a "PR summary" markdown in `docs/audits/2026-05-XX-pilot-hb-1-implementation-summary.md`, the hook will fire on that file. If not, hook is silent.
7. Executor opens the PR linking back to this dispatch + the amendment PR #93.
8. AugmentCode + Greptile review. Per the latest `reference-review-gates-2026-05-17`: silent re-review on absorption pushes is acceptance (no second +1 needed). Convergent catches (Greptile + AugmentCode same locus) are high-confidence P1 regardless of individual rating per `convergent-catch-signal`.
9. Optional but recommended for institutional-weight PRs: orchestrator runs `/codex:adversarial-review` after first round of bot reviewers absorbed. Per `reference-review-gates-2026-05-17`, Codex catches design-level issues the precision-reviewers miss (Codex caught the `RFQInvitationPurpose` over-binding on the amendment PR #93 that all 3 other reviewers passed on).
10. Andrei merges when: Greptile +1 reaction present + zero unresolved threads + CI all SUCCESS + AugmentCode catches absorbed + Andrei's explicit text authorization (per `feedback_dispatch_transport_partner_clause` and the prior session merges of #91/#92/#93).
11. After merge, Andrei (or orchestrator on Andrei's authorization) executes the operational pre-condition: for each of the 8 pilot counterparties from brief §4, calls `POST /counterparties/{id}/kyc-status` with `new_status=approved, reason=<pilot pre-approval evidence per §7>`. Records the audit event ids in the pilot brief §7 sign-off notes.
12. HB-1 is closed. Next: HB-2 governance amendment authoring (Workflow Approvals — separate audit cycle, separate dispatch).

---

**Executor preference (per `feedback_executor_false_completion_pattern`):** Codex CLI. If another executor is used, mandatory 3-endpoint independent verification (PR + actions + reactions) before merge auth regardless of executor self-report.

**Handoff artifact:** when the executor session begins, create `.handoffs/hb-1-kyc-gate-implementation.md` (gitignored) summarizing the executor's context-window-friendly briefing (links to this dispatch + amendment, working-tree expected state, commands to run first).
