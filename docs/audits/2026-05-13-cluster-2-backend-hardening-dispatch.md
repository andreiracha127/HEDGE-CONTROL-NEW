# Cluster 2 Remediation Dispatch — Backend Hardening (closes A6 dual-layer deferrals)

**Cluster:** Cross-Phase Deferral Backlog — Cluster 2 (backend hardening)
**Authoring date:** 2026-05-13
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main` (HEAD `aa255e2be` at authoring time)
**Required branch:** `audit-followup/cluster-2-backend-hardening`
**Source backlog entry:** `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` §Cluster 2
**Source jury verdict:** `docs/audits/2026-05-12-phase-a6-jury-verdict.md` §Cross-Phase Deferrals
**Reference closure:** `docs/audits/2026-05-13-phase-a6-closure.md`

## 1. Objective

Close the two A6 cross-phase deferrals whose canonical fix sits on the backend:

- **D-2.1** — Backend RFQ actor derivation from JWT (closes J-A6-04 backend slice).
- **D-2.2** — Backend status endpoint refuses generic `settled` / `partially_settled` patch (closes J-A6-02 backend slice).

Both findings already have a frontend slice merged on main:

- PR #65 made the frontend send the immutable JWT `sub` claim as the `user_id` body field on RFQ mutations and gated submission on its presence.
- PR #64 removed `settled` and `partially_settled` from `VALID_TRANSITIONS` on the frontend status-change UI and added a defence-in-depth refusal in `transitionStatus()`.

The frontend slice protects the institutional UX from creating false evidence. The backend slice removes the same protection's escape hatch for any non-frontend caller (programmatic clients, replay, integration tools). Both must converge so the protection is unbypassable.

## 2. Non-Negotiable Constraints

- Do **not** edit `docs/governance.md`.
- Do **not** widen scope to other deferral clusters (no IAM RBAC matrix work, no IdP selection, no token-storage hardening — those are Cluster 3).
- Do **not** alter the canonical ledger settlement path `/cashflow/contracts/{contract_id}/settle`. That path remains the only legitimate writer for `HedgeContractStatus.settled`.
- Do **not** alter the canonical role gate `require_role("trader")` on any of the seven touched RFQ routes or on the status-update route.
- Do **not** introduce a new auth dependency framework. Reuse `get_current_user` from `backend/app/core/auth.py` and the `_ANONYMOUS_USER` dev/test fallback contract already validated by Phase A5.
- Do **not** silently accept body `user_id` after the change lands — the canonical contract must reject the field (Pydantic `extra="forbid"` or explicit validator) so request shape is unambiguous.
- Do **not** remove `user_id` from `RFQStateEventRead` (it is read-side evidence stored on each state event and is the persisted audit trail of who acted).
- Do **not** broaden into a backend audit-cycle re-run. Cluster 2 is direct remediation, not a new audit phase.

Settlement state and actor identity are institutional evidence. After this wave lands, no client-supplied identity may be persisted as actor on RFQ state events, and no client may force `settled` through the generic status endpoint.

## 3. Findings and Evidence

### D-2.1 — Backend RFQ actor derivation from JWT

Accepted evidence (verified at HEAD `aa255e2be`):

- `backend/app/schemas/rfq.py:211-213` defines `RFQUserActionBase` with a required, client-supplied `user_id: str = Field(..., max_length=64)`.
- `backend/app/schemas/rfq.py:85-130` defines `RFQCreate`. `RFQCreate` has no `user_id` field, but it also declares no restriction on extra keys. The frontend currently sends `user_id: actorSub` in the POST `/rfqs` body (`frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:147`) and Pydantic silently drops it. The backend `create_rfq` route (`backend/app/api/routes/rfqs.py:101-128`) does not consume `payload.user_id` — verified by Serena symbolic survey of `RFQService.create` at `backend/app/services/rfq_service.py:455-709`: the service body never reads `user_id` from the payload. POST `/rfqs` is therefore also part of the silent-drop surface and must be closed in the same wave so the contract is unambiguous across **every** RFQ-mutation route, not only the six body-actor routes.
- Six request schemas inherit from `RFQUserActionBase` and therefore require client `user_id`:
  - `RFQRejectRequest` (`backend/app/schemas/rfq.py:215-216`)
  - `RFQRefreshRequest` (`backend/app/schemas/rfq.py:219-220`)
  - `RFQAwardRequest` (`backend/app/schemas/rfq.py:223-224`)
  - `RFQRejectQuoteRequest` (`backend/app/schemas/rfq.py:227-230`)
  - `RFQCancelRequest` (`backend/app/schemas/rfq.py:233-236`)
  - `RFQRefreshCounterpartyRequest` (`backend/app/schemas/rfq.py:239-242`)
- Seven RFQ routes consume the client-supplied `user_id` verbatim and pass it to `RFQService`:
  - `reject_rfq` at `backend/app/api/routes/rfqs.py:315-333` → `RFQService.reject(session, rfq_id, payload.user_id)`.
  - `cancel_rfq` at `backend/app/api/routes/rfqs.py:336-361` → `RFQService.cancel(session, rfq_id, payload.user_id)`.
  - `reject_quote` at `backend/app/api/routes/rfqs.py:367-398` → `RFQService.reject_quote(..., payload.user_id, ...)`.
  - `refresh_counterparty` at `backend/app/api/routes/rfqs.py:401-431` → `RFQService.refresh_counterparty(..., payload.user_id, ...)`.
  - `refresh_rfq` at `backend/app/api/routes/rfqs.py:434-462` → `RFQService.refresh(..., payload.user_id, ...)`.
  - `award_rfq` at `backend/app/api/routes/rfqs.py:465-483` → `RFQService.award(session, rfq_id, payload.user_id)`.
  - `archive_rfq` at `backend/app/api/routes/rfqs.py:486-504` → `RFQService.archive(session, rfq_id, user_id=payload.user_id)`.
- `backend/app/core/auth.py:184-223` defines `get_current_user`, which returns the decoded JWT payload (including `sub`) in auth-enabled mode and the synthetic `_ANONYMOUS_USER` (`backend/app/core/auth.py:178-183`, where `sub == "anonymous"`) in dev/test (auth disabled, non-fail-closed env).
- The frontend already sends JWT `sub` as the body `user_id`:
  - `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:129-147` (POST `/rfqs`)
  - `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte` — all four mutation paths after PR #65.
- `RFQStateEventRead.user_id` at `backend/app/schemas/rfq.py:283` is the persisted read-side evidence; it must continue to reflect the actor that performed the transition.

### D-2.2 — Backend status endpoint refuses generic `settled` patch

Accepted evidence (verified at HEAD `aa255e2be`):

- `backend/app/api/routes/contracts.py:134-149` defines `PATCH /contracts/hedge/{contract_id}/status` and calls `ContractService.transition_status(session, contract_id, payload)` inside `unit_of_work`.
- `backend/app/services/contract_service.py:243-279` implements `transition_status`; it validates only against `VALID_STATUS_TRANSITIONS` and writes `contract.status = target` directly without writing any settlement ledger evidence.
- `backend/app/models/contracts.py:55-67` defines `VALID_STATUS_TRANSITIONS` with the following lifecycle edges:
  - `active → {partially_settled, settled, cancelled}`
  - `partially_settled → {settled, cancelled}`
  - `settled → {}`
  - `cancelled → {}`
- The canonical settlement path is `POST /cashflow/contracts/{contract_id}/settle` at `backend/app/api/routes/cashflow_ledger.py:27-56`, which calls `ingest_hedge_contract_settlement` in `backend/app/services/cashflow_ledger_service.py:216-300`. That service writes a `HedgeContractSettlementEvent`, writes `CashFlowLedgerEntry` rows, and only then sets `contract.status = HedgeContractStatus.settled` (line 292) under the same UoW.
- There is no other writer of `HedgeContractStatus.settled` or `HedgeContractStatus.partially_settled` in the service layer.

## 4. Required Implementation Boundary

### 4.1 D-2.1 — Derive actor from JWT, reject body `user_id`

**Add a dedicated dependency** in `backend/app/core/auth.py`:

```python
def get_current_actor_sub(
    user: dict[str, Any] = Depends(get_current_user),
) -> str:
    """Authoritative actor identifier for mutation evidence.

    Returns the JWT `sub` claim in auth-enabled mode, or the dev/test
    `_ANONYMOUS_USER["sub"]` when auth is disabled. Raises 401 if the
    sub claim is missing/empty in any environment (fail-closed envs
    will already have failed inside get_current_user).
    """
    sub = user.get("sub") if isinstance(user, dict) else None
    if not isinstance(sub, str) or not sub.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated subject is required",
        )
    return sub.strip()
```

**Update `RFQUserActionBase` and derived schemas** in `backend/app/schemas/rfq.py`:

- Remove the `user_id: str = Field(..., max_length=64)` field from `RFQUserActionBase`.
- Add `model_config = ConfigDict(extra="forbid")` to `RFQUserActionBase` so any client supplying `user_id` (or any other extra field) gets a 422.
- Derived classes inherit the empty base. `RFQRefreshCounterpartyRequest` keeps its `counterparty_id` field.
- Leave `RFQStateEventRead.user_id` (read-side schema at line 283) untouched.

**Tighten `RFQCreate`** in `backend/app/schemas/rfq.py` (closes the POST `/rfqs` silent-drop gap surfaced in §3 D-2.1):

- Add a targeted `@model_validator(mode="before")` to `RFQCreate` that raises `ValueError("user_id is not accepted on POST /rfqs; actor identity is derived from the authenticated JWT sub")` if the incoming dict contains a `user_id` key (any value, including empty string or null). FastAPI translates the `ValueError` into a 422 response automatically.
- Do **not** add `extra="forbid"` to `RFQCreate`. The frontend currently sends an additional `counterparty_ids` extra (`frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:146`) that the backend silently drops; that gap is a pre-existing frontend/backend contract mismatch outside Cluster 2 scope (this dispatch closes only the `user_id` silent-drop, not the broader extras posture on `RFQCreate`). The targeted validator scopes the fix narrowly to the actor-identity attack vector.
- Leave the other `RFQCreate` fields (`intent`, `commodity`, `quantity_mt`, `delivery_window_start`, `delivery_window_end`, `direction`, `order_id`, `buy_trade_id`, `sell_trade_id`, `invitations`, `text_en`, `text_pt`) untouched.

**`create_rfq` route is not actor-rewired** — verified by the survey: `RFQService.create` (`backend/app/services/rfq_service.py:455-709`) never consumes `payload.user_id` and never writes the actor onto the `RFQStateEvent` it emits for the `created → sent` transition. Capturing creation-actor evidence on the create-state-event row would be a behavioral expansion outside Cluster 2 scope (record it as a future Cluster-1 / A1-followup-adjacent observation). For Cluster 2, closing POST `/rfqs` means **only** rejecting body `user_id` via the validator above. Audit evidence on the create path continues to flow through the existing `audit_event(entity_type="rfq", event_type="created")` decorator at `backend/app/api/routes/rfqs.py:106-110`, which reads the actor from the authenticated request state independently of the request body.

**Update seven RFQ routes** in `backend/app/api/routes/rfqs.py`:

- Add `actor_sub: str = Depends(get_current_actor_sub)` as a route parameter on all seven mutation handlers listed in §3 D-2.1.
- Replace every `payload.user_id` call site with `actor_sub`.
- The seven handlers must continue to use `unit_of_work` / `audit_event` / `mark_audit_success` / `record_audit_checkpoint` exactly as they do today; only the actor value source changes.
- Do not change the public path, response_model, status_code, role gate, or rate-limit decorator on any of the seven routes.

**Update `RFQService` method signatures** in `backend/app/services/rfq_service.py`:

- Rename the `user_id` parameter to `actor_sub` on every service method that previously consumed `payload.user_id` (reject, cancel, reject_quote, refresh_counterparty, refresh, award, archive). The downstream persistence call that writes the value into `RFQStateEvent.user_id` is unchanged — the column meaning is now "authenticated JWT sub at action time" rather than "client-claimed identifier". No migration is required; the column is `str` and accepts the new content shape (a JWT sub) verbatim.
- Update all internal callers of these service methods (including the worker auto-create path, if any) to pass an actor identifier sourced from the runtime actor or a documented service-account sub.

**Frontend follow-up in the same PR** — `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte` and `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte`:

- Remove `user_id` from every request body (POST `/rfqs`, all `/rfqs/{id}/actions/*`, PATCH `/rfqs/{id}/archive`). The backend now derives this from the JWT.
- Keep `requireActorSub()` and `auth.svelte.ts:userSub` for **client-side preflight** (block the request when the local JWT has no `sub`, so the user gets a clear UX message instead of a 401 round-trip), but never pass `user_id` in the body.
- Update `frontend-svelte/src/lib/api/rfq-evidence-integrity.test.ts` source-scan invariants accordingly: the invariant flips from "POST body must contain `user_id: userSub`" to "POST body must not contain `user_id` at all"; `requireActorSub()` must still gate every mutation locally before `apiFetch` is called.

### 4.2 D-2.2 — Reject `settled` / `partially_settled` via generic status PATCH

**Tighten `transition_status`** in `backend/app/services/contract_service.py`:

- Define a new module-level constant `GENERIC_STATUS_TRANSITIONS` that mirrors `VALID_STATUS_TRANSITIONS` minus every edge whose target is `HedgeContractStatus.settled` or `HedgeContractStatus.partially_settled`. The resulting table is:

```python
GENERIC_STATUS_TRANSITIONS: dict[HedgeContractStatus, set[HedgeContractStatus]] = {
    HedgeContractStatus.active: {HedgeContractStatus.cancelled},
    HedgeContractStatus.partially_settled: {HedgeContractStatus.cancelled},
    HedgeContractStatus.settled: set(),
    HedgeContractStatus.cancelled: set(),
}
```

- `transition_status` uses `GENERIC_STATUS_TRANSITIONS.get(contract.status, set())` (not the full `VALID_STATUS_TRANSITIONS`) when validating the requested target. Targets `settled` and `partially_settled` therefore raise 409 with a settlement-specific detail message: `"Settlement transitions must go through POST /cashflow/contracts/{contract_id}/settle"`.
- Leave `VALID_STATUS_TRANSITIONS` in `backend/app/models/contracts.py` untouched. `ingest_hedge_contract_settlement` does not consult `VALID_STATUS_TRANSITIONS`; it writes the status directly under settlement evidence, so this constant remains an authoritative description of all lifecycle edges across all writers.

**Do not change `/cashflow/contracts/{contract_id}/settle`** in any way. The ledger settlement path remains the only writer of `HedgeContractStatus.settled` and (after this change) the only path that can reach `HedgeContractStatus.partially_settled` if and when the settlement service grows partial-settlement semantics.

**No model migration**. Both states remain valid storage values for existing rows. Only the lifecycle ingress is tightened.

## 5. Constitutional rules

This wave is governed by:

- `docs/governance.md` §2.1 — Evidence integrity (actor identity must reflect the authenticated subject; settlement must produce ledger evidence).
- `docs/governance.md` §2.2 — Mutation must not bypass the canonical lifecycle for its entity (settlement must go through the settlement event path, not a generic status patch).
- `docs/governance.md` §2.7 — Audit reconstructability (state-event rows must show who acted; client-supplied identity is not an authentication signal).

No changes to `docs/governance.md` are part of this wave.

## 6. Acceptance Criteria

A merged PR closes Cluster 2 iff every item below is true on the final commit.

### 6.1 D-2.1 acceptance

- [ ] `backend/app/schemas/rfq.py` — `RFQUserActionBase` has no `user_id` field and declares `model_config = ConfigDict(extra="forbid")`.
- [ ] `backend/app/schemas/rfq.py` — `RFQCreate` defines a `@model_validator(mode="before")` (or equivalent root validator) that raises `ValueError` on any incoming `user_id` key. The class itself does **not** declare `extra="forbid"`; the validator is the narrow gate, scoped to `user_id` only, leaving the pre-existing `counterparty_ids` extra unblocked.
- [ ] `backend/app/core/auth.py` — `get_current_actor_sub` exists, returns `str`, raises 401 when `sub` is missing/empty.
- [ ] `backend/app/api/routes/rfqs.py` — every one of the seven mutation handlers in §3 D-2.1 binds `actor_sub: str = Depends(get_current_actor_sub)` and passes it to `RFQService` instead of `payload.user_id`.
- [ ] `backend/app/api/routes/rfqs.py` — `create_rfq` (POST `/rfqs`) is unchanged in signature; the new validator on `RFQCreate` is the only enforcement point for the create-path body `user_id`.
- [ ] `backend/app/services/rfq_service.py` — every consumed method renamed parameter to `actor_sub`; internal callers updated.
- [ ] Frontend mutation bodies under `frontend-svelte/src/routes/(protected)/rfq/` no longer contain `user_id` — this covers both the seven action endpoints and the POST `/rfqs` create body.
- [ ] `rg -nP 'payload\.user_id' backend/app/api/routes/rfqs.py` returns zero matches.
- [ ] `rg -nP "'user_id'\s*:" frontend-svelte/src/routes/\\(protected\\)/rfq/` returns zero matches.

### 6.2 D-2.2 acceptance

- [ ] `backend/app/services/contract_service.py` — `transition_status` consults `GENERIC_STATUS_TRANSITIONS`, not `VALID_STATUS_TRANSITIONS`.
- [ ] `GENERIC_STATUS_TRANSITIONS` is defined and has the exact shape specified in §4.2.
- [ ] `backend/app/models/contracts.py` — `VALID_STATUS_TRANSITIONS` is unchanged.
- [ ] `backend/app/services/cashflow_ledger_service.py` — `ingest_hedge_contract_settlement` is unchanged.
- [ ] `rg -nP "HedgeContractStatus\\.settled" backend/app/services/contract_service.py` shows no new writer of `.settled`; the symbol may still appear in error message construction.

### 6.3 Cross-cutting acceptance

- [ ] `docs/governance.md` diff is empty.
- [ ] Single alembic head unchanged.
- [ ] `backend/tests` passes under `pytest -q`.
- [ ] `frontend-svelte` passes `npm run check`, `npm test`, `npm run build`.
- [ ] OpenAPI regeneration (`npm run gen:api` if applicable, or the canonical regen path) produces a diff that removes `user_id` from `RFQRejectRequest`, `RFQRefreshRequest`, `RFQAwardRequest`, `RFQRejectQuoteRequest`, `RFQCancelRequest`, `RFQRefreshCounterpartyRequest`, and `RFQUserActionBase`. No other endpoint surface changes.
- [ ] CI `openapi_diff` job is green.

## 7. Required Tests

### 7.1 D-2.1 tests

**Backend** — `backend/tests/test_rfq_actor_jwt_derivation.py` (new):

1. Authenticated mutation derives actor from JWT — POST `/rfqs/{id}/actions/reject` with a valid bearer carrying `sub=sub-abc` and an empty JSON body produces `RFQStateEvent.user_id == "sub-abc"`.
2. Same test repeated for the other six mutation routes (cancel, reject-quote, refresh-counterparty, refresh, award, archive). Use parametrization.
3. Body that supplies `user_id` is rejected with 422 — POST `/rfqs/{id}/actions/reject` with `{"user_id": "spoof"}` returns 422 and does not transition state (`RFQ.state` unchanged, no new `RFQStateEvent`).
4. **POST `/rfqs` with body `user_id` is rejected with 422** — POST `/rfqs` with a valid `RFQCreate` body augmented by `{"user_id": "spoof"}` returns 422 with the validator's detail message ("user_id is not accepted on POST /rfqs; actor identity is derived from the authenticated JWT sub"). No `RFQ` row, no `RFQInvitation` row, and no `RFQStateEvent` row are created. Sanity counter-test: a POST `/rfqs` body **without** `user_id` succeeds (subject to the existing 400/404 validation surface — counterparty existence, intent/direction, etc.).
5. Missing `sub` claim is rejected with 401 — a JWT-decoded payload without `sub` produces 401 with detail `"Authenticated subject is required"`.
6. Dev/anonymous environment writes `sub == "anonymous"` — when auth is disabled and env is not fail-closed, the same routes write `"anonymous"` into `RFQStateEvent.user_id` (regression guard for the existing `_ANONYMOUS_USER` fallback contract from Phase A5).
7. `RFQStateEventRead.user_id` is preserved on the read-side — GET `/rfqs/{id}/state-events` after a mutation returns the actor sub.

**Backend regression** — extend `backend/tests/test_outbound_evidence.py` (or the existing RFQ action test files) to:

8. Confirm `user_id` is rejected on every existing action test that previously supplied it. Strict assertion: previously passing tests that included a `user_id` body field must now fail closed unless updated. Same guarantee applies to any existing test that POSTs `/rfqs` with a `user_id` body field — those tests must be updated to omit `user_id` (the validator now 422s them).

**Frontend** — extend `frontend-svelte/src/lib/api/rfq-evidence-integrity.test.ts`:

9. Source-scan invariant: every call site under `frontend-svelte/src/routes/(protected)/rfq/` that issues an RFQ mutation must not contain `user_id` in its request body literal. The invariant must explicitly cover `rfq/new/+page.svelte` (POST `/rfqs`) in addition to the six action paths under `rfq/[id]/+page.svelte`.
10. `requireActorSub()` still gates every mutation (including create) locally (regression guard for the local UX preflight contract).

### 7.2 D-2.2 tests

**Backend** — `backend/tests/test_contract_status_settlement_guard.py` (new):

1. PATCH `/contracts/hedge/{id}/status` with `{"status": "settled"}` against an active contract returns 409 with detail `"Settlement transitions must go through POST /cashflow/contracts/{contract_id}/settle"`. The contract row remains `active`.
2. Same as 1 but with `{"status": "partially_settled"}` and `active` source state.
3. Same as 1 but with `{"status": "settled"}` and `partially_settled` source state.
4. PATCH `/contracts/hedge/{id}/status` with `{"status": "cancelled"}` against `active` returns 200 and the contract is `cancelled`. (Regression guard: the legitimate cancellation path is unchanged.)
5. PATCH `/contracts/hedge/{id}/status` with `{"status": "cancelled"}` against `partially_settled` returns 200 and the contract is `cancelled`. (Regression guard.)
6. POST `/cashflow/contracts/{id}/settle` with the canonical `HedgeContractSettlementCreate` payload against `active` returns 201, writes ledger entries, and transitions the contract to `settled`. (Regression guard for the legitimate settlement path.)

**Backend invariants**:

7. Module-level assertion test that `HedgeContractStatus.settled not in GENERIC_STATUS_TRANSITIONS[HedgeContractStatus.active]` and not in `GENERIC_STATUS_TRANSITIONS[HedgeContractStatus.partially_settled]`.
8. Module-level assertion test that `VALID_STATUS_TRANSITIONS` is unchanged (importable and equal to a frozen reference dict).

## 8. Required Verification

Before opening the PR:

```bash
# Schema sweep — confirm user_id is gone from request schemas (only allowed mention: read-side RFQStateEventRead.user_id at line ~283)
rg -nP "user_id" backend/app/schemas/rfq.py
rg -nP "payload\\.user_id" backend/app/api/routes/rfqs.py
rg -nP "'user_id'\\s*:" frontend-svelte/src/routes/\\(protected\\)/rfq/

# RFQCreate validator sweep — confirm a model_validator that rejects user_id is present
rg -nP "user_id.*not accepted on POST /rfqs|model_validator.*before.*RFQCreate|RFQCreate.*user_id" backend/app/schemas/rfq.py

# Lifecycle sweep
rg -nP "VALID_STATUS_TRANSITIONS|GENERIC_STATUS_TRANSITIONS" backend/app

# Test sweep
pytest -q backend/tests/test_rfq_actor_jwt_derivation.py
pytest -q backend/tests/test_contract_status_settlement_guard.py
pytest -q backend/tests
cd frontend-svelte && npm run check && npm test && npm run build && cd ..

# Generated artifacts
git diff -- docs/api/openapi_v1.json frontend-svelte/src/lib/api/schema.d.ts
git diff --check
```

The schema sweep must return zero matches for `payload.user_id` in routes and zero matches for `'user_id':` in the frontend RFQ routes. The `user_id` mention in `backend/app/schemas/rfq.py` must collapse to (a) the new validator literal in `RFQCreate` and (b) the read-side `RFQStateEventRead.user_id` field — both are intentional and must remain.

## 9. Out of Scope

Explicitly out of scope for this wave (do not implement here):

- Cluster 1 — A1 follow-up audit cycle (deal-engine + exposure + scenario). Separate phase.
- Cluster 3 — IAM RBAC matrix, IdP selection, token storage hardening, CSP/CSRF/XSS-sink inventory. Platform decisions outstanding.
- Cluster 4 — Market-data governance beyond signed evidence. Separate scope.
- Settlement-event redesign (partial vs full settlement semantics; settlement reversal; settlement cancellation). Out of A6's deferred surface.
- Adding new actor-evidence columns to existing tables. The `RFQStateEvent.user_id` column is the persisted actor field and is reused as-is.
- Wiring `actor_sub` into routes other than the seven RFQ mutations and the contract status patch. No status patch on `/orders`, `/exposures`, or any other route is part of this dispatch.
- Any change to the canonical role gate or to the `_ANONYMOUS_USER` dev/test fallback.
- Any change to `docs/governance.md`.

## 10. PR Requirements

The implementing PR title must be:

```
fix(audit-followup): close Cluster 2 backend hardening (D-2.1 + D-2.2)
```

The PR body must include:

- **Findings closed:** explicit list of D-2.1 (J-A6-04 backend slice) and D-2.2 (J-A6-02 backend slice).
- **Files changed:** full inventory grouped by backend / frontend / tests.
- **Verification matrix:** results of the §8 sweeps and the test suites.
- **Generated-artifact diff:** explicit summary of the OpenAPI / `schema.d.ts` removal of `user_id` from the six action-request schemas, plus the new `RFQCreate` validator that 422s body `user_id` on POST `/rfqs` (the OpenAPI shape of `RFQCreate` itself does not change because `user_id` was never a declared field; the OpenAPI delta surfaces only through the six action schemas).
- **Hook artifact path:** `.cache/dispatch_review/audit-followup-cluster-2-backend-hardening-{sha}.json` for every push.
- **Governance statement:** `docs/governance.md` diff is empty.

## 11. Workflow

1. Branch off `main` at HEAD `aa255e2be` (or later if main advances before work begins): `git checkout -b audit-followup/cluster-2-backend-hardening`.
2. Implement §4.1 D-2.1 in this order to minimize churn:
   1. Add `get_current_actor_sub` in `backend/app/core/auth.py`.
   2. Update `RFQUserActionBase` and remove the field from the six derived schemas; add the targeted `@model_validator(mode="before")` to `RFQCreate` that 422s a body `user_id`. **Do not** add `extra="forbid"` to `RFQCreate` (per §4.1 boundary rule).
   3. Wire `actor_sub` into the seven RFQ routes and update `RFQService` signatures.
   4. Drop `user_id` from frontend mutation bodies (all seven actions **and** the POST `/rfqs` create body) and update `rfq-evidence-integrity.test.ts`.
   5. Regenerate OpenAPI + `schema.d.ts`.
3. Implement §4.2 D-2.2:
   1. Define `GENERIC_STATUS_TRANSITIONS` in `backend/app/services/contract_service.py`.
   2. Switch `transition_status` to use it.
   3. Update error detail message text per §4.2.
4. Add the two new test files (`test_rfq_actor_jwt_derivation.py`, `test_contract_status_settlement_guard.py`).
5. Update existing tests that previously supplied `user_id` in RFQ mutation bodies — they must be rewritten to assert 422 on body-`user_id` or to omit the field.
6. Run §8 verification locally. Fix any pre-push hook v2 P1/P2 in place.
7. Push the branch and open the PR per §10.
8. Codex Connector review is the final gate. Address every Codex inline catch. Merge only after explicit user authorization.

## 12. Hook v2 + Codex calibration notes

- This wave touches three layers (backend schemas, backend routes, frontend) but is single-PR-shaped because both findings share the same `actor / lifecycle authority` constitutional concern.
- Expected hook v2 surface area: schema-shape drift (extra="forbid" enforcement on `RFQUserActionBase` + the narrow `RFQCreate` validator), route-handler signature drift, frontend body-literal drift across **both** the seven action routes and POST `/rfqs`, OpenAPI regen drift. The 8-section sweep checklist from [[feedback_dispatch_self_consistency]] applies — confirm §3 evidence, §4 boundary, §6 acceptance, §7 tests, §10 PR body, and §11 workflow all enumerate the same seven RFQ action routes **plus** POST `/rfqs` and both target lifecycle transitions every time the list is rewritten.
- Expected Codex catches: missing call site for one of the seven RFQ action routes; `RFQUserActionBase` derived class missed; worker / service-internal caller of an `RFQService` method missed; settlement-related test missing the partial state's regression case; **POST `/rfqs` create-body `user_id` silent-drop missed if the implementing PR only enforces `extra="forbid"` on the action base but not the targeted validator on `RFQCreate`** (this is the exact gap Codex caught on the v1 dispatch — see PR #70 review).
- Pre-emptive dispatch rigor pattern from [[feedback_dispatch_self_consistency]] applies: cross-section sweep before publishing the dispatch is mandatory. The institutional FP class around partial-diff blindness from [[reference_pre_push_hook_calibration]] will likely surface when the implementing branch pushes test-only or schema-only follow-ups.
