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
- **Per-route actor-evidence-sink matrix (verified by Serena symbolic survey at HEAD `aa255e2be`).** The seven action routes do **not** share a single evidence sink. The wiring of `actor_sub` must reach the appropriate sink for each route, and acceptance/tests must be split accordingly:

  | Route | Service method (line) | Actor evidence sink today | After Cluster 2 |
  |---|---|---|---|
  | `reject_rfq` | `RFQService.reject` (`rfq_service.py:919-943`) | `RFQStateEvent.user_id` on QUOTED→CLOSED (reason=`USER_REJECTED`) | unchanged sink; param renamed to `actor_sub`, value from JWT |
  | `cancel_rfq` | `RFQService.cancel` (`rfq_service.py:945-970`) | `RFQStateEvent.user_id` on CREATED/SENT→CLOSED (reason=`USER_CANCELLED`) | unchanged sink; param renamed; value from JWT |
  | `reject_quote` | `RFQService.reject_quote` (`rfq_service.py:1101-1264`) | `RFQQuote.rejected_by` (per-quote field, always set); conditional `RFQStateEvent` (QUOTED→SENT, reason=`ALL_QUOTES_REJECTED`) emitted when last active quote is rejected, **but the conditional event currently has no `user_id` populated** | `RFQQuote.rejected_by=actor_sub` (unchanged sink); the conditional `ALL_QUOTES_REJECTED` event also gains `user_id=actor_sub` (sub-gap closed) |
  | `refresh_rfq` | `RFQService.refresh` (`rfq_service.py:972-1095`) | **None.** Service writes `RFQInvitation` outbox rows (`purpose=refresh`); the `user_id` parameter is accepted by the signature but never persisted anywhere | param renamed to `actor_sub`, sourced from JWT, but the residual no-evidence behavior is preserved — closing this gap requires either adding a `user_id` column to `RFQInvitation` (migration) or emitting a new state-event semantic (lifecycle change), both outside §6.3's single-alembic-head invariant. Recorded in §9 |
  | `refresh_counterparty` | `RFQService.refresh_counterparty` (`rfq_service.py:1266-1379`) | **None.** Same shape as `refresh_rfq` — single `RFQInvitation` outbox row, `user_id` parameter silently dropped | same as `refresh_rfq` |
  | `award_rfq` | `RFQService.award` (`rfq_service.py:1381-1616`) | `RFQStateEvent.user_id` on QUOTED→AWARDED **plus** on child-spread closes (per `closed_by_parent_spread`) | unchanged sinks; param renamed; value from JWT |
  | `archive_rfq` | `RFQService.archive` (`rfq_service.py:760-803`) | `RFQStateEvent.user_id` on CLOSED→CLOSED (trigger=`archive`) | unchanged sink; param renamed; value from JWT |

  Summary by sink class:
  - **State-event sink (4 routes today; 5 after this wave)**: reject, cancel, award, archive — and (after this wave) the conditional `ALL_QUOTES_REJECTED` event from reject_quote also gains `user_id`.
  - **Per-quote sink (1 route)**: reject_quote writes `RFQQuote.rejected_by` directly. The mandatory sink for this route — the conditional state event is the secondary surface.
  - **No-evidence sink (2 routes)**: refresh, refresh_counterparty — parameter is JWT-sourced after this wave but no new evidence column is added. The pre-existing absence of an evidence sink on these two routes is **preserved**.
- `backend/app/core/auth.py:184-223` defines `get_current_user`, which returns the decoded JWT payload (including `sub`) in auth-enabled mode and the synthetic `_ANONYMOUS_USER` (`backend/app/core/auth.py:178-183`, where `sub == "anonymous"`) in dev/test (auth disabled, non-fail-closed env).
- The frontend already sends JWT `sub` as the body `user_id`:
  - `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:129-147` (POST `/rfqs`)
  - `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte` — all four mutation paths after PR #65.
- `RFQStateEventRead.user_id` at `backend/app/schemas/rfq.py:283` is the persisted read-side evidence; it must continue to reflect the actor that performed the transition.
- **Create-path actor-evidence gap (verified by Serena symbolic survey at HEAD `aa255e2be`).** An earlier draft of this dispatch claimed the create path carried actor evidence through the `audit_event` decorator. That claim is false. Concretely:
  - `backend/app/api/dependencies/audit.py:47-113` defines the `audit_event` factory. The internal `_commit_audit` closure writes via `AuditTrailService.record` with `entity_type`, `entity_id`, `event_type`, `payload_raw`, and `payload_obj` only — **no actor field is read from the request state and no actor column is persisted**.
  - `backend/app/models/audit.py:11-24` defines `AuditEvent` with columns `id`, `timestamp_utc`, `entity_type`, `entity_id`, `event_type`, `payload`, `payload_canonical`, `checksum`, `signature` — **no actor / user / sub column exists at all**.
  - `backend/app/services/rfq_service.py:455-709` (`RFQService.create`) emits the `created → sent` `RFQStateEvent` near the end of the function using only `rfq_id`, `from_state`, `to_state`, and `event_timestamp` keyword arguments — **`user_id` is never passed**.
- Consequence: today RFQ creation has **zero authenticated-actor evidence** on either the `AuditEvent` row (no column) or the `RFQStateEvent` row (column exists, but the create path never populates it). If Cluster 2 closes only the seven action routes and the `RFQCreate` validator, POST `/rfqs` remains the lone RFQ-mutation route without actor evidence — institutional inconsistency. The create-path `RFQStateEvent.user_id` must be wired in the same wave for the contract to be uniform across every RFQ-mutation route. Adding an actor column to `AuditEvent` itself is a broader IAM-design concern (Cluster 3 territory) and stays out of scope for Cluster 2.
- **Frontend POST `/rfqs` body uses the wrong field for invitations (verified at HEAD `aa255e2be`).** The frontend constructs the create payload at `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:139-148` with `counterparty_ids: selectedCounterpartyIds`. The backend `RFQCreate` schema (`backend/app/schemas/rfq.py:85-130`) declares `invitations: list[RFQInvitationCreate]` (no `counterparty_ids` field), so Pydantic silently drops the extra. The service then iterates `payload.invitations` (which is the empty default), the for-loop is a no-op, no `RFQInvitation` rows are persisted, no WhatsApp sends are attempted, `has_sent` evaluates to `False`, and **the `created → sent` `RFQStateEvent` is never emitted** for UI-created RFQs. Naïvely wiring `actor_sub` only into the conditional `created → sent` event would still leave **production** UI-created RFQs with zero actor evidence — the fix would be vacuously correct against synthetic backend test bodies but practically broken. `RFQInvitationCreate` requires only `counterparty_id: UUID` (`backend/app/schemas/rfq.py:55-58`), so the frontend mapping is a one-line transformation. Cluster 2 must include this frontend contract repair so the actor evidence path is reachable in production.

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
- Do **not** add `extra="forbid"` to `RFQCreate`. The frontend contract repair below (see "Frontend follow-up") replaces the broken `counterparty_ids` extra with the canonical `invitations` array, but Cluster 2 deliberately keeps the create-path contract narrow at the schema layer: the targeted `@model_validator` gives a specific operator-readable 422 message for `user_id` only ("user_id is not accepted on POST /rfqs; actor identity is derived from the authenticated JWT sub"). A generic `extra="forbid"` on `RFQCreate` would lump every future stray field into a cryptic "extra not permitted" error and would also expand scope to a comprehensive extras posture (deciding which optional/legacy fields are intentional, etc.) that belongs to a later cleanup, not this remediation wave.
- Leave the other `RFQCreate` fields (`intent`, `commodity`, `quantity_mt`, `delivery_window_start`, `delivery_window_end`, `direction`, `order_id`, `buy_trade_id`, `sell_trade_id`, `invitations`, `text_en`, `text_pt`) untouched.

**Wire `create_rfq` for actor evidence** — the create path must also persist the authenticated JWT sub onto the `RFQStateEvent` it emits, for consistency with the seven action routes. Per §3 D-2.1 evidence: `audit_event` does **not** carry actor identity (no actor column on `AuditEvent`), and `RFQService.create` currently emits the `created → sent` state event with `user_id=None`. Closing POST `/rfqs` for actor evidence therefore requires three changes:

- **Route**: `create_rfq` at `backend/app/api/routes/rfqs.py:101-128` adds `actor_sub: str = Depends(get_current_actor_sub)` and passes it to `RFQService.create(..., actor_sub=actor_sub)`. Keep `audit_event`, `require_role`, and the existing `audit_checkpoint` flow unchanged.
- **Service**: `RFQService.create` gains an `actor_sub: str` keyword parameter (positional after `payload`, before the existing `audit_checkpoint` kwarg). The single `RFQStateEvent(...)` construction inside the function (the `created → sent` event near the end of the body) gains `user_id=actor_sub`.
- **No new state event for initial `created` state**: the pre-existing design does not emit a `null → created` state event on RFQ creation, only the `created → sent` transition when at least one invitation was successfully sent. Cluster 2 does not alter this design — if `has_sent` is `False`, no state event is written and no actor evidence persists for that RFQ (the existing pre-merge condition; not new). This narrow gap is recorded in §9 Out of Scope.

`RFQCreate` body `user_id` is still rejected by the validator added above. The route's `actor_sub` parameter is the **only** authoritative actor source for the create path; the body validator prevents any client-supplied claim from coexisting with the JWT-derived value (defence in depth against future regressions).

**Update seven RFQ routes** in `backend/app/api/routes/rfqs.py`:

- Add `actor_sub: str = Depends(get_current_actor_sub)` as a route parameter on all seven mutation handlers listed in §3 D-2.1.
- Replace every `payload.user_id` call site with `actor_sub`.
- The seven handlers must continue to use `unit_of_work` / `audit_event` / `mark_audit_success` / `record_audit_checkpoint` exactly as they do today; only the actor value source changes.
- Do not change the public path, response_model, status_code, role gate, or rate-limit decorator on any of the seven routes.

**Update `RFQService` method signatures** in `backend/app/services/rfq_service.py` — split by evidence-sink class (per §3 D-2.1 matrix):

- **State-event-sink methods** (`reject`, `cancel`, `award`, `archive`): rename the `user_id` parameter to `actor_sub`. The downstream `RFQStateEvent(user_id=...)` construction is unchanged in shape; only the value source changes from "client-claimed identifier" to "authenticated JWT sub at action time". The `RFQStateEvent.user_id` column is `str | None` (`backend/app/models/rfqs.py:196`) and accepts the new content shape verbatim. No migration.
- **Per-quote-sink method** (`reject_quote`): rename `user_id` to `actor_sub`. The mandatory write is `RFQQuote.rejected_by = actor_sub` (today writes `payload.user_id`); after this wave the value is the JWT sub. The conditional `ALL_QUOTES_REJECTED` `RFQStateEvent` emitted when the last active quote is rejected (`rfq_service.py:1219-1228`) currently constructs without `user_id`; **add `user_id=actor_sub` to that construction** so the secondary state event also carries actor evidence when emitted. This closes the sub-gap surfaced in §3 D-2.1 ("conditional event currently has no `user_id`").
- **No-evidence-sink methods** (`refresh`, `refresh_counterparty`): rename `user_id` to `actor_sub`. Do **not** add new persistence — neither method writes a state event today, and neither `RFQInvitation` nor any other reachable row has a `user_id` column. The parameter is preserved (now JWT-sourced) for future use; closing the no-evidence gap on these two routes requires a migration (add `user_id` to `RFQInvitation` or emit a new state-event semantic) which is explicitly deferred in §9.
- Update all internal callers of these service methods (including the worker auto-create path, if any) to pass an actor identifier sourced from the runtime actor or a documented service-account sub.

**Frontend follow-up in the same PR** — `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte` and `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte`:

- Remove `user_id` from every request body (POST `/rfqs`, all `/rfqs/{id}/actions/*`, PATCH `/rfqs/{id}/archive`). The backend now derives this from the JWT.
- **Replace `counterparty_ids: selectedCounterpartyIds` with `invitations: selectedCounterpartyIds.map((id) => ({ counterparty_id: id }))`** in the POST `/rfqs` body construction at `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:146`. This closes the silent-drop contract drift surfaced in §3 D-2.1: today the backend never sees any invitation array from UI-created RFQs, so the invitation loop is a no-op, `has_sent` is `False`, and no `RFQStateEvent` (and therefore no actor evidence) is ever written. After this mapping fix, UI-created RFQs will produce the same `RFQInvitation` rows that the existing service code already handles for backend-test bodies — no other service-side changes are needed because `RFQInvitationCreate` requires only `counterparty_id: UUID` per the schema at `backend/app/schemas/rfq.py:55-58`.
- Keep `requireActorSub()` and `auth.svelte.ts:userSub` for **client-side preflight** (block the request when the local JWT has no `sub`, so the user gets a clear UX message instead of a 401 round-trip), but never pass `user_id` in the body.
- Update `frontend-svelte/src/lib/api/rfq-evidence-integrity.test.ts` source-scan invariants accordingly: (a) flip the `user_id` invariant from "POST body must contain `user_id: userSub`" to "POST body must not contain `user_id` at all"; (b) `requireActorSub()` must still gate every mutation locally before `apiFetch` is called; (c) new invariant: the POST `/rfqs` body literal must not contain `counterparty_ids:` (the broken field name) and must contain `invitations:` (the canonical field name).

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
- [ ] `backend/app/schemas/rfq.py` — `RFQCreate` defines a `@model_validator(mode="before")` (or equivalent root validator) that raises `ValueError` on any incoming `user_id` key. The class itself does **not** declare `extra="forbid"`; the validator is the narrow gate scoped to `user_id` only, with an operator-readable 422 detail message.
- [ ] `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte` — the POST `/rfqs` body construction at line 146 maps `selectedCounterpartyIds` to `invitations: selectedCounterpartyIds.map((id) => ({ counterparty_id: id }))`. The `counterparty_ids` field is gone from the POST body literal. This closes the silent-drop contract drift so the create-path `RFQStateEvent` is reachable when at least one invitation send succeeds.
- [ ] `backend/app/core/auth.py` — `get_current_actor_sub` exists, returns `str`, raises 401 when `sub` is missing/empty.
- [ ] `backend/app/api/routes/rfqs.py` — every one of the seven mutation handlers in §3 D-2.1 binds `actor_sub: str = Depends(get_current_actor_sub)` and passes it to `RFQService` instead of `payload.user_id`.
- [ ] `backend/app/api/routes/rfqs.py` — `create_rfq` (POST `/rfqs`) binds `actor_sub: str = Depends(get_current_actor_sub)` and forwards it to `RFQService.create(..., actor_sub=actor_sub)`. The `RFQCreate` validator added in this wave is a defence-in-depth gate that 422s any body-supplied `user_id`; the `actor_sub` Depends is the authoritative actor source.
- [ ] `backend/app/services/rfq_service.py` — `RFQService.create` signature gains an `actor_sub: str` parameter and constructs its single `RFQStateEvent(... user_id=actor_sub)` for the `created → sent` transition. The pre-existing absence of any state event when `has_sent` is `False` is unchanged and recorded in §9 Out of Scope.
- [ ] `backend/app/services/rfq_service.py` — every consumed method renamed parameter to `actor_sub`; internal callers updated.
- [ ] `backend/app/services/rfq_service.py` (`reject_quote`) — the conditional `RFQStateEvent(reason="ALL_QUOTES_REJECTED", ...)` construction at `rfq_service.py:1219-1228` gains `user_id=actor_sub`. Today this conditional event is emitted with no `user_id` populated; after this wave it carries the JWT sub so the secondary state-event surface for `reject_quote` is consistent with the primary `RFQQuote.rejected_by` field.
- [ ] **Per-route sink wiring is split** — the implementing PR must NOT assert `RFQStateEvent.user_id` for every action route, because `refresh` and `refresh_counterparty` emit **no state event** today and Cluster 2 does not add one (see §3 D-2.1 matrix). Acceptance for those two routes is parameter-derivation-only: the route binds `actor_sub` Depends and the service signature receives it; no new evidence column is asserted. The residual no-evidence gap is recorded in §9.
- [ ] Frontend mutation bodies under `frontend-svelte/src/routes/(protected)/rfq/` no longer contain `user_id` — this covers both the seven action endpoints and the POST `/rfqs` create body.
- [ ] `rg -nP 'payload\.user_id' backend/app/api/routes/rfqs.py` returns zero matches.
- [ ] `rg -nP "\buser_id\s*:" frontend-svelte/src/routes/\\(protected\\)/rfq/` returns zero matches. **Important:** the regex matches unquoted object-literal keys (`user_id: actorSub`), the JS/TS form actually used in the frontend (verified pre-amendment at `rfq/[id]/+page.svelte:219,247,274,298` and `rfq/new/+page.svelte:147`), not only string-quoted JSON keys (`'user_id':`). The pattern intentionally excludes read-side field references like `evt.user_id` because those have no `:` immediately after the field name — those remain legitimate on the RFQ detail page for displaying state-event actors (e.g. `<div>por {evt.user_id}</div>`).

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
2a. **State-event-sink routes (parametrized over `cancel`, `award`, `archive`)**: with a valid bearer carrying `sub=sub-abc` and a valid (non-`user_id`) body, the mutation produces a corresponding `RFQStateEvent` whose `user_id == "sub-abc"`. For `cancel`: from CREATED→CLOSED **and** SENT→CLOSED (both parametrized fixtures). For `award`: the QUOTED→AWARDED event must have `user_id`; for a SPREAD award, every child-spread close event also carries `user_id`. For `archive`: the CLOSED→CLOSED event with `trigger="archive"` carries `user_id`.
2b. **Per-quote-sink route (`reject_quote`)**: with a valid bearer carrying `sub=sub-abc` and a valid body, the mutation persists `RFQQuote.rejected_by == "sub-abc"` on the targeted quote (always set). Additionally, when the targeted quote is the **last active quote** on the RFQ, the conditional `RFQStateEvent(from_state=QUOTED, to_state=SENT, reason="ALL_QUOTES_REJECTED")` is emitted with `user_id == "sub-abc"` — this is the sub-gap that Cluster 2 closes per §4.1. Counter-case: when other active quotes remain, no `RFQStateEvent` is emitted (existing behavior) but `RFQQuote.rejected_by` is still set on the targeted quote.
2c. **No-evidence-sink routes (`refresh`, `refresh_counterparty`)**: with a valid bearer carrying `sub=sub-abc` and a valid body, the mutation succeeds (200) and persists at least one `RFQInvitation` row with `purpose=RFQInvitationPurpose.refresh` (existing behavior). The test must explicitly assert that **no new `RFQStateEvent` is emitted** by these routes (pre-existing behavior preserved; documented in §9). The route's `actor_sub` parameter is verified to be derived from the JWT (not from the body) by separate test 3 below.
3. Body that supplies `user_id` is rejected with 422 — POST `/rfqs/{id}/actions/reject` with `{"user_id": "spoof"}` returns 422 and does not transition state (`RFQ.state` unchanged, no new `RFQStateEvent`).
4. **POST `/rfqs` with body `user_id` is rejected with 422** — POST `/rfqs` with a valid `RFQCreate` body augmented by `{"user_id": "spoof"}` returns 422 with the validator's detail message ("user_id is not accepted on POST /rfqs; actor identity is derived from the authenticated JWT sub"). No `RFQ` row, no `RFQInvitation` row, and no `RFQStateEvent` row are created.
4a. **POST `/rfqs` success path persists actor on the create state event** — POST `/rfqs` with a valid `RFQCreate` body containing `invitations: [{counterparty_id: <uuid>}]` (no `user_id` field) and a JWT carrying `sub=sub-abc`, where at least one invitation send succeeds (mock the `WhatsAppService.send_text_message` to return success), returns 201 and the resulting `RFQStateEvent(from_state=created, to_state=sent)` has `user_id == "sub-abc"`. This is the create-path counterpart of test 1 and closes the institutional gap that POST `/rfqs` previously left no actor evidence anywhere.
4b. **POST `/rfqs` no-send branch preserves pre-existing behavior** — POST `/rfqs` with a valid `RFQCreate` body containing `invitations: [{counterparty_id: <uuid>}]` and a JWT carrying `sub=sub-abc`, where all invitation sends fail (mock `WhatsAppService.send_text_message` to return failure), returns 201 but **no `RFQStateEvent` row is written** (pre-existing behavior; `has_sent` evaluates to `False`). The test must assert this explicitly so future readers don't confuse the no-state-event branch with a regression; it also documents that the all-sends-fail edge case is a known remaining partial gap (Cluster 2 does not write unconditional actor evidence on the create path — see §9). The `RFQ` row is still persisted at `state=RFQState.created`, and the corresponding `RFQInvitation` rows are persisted with `send_status=failed` and `failure_reason` populated.
4c. **Frontend POST `/rfqs` body uses canonical `invitations` field** — vitest source-scan test under `frontend-svelte/src/lib/api/rfq-evidence-integrity.test.ts` asserts that `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte` (a) does not contain `counterparty_ids:` in the POST `/rfqs` body literal, and (b) contains `invitations:` (the canonical field name) plus the mapping shape `counterparty_id:` inside the mapped object. The invariant is the source-scan counterpart of the §3 D-2.1 contract-drift evidence, so future regressions to the broken field name are caught at unit-test time, not by manual debugging of empty-invitation RFQs in staging.
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
rg -nP "\\buser_id\\s*:" frontend-svelte/src/routes/\\(protected\\)/rfq/   # unquoted JS/TS object-literal keys, the actual form in the frontend

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
- Adding new actor-evidence columns to existing tables. The `RFQStateEvent.user_id` column is the persisted actor field and is reused as-is across all eight RFQ-mutation routes (the seven actions plus POST `/rfqs`). Notably, `AuditEvent` (`backend/app/models/audit.py:11-24`) has no actor column today; adding one would be a broader IAM-design change that belongs to Cluster 3 (security/platform), not Cluster 2.
- Wiring `actor_sub` into routes other than the eight RFQ mutations (the seven actions plus POST `/rfqs`) and the contract status patch. No status patch on `/orders`, `/exposures`, or any other route is part of this dispatch. The contract status PATCH at `/contracts/hedge/{id}/status` is tightened in D-2.2 to refuse `settled` / `partially_settled` targets, but is **not** rewired for actor identity — that surface remains actor-blind in Cluster 2.
- Emitting an unconditional `null → created` (or any other no-send-branch) `RFQStateEvent` on RFQ creation. The pre-existing `RFQService.create` only writes a `created → sent` event when at least one invitation send succeeded. After Cluster 2's frontend repair (mapping `counterparty_ids → invitations`), UI-created RFQs will populate `invitations` and reach the send loop, so in the typical case at least one send succeeds and the state event is emitted with `user_id=actor_sub`. The remaining edge case — **every** invitation send fails (e.g. WhatsApp connectivity outage) — leaves the RFQ at `RFQState.created` with no state event and therefore no actor evidence on a state event. Capturing the actor on that branch would require either (a) making `RFQStateEvent.from_state` nullable so a `null → created` row can be written before the send loop, or (b) adding a `created_by` column to the `RFQ` row directly. Both require an alembic migration; Cluster 2 explicitly preserves the single-alembic-head invariant (§6.3) and defers the residual edge case to a future cleanup wave.
- **No new evidence sink on `refresh` and `refresh_counterparty`.** Per the §3 D-2.1 evidence-sink matrix, these two routes write only `RFQInvitation` outbox rows today and `RFQInvitation` has no `user_id` column. Cluster 2 preserves this pre-existing absence verbatim: the `actor_sub` parameter on these routes is JWT-sourced (so client-supplied identity can no longer be persisted via these routes either) but no new state event is emitted and no new column is added. Closing this residual gap requires either (a) adding a `user_id` column to `RFQInvitation` (migration), or (b) emitting a new `RFQStateEvent` semantic for refresh actions (lifecycle change that would need its own jury review). Both expand scope past §6.3's single-alembic-head invariant and are recorded for a future audit cycle.
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
   3. Wire `actor_sub` into the **eight** RFQ-mutation routes — the seven actions (reject, cancel, reject-quote, refresh-counterparty, refresh, award, archive) **plus** POST `/rfqs` — and update `RFQService` signatures accordingly. For `RFQService.create`, the new `actor_sub` kwarg must reach the `created → sent` `RFQStateEvent(... user_id=actor_sub)` construction.
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
- Expected Codex catches: missing call site for one of the seven RFQ action routes; `RFQUserActionBase` derived class missed; worker / service-internal caller of an `RFQService` method missed; settlement-related test missing the partial state's regression case; **POST `/rfqs` create-body `user_id` silent-drop missed if the implementing PR only enforces `extra="forbid"` on the action base but not the targeted validator on `RFQCreate`** (this is the exact gap Codex caught on the v1 dispatch — see PR #70 review); **POST `/rfqs` actor evidence missed if the implementing PR only adds the `RFQCreate` validator but does not also wire `actor_sub` into `RFQService.create` and the create-path `RFQStateEvent`** (Codex caught the false "audit_event carries actor" claim on the v2 dispatch — `AuditEvent` has no actor column, so the only canonical actor evidence for RFQ creation is the `RFQStateEvent.user_id` field on the `created → sent` transition); **POST `/rfqs` production-path actor evidence vacuously satisfied if the frontend `counterparty_ids → invitations` contract drift is not also fixed in the same wave** (Codex caught the v3 dispatch with a body-shape mismatch: synthetic backend tests with `invitations: [...]` would pass while UI-created RFQs still produce `payload.invitations = []`, `has_sent = False`, and no `RFQStateEvent`). **Routes don't share a single evidence sink — `RFQStateEvent.user_id` assertions can't be parametrized over every action route**: `refresh` and `refresh_counterparty` write `RFQInvitation` outbox rows only and emit no state event; `reject_quote` writes `RFQQuote.rejected_by` plus a conditional `ALL_QUOTES_REJECTED` state event whose `user_id` is unset today. The v4 dispatch's monolithic "same test repeated for the other six" parametrization would either fail or force the implementer to add new lifecycle events outside the stated boundary; Codex caught this on the v4 dispatch and the v5 amendment splits §3 / §4.1 / §6.1 / §7.1 by evidence-sink class (state-event sink, per-quote sink, no-evidence sink). All four v1–v4 catches are recorded as expected catches so future audit cycles don't re-discover them.
- Pre-emptive dispatch rigor pattern from [[feedback_dispatch_self_consistency]] applies: cross-section sweep before publishing the dispatch is mandatory. The institutional FP class around partial-diff blindness from [[reference_pre_push_hook_calibration]] will likely surface when the implementing branch pushes test-only or schema-only follow-ups.
