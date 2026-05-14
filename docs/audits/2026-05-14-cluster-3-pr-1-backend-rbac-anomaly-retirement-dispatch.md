# Cluster 3 Implementation Dispatch — PR-CL3-1 — Backend RBAC + Service Accounts + Anomaly Retirement

**Cluster:** 3 — Security / Platform (D-3.1 RBAC matrix enforcement)
**Wave:** PR-CL3-1 (1 of 4)
**Authoring date:** 2026-05-14
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main` (HEAD `e3ad0dffb` post-PR #79, the AUTHORIZATION MATRIX appendix)
**Required branch:** `audit-followup/cluster-3-backend-rbac`
**Source-of-truth:** `docs/governance.md` AUTHORIZATION MATRIX section (lines 188-340 approximately at HEAD `e3ad0dffb`); supersedes any per-route role assignment in code

## 1. Objective

Enforce the AUTHORIZATION MATRIX bindado in `docs/governance.md` (PR #79 merged 2026-05-14). This wave is backend-only and IdP-agnostic — it works with the current generic JWKS validator at `backend/app/core/auth.py` and prepares the helper surface that PR-CL3-2 (Clerk swap) will reuse.

Three coupled deliverables:

1. **`get_current_actor_roles()` helper** — extract role list from JWT payload, enforce auditor-exclusive role combinability (catch #4 of PR #79: `{trader, auditor}` mixed sets MUST raise HTTP 401 at JWT validation time, BEFORE route gates evaluate).
2. **Per-type Counterparty authorization** — implement the per-HTTP-method gates documented in governance §"Authorization invariants" (POST payload-gate / PATCH stored-record-gate + payload-type-mutation-rejection / DELETE stored-record-gate / GET trader-only filter).
3. **Anomaly retirement (8 categories)** — swap per-route role gates to match the matrix, formalize 3 internal-issued service identities (westmetall_ingest, rfq_outbound, cashflow_pipeline) with backend-signed JWT minting + verification, formalize webhook_inbound as audit-trail attribution context (request stays HMAC, NOT swapped to JWT).

The RBAC matrix is canonical (`docs/governance.md` "The RBAC matrix is canonical. A per-route deviation is a constitutional amendment requiring this section's update, not a silent override in code."). Code MUST conform to it.

## 2. Non-Negotiable Constraints

- Do **not** edit `docs/governance.md`. The matrix landed in PR #79; this wave implements it, not amends it.
- Do **not** introduce a new IdP integration. PR-CL3-2 swaps the JWT validator to Clerk; this wave keeps the existing `JWKSCache` mechanism. The dispatch operates on JWT payload claims `sub` and `roles` as already validated by `get_current_user`.
- Do **not** introduce httpOnly cookies. PR-CL3-2 owns cookie management; this wave continues to use Bearer tokens via `_extract_token`.
- Do **not** introduce a CSP change, nginx edit, or frontend code change. PR-CL3-3 + PR-CL3-4 own those.
- Do **not** add a migration. Single alembic head must remain `044_drop_deal_lifecycle_fields`.
- Do **not** widen scope into PR-CL3-2 / PR-CL3-3 / PR-CL3-4 territory.
- Do **not** "loosen" any matrix rule via per-route exception. The matrix says deviation requires constitutional amendment, not silent override.

## 3. Findings and Evidence

Verified at HEAD `e3ad0dffb`.

### Constitutional source-of-truth (PR #79 landing)

- `docs/governance.md` AUTHORIZATION MATRIX section (~line 188-340): 3 human roles (trader / risk_manager / auditor), 4 service identities (1 external-ingress + 3 internal-issued JWT), per-HTTP-method Counterparty authorization, role combinability (auditor exclusive), 7 anomalies enumerated.

### Existing auth surface

- `backend/app/core/auth.py:185-224` — `get_current_user` returns the validated JWT payload dict. JWKS-based, RS256, audience+issuer check.
- `backend/app/core/auth.py:227-242` — `get_current_actor_sub` returns the `sub` claim. Established by Cluster 2 (PR #71).
- `backend/app/core/auth.py:246-265` — `require_role(role)` and `require_any_role(*roles)` factory deps. Both currently consult `user.get("roles", [])` from the JWT payload (verify by reading the body); both raise 403 on missing role.
- `backend/app/core/auth.py:33-42` — `_canonical_env` and `_FAIL_CLOSED_ENVS` for production fail-closed behavior (Phase A5 J-A5-06).

### Anomaly inventory (per governance.md, with line citations)

8 documented anomalies. Each MUST be retired in this wave per governance "Anomalies to be retired upon Cluster 3 implementation closure" preamble; PR-CL3-1 dispatch §3 ALSO requires a sweep of every backend route against the matrix and inclusion of any newly-discovered anomaly in the implementation scope:

1. **Westmetall ingest** (`backend/app/api/routes/westmetall.py:135`, `:184`) — currently `require_role("trader")`. Swap to `require_service_identity("westmetall_ingest")`. Also covers the scheduler/task that triggers ingest (per governance update).
2. **WhatsApp webhook** (`backend/app/api/routes/webhooks.py:309-335` GET, `:339+` POST) — ingress stays as today (Meta `hub.verify_token` for GET, HMAC `X-Hub-Signature-256` / `X-Twilio-Signature` for POST). Internal processing context attributed to `service:webhook_inbound` for audit trail (NOT a route auth swap).
3. **Counterparty CRUD** (`backend/app/api/routes/counterparties.py:23` POST, `:46` GET list, `:75` GET by-id, `:89` PATCH, `:120` DELETE) — apply per-method authorization per governance §"Authorization invariants" + read filter for trader-only effective role.
4. **RFQ workflow** (`backend/app/api/routes/rfqs.py` 10 sites: `:102` POST /rfqs, `:134` POST /preview-text, `:266` POST submit-quote, `:318` reject, `:340` cancel, `:372` reject-quote, `:407` refresh-counterparty, `:441` refresh, `:473` award, `:495` PATCH archive) — swap from `require_role("trader")` to `require_role("risk_manager")`.
5. **HedgeContract lifecycle** (`backend/app/api/routes/contracts.py:41` POST hedge create, `:100` PATCH archive, `:121` PATCH update, `:144` PATCH status, `:164` DELETE) — swap from `require_role("trader")` to `require_role("risk_manager")`.
6. **Deal lifecycle** (`backend/app/api/routes/deals.py:104` POST deal create, `:186` POST add link, `:208` DELETE link, `:235` POST snapshot) — swap from `require_any_role("trader", "risk_manager")` to `require_role("risk_manager")` (drop trader from gate).
7. **Hedge-Order Linkage create** (`backend/app/api/routes/linkages.py:56` POST) — swap from `require_role("trader")` to `require_role("risk_manager")`.
8. **RFQ WebSocket topic subscription** (`backend/app/api/routes/ws.py:7`, `:112`, `:217`) — currently any authenticated JWT can subscribe to `topic == "rfq"` because `ConnectionManager.subscribe(...)` stores the topic with no role gate. Add an explicit `risk_manager` check for `topic == "rfq"` before subscription is recorded. Non-risk-manager actors receive `subscription_error` / forbidden and the subscription MUST NOT be added.

Evidence sweep already performed for the RFQ WebSocket surface: `rg -nP 'topic.*rfq|websocket.*rfq|def subscribe' backend/app/api/routes/ws.py` finds the subscription path above, so it is part of this dispatch rather than a conditional follow-up. The dispatch executor MUST also sweep `rg -nP "@router\\.(post|patch|put|delete)" backend/app/api/routes/` and check every mutation route against the matrix; any additional anomaly found beyond the 8 above MUST be added to the implementation scope of this PR with an inline note in the PR body and reply to whichever Codex catch surfaces it.

### Service identity gaps

- `backend/app/core/auth.py` has no service-account minting/verification helpers today. Need 3 internal-issued JWT helpers (one per identity: westmetall_ingest, rfq_outbound, cashflow_pipeline) using the same JWKS pattern but with backend as issuer. The webhook_inbound identity is processing-context-only (no JWT minting); the route stays HMAC-authed.
- `backend/app/core/audit.py` (or wherever `mark_audit_success` lives) needs to accept `actor_sub` of the form `service:<name>` for service-account writes and persist that as the audit event actor (currently expects human sub; verify by reading the helper).

## 4. Required Implementation Boundary

### 4.1 New `get_current_actor_roles` helper

Add to `backend/app/core/auth.py` between `get_current_actor_sub` and `require_role`:

```python
_VALID_HUMAN_ROLES = frozenset({"trader", "risk_manager", "auditor"})

def get_current_actor_roles(
    user: dict[str, Any] = Depends(get_current_user),
) -> list[str]:
    """Authoritative role set for authorization decisions.

    Validates auditor-exclusive constraint at JWT-validation time per
    docs/governance.md AUTHORIZATION MATRIX > Role combinability:
    auditor MUST NOT be combined with any other human role.
    Mixed sets like {trader, auditor} or {risk_manager, auditor}
    raise HTTP 401 (config error: invalid role combination).
    """
    raw = user.get("roles") if isinstance(user, dict) else None
    if not isinstance(raw, list):
        return []
    roles = sorted({r for r in raw if isinstance(r, str) and r in _VALID_HUMAN_ROLES})
    if user.get("sub") == "anonymous" and roles == ["auditor", "risk_manager", "trader"]:
        # Auth-disabled local/test fallback keeps broad roles for ergonomics;
        # do not let the auditor-exclusive guard break local anonymous flows.
        return roles
    if "auditor" in roles and len(roles) > 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid role combination: auditor must be exclusive",
        )
    return roles
```

Notes:
- Returns sorted, lowercased list of valid human roles only (filters unknown values).
- Service identity "roles" (e.g. `service:westmetall_ingest`) are not in `_VALID_HUMAN_ROLES`; service routes use a separate `require_service_identity` helper (§4.4), not `require_role`/`require_any_role`.
- The 401 fail closes the multi-role escape (governance §"Role combinability" — catch #4 of PR #79). Auditor-exclusive enforcement happens here, BEFORE any route gate.

`require_role` and `require_any_role` MUST be refactored to consume `get_current_actor_roles` (not `get_current_user.roles` directly) so the auditor-exclusive check runs on every authenticated request.

### 4.2 Per-type Counterparty authorization

Refactor `backend/app/api/routes/counterparties.py`:

#### POST `/counterparties` (line 23)

```python
@router.post("", response_model=CounterpartyRead, status_code=status.HTTP_201_CREATED)
def create_counterparty(
    payload: CounterpartyCreate,
    actor_roles: list[str] = Depends(get_current_actor_roles),
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(audit_event(entity_type="counterparty", event_type="created")),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    if "risk_manager" not in actor_roles:
        # trader-only effective role — payload type gate
        if payload.type not in (CounterpartyType.customer, CounterpartyType.supplier):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trader role can only manage customer/supplier counterparties",
            )
    # ... rest unchanged
```

#### PATCH `/counterparties/{counterparty_id}` (line 89)

```python
@router.patch("/{counterparty_id}", response_model=CounterpartyRead)
def update_counterparty(
    counterparty_id: UUID,
    payload: CounterpartyUpdate,
    actor_roles: list[str] = Depends(get_current_actor_roles),
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(audit_event(entity_type="counterparty", event_type="updated")),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    existing = session.get(Counterparty, counterparty_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    if "risk_manager" not in actor_roles:
        # trader-only effective role — stored-record gate
        if existing.type not in (CounterpartyType.customer, CounterpartyType.supplier):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,  # 404 to avoid leaking row existence
                detail="Counterparty not found",
            )
        # Reject any payload field that would mutate `type`. CounterpartyUpdate
        # currently has no `type` field, but the rejection guards future schema
        # evolution.
        payload_dict = payload.model_dump(exclude_unset=True)
        if "type" in payload_dict:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trader role cannot mutate counterparty type",
            )
    # ... rest unchanged
```

#### DELETE `/counterparties/{counterparty_id}` (line 120)

```python
@router.delete("/{counterparty_id}", response_model=CounterpartyRead)
def delete_counterparty(
    counterparty_id: UUID,
    actor_roles: list[str] = Depends(get_current_actor_roles),
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(audit_event(entity_type="counterparty", event_type="deleted")),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    existing = session.get(Counterparty, counterparty_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    if "risk_manager" not in actor_roles:
        # trader-only effective role — stored-record gate
        if existing.type not in (CounterpartyType.customer, CounterpartyType.supplier):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,  # 404 to avoid leaking
                detail="Counterparty not found",
            )
    # ... rest unchanged
```

#### GET list `/counterparties` (line 46) — read filter

```python
@router.get("", response_model=CounterpartyListResponse)
def list_counterparties(
    actor_roles: list[str] = Depends(get_current_actor_roles),
    type: CounterpartyType | None = Query(None),
    # ... existing pagination/filter args ...
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CounterpartyListResponse:
    # Trader-only effective role: server-side type filter to {customer, supplier}.
    # Auditor + risk_manager + mixed (trader+risk_manager) see all 4 types.
    if actor_roles == ["trader"]:  # exactly trader, no other role
        if type is not None and type not in (CounterpartyType.customer, CounterpartyType.supplier):
            # Trader explicitly asked for broker/bank — return empty list (don't
            # leak existence). MUST NOT raise; pagination contract stays.
            return CounterpartyListResponse(items=[], total=0, ...)
        # Force the filter to trader-allowed types regardless of query param.
        effective_types = (CounterpartyType.customer, CounterpartyType.supplier)
        # ... apply effective_types in the SQLAlchemy query
    # ... rest unchanged
```

#### GET by-id `/counterparties/{id}` (line 75) — stored-type gate

```python
@router.get("/{counterparty_id}", response_model=CounterpartyRead)
def get_counterparty(
    counterparty_id: UUID,
    actor_roles: list[str] = Depends(get_current_actor_roles),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    cp = session.get(Counterparty, counterparty_id)
    if cp is None:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    if actor_roles == ["trader"]:
        if cp.type not in (CounterpartyType.customer, CounterpartyType.supplier):
            # 404 (NOT 403) to avoid leaking row existence
            raise HTTPException(status_code=404, detail="Counterparty not found")
    # ... rest unchanged
```

### 4.3 Anomaly retirement (per §3 inventory)

| Site | Before | After |
|---|---|---|
| `westmetall.py:135` | `require_role("trader")` | `require_service_identity("westmetall_ingest")` |
| `westmetall.py:184` | `require_role("trader")` | `require_service_identity("westmetall_ingest")` |
| `rfqs.py:113`, `:137`, `:280`, `:330`, `:352`, `:385`, `:419`, `:453`, `:485`, `:507` (10 sites) | `require_role("trader")` | `require_role("risk_manager")` |
| `contracts.py:41`, `:100`, `:121`, `:144`, `:164` (5 sites) | `require_role("trader")` | `require_role("risk_manager")` |
| `deals.py:104`, `:186`, `:208`, `:235` (4 sites) | `require_any_role("trader", "risk_manager")` | `require_role("risk_manager")` (drop trader) |
| `linkages.py:56` | `require_role("trader")` | `require_role("risk_manager")` |
| `webhooks.py:309-335` GET, `:339+` POST | unauthed / HMAC-only | unchanged at route gate; downstream operations attribute `actor_sub="service:webhook_inbound"` to audit events |

For every site swapped, also verify the `actor_sub: str = Depends(get_current_actor_sub)` parameter exists (Cluster 2 pattern). If absent on a mutation route, ADD it; the actor_sub is part of the audit-event metadata recipe.

### 4.4 Service identity helpers

Add to `backend/app/core/auth.py`:

```python
_INTERNAL_SERVICE_IDENTITIES = frozenset({
    "service:westmetall_ingest",
    "service:rfq_outbound",
    "service:cashflow_pipeline",
})

def require_service_identity(name: str):
    """Route gate for internal-issued service-account JWTs.

    Validates that the actor_sub matches `service:<name>` exactly.
    Use for routes confined to a single service identity (e.g. westmetall
    ingest cron, cashflow_pipeline workers).
    """
    expected = f"service:{name}" if not name.startswith("service:") else name
    if expected not in _INTERNAL_SERVICE_IDENTITIES:
        raise ValueError(f"Unknown service identity: {expected}")

    def _gate(actor_sub: str = Depends(get_current_actor_sub)) -> None:
        if actor_sub != expected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Service identity {expected} required",
            )
    return _gate
```

Service-identity JWT minting is OUT of scope here (will land in PR-CL3-2 alongside the Clerk integration, since both use the same JWKS infrastructure). For PR-CL3-1, the service-identity routes use the existing `get_current_actor_sub` and the new `require_service_identity` helper; the JWT issuance lives in a TODO until PR-CL3-2.

For the `westmetall.py:135`/`:184` swap to land cleanly without minting being available yet, add a temporary fixture: when `_canonical_env() not in _FAIL_CLOSED_ENVS` (i.e. dev/test), accept actor_sub `service:westmetall_ingest` from a dev-only env var `DEV_SERVICE_ACTOR_SUB` for local cron testing. Production (and tests via override) must use real JWT issued by PR-CL3-2.

### 4.5 webhook_inbound audit attribution

In `backend/app/api/routes/webhooks.py` POST handler (line `:339+` per §3) and any downstream sink (message persistence, RFQ correlation, audit_event calls):

- Replace any `actor_sub=None` or unset actor_sub in `mark_audit_success(...)` calls with `actor_sub="service:webhook_inbound"`.
- Where `mark_audit_success` does not currently accept actor_sub override (e.g. binds from request context), add an explicit `metadata={"actor_sub": "service:webhook_inbound"}` argument so the audit event payload records the service identity.
- Verify by `rg -nP 'mark_audit_success' backend/app/api/routes/webhooks.py backend/app/services/whatsapp_*` and confirm every call after HMAC validation either receives `actor_sub="service:webhook_inbound"` directly OR has `metadata` with that field.

The HMAC validation logic in the POST handler stays unchanged.

### 4.6 RFQ WebSocket topic

Per governance update (PR #79 catch absorption), the RFQ WebSocket topic `"rfq"` is part of RFQ surface. The route exists in `backend/app/api/routes/ws.py`; implement the gate directly, do not leave it as sweep-only discovery.

Required implementation:

- Add a pure helper in `backend/app/core/auth.py` that validates/extracts human roles from a JWT payload dict without `Depends`, and have `get_current_actor_roles(...)` call that helper. The WebSocket path can then reuse exactly the same filtering + auditor-exclusive logic as HTTP routes.
- In `backend/app/api/routes/ws.py`, before `await manager.subscribe(ws, topic, topic_id)`, if `topic == "rfq"` then read `manager.get_user(ws)`, extract roles with the shared helper, and require `"risk_manager" in roles`.
- If the RFQ-topic role check fails, return a `subscription_error` with reason `"forbidden"` (or equivalent stable code), and do not add `(topic, topic_id)` to `state.subscriptions`.
- Non-RFQ topics remain unchanged unless the governance matrix explicitly classifies them.

## 5. Constitutional Rules

This wave is governed by:

- `docs/governance.md` AUTHORIZATION MATRIX (entire section, lines ~188-340 at HEAD `e3ad0dffb`) — the canonical RBAC contract.
- `docs/governance.md` §"GOVERNANCE HARD FAILS" — "No mutation without evidence" (audit_event + actor_sub on every mutation route).
- `docs/governance.md` §2.7 (audit reconstructability) — actor_sub on every audit event makes the actor identifiable.

No changes to `docs/governance.md` are part of this wave.

## 6. Acceptance Criteria

A merged PR closes D-3.1 (RBAC enforcement portion) iff every item below is true.

### 6.1 Helper surface

- [ ] `backend/app/core/auth.py` — `get_current_actor_roles` exists with the signature and auditor-exclusive validation in §4.1.
- [ ] `backend/app/core/auth.py` — `require_role` and `require_any_role` consume `get_current_actor_roles` (verify via grep that they no longer read `user.roles` directly).
- [ ] `backend/app/core/auth.py` — `require_service_identity(name)` factory exists per §4.4.
- [ ] `backend/app/core/auth.py` — `_VALID_HUMAN_ROLES` and `_INTERNAL_SERVICE_IDENTITIES` frozensets exist.

### 6.2 Counterparty per-type authorization

- [ ] `backend/app/api/routes/counterparties.py` POST (`:23`) — payload-type gate per §4.2.
- [ ] `backend/app/api/routes/counterparties.py` PATCH (`:89`) — stored-record gate + payload type-mutation rejection per §4.2.
- [ ] `backend/app/api/routes/counterparties.py` DELETE (`:120`) — stored-record gate per §4.2.
- [ ] `backend/app/api/routes/counterparties.py` GET list (`:46`) — server-side type filter for trader-only-effective role per §4.2.
- [ ] `backend/app/api/routes/counterparties.py` GET by-id (`:75`) — stored-type assert + 404 (NOT 403) for trader-only on broker/bank per §4.2.

### 6.3 Anomaly retirement (8 categories)

- [ ] `westmetall.py:135`, `:184` swapped to `require_service_identity("westmetall_ingest")`.
- [ ] `webhooks.py:309-335` GET + `:339+` POST: route gate UNCHANGED; downstream `actor_sub="service:webhook_inbound"` plumbed to audit-event metadata.
- [ ] `rfqs.py` 10 sites swapped to `require_role("risk_manager")`. Sweep `rg -nP 'require_role\\("trader"\\)' backend/app/api/routes/rfqs.py` → zero matches.
- [ ] `contracts.py` 5 sites swapped to `require_role("risk_manager")`. Sweep `rg -nP 'require_role\\("trader"\\)' backend/app/api/routes/contracts.py` → zero matches.
- [ ] `deals.py` 4 mutation sites swapped to `require_role("risk_manager")` (drop trader). Sweep `rg -nP 'require_any_role\\("trader", "risk_manager"\\)' backend/app/api/routes/deals.py` → matches only on read sites (not on mutation).
- [ ] `linkages.py:56` swapped to `require_role("risk_manager")`.
- [ ] RFQ WebSocket topic `"rfq"` subscription in `ws.py` requires `risk_manager` before subscription state is written.

### 6.4 Sweep for newly-discovered anomalies

- [ ] `rg -nP "@router\\.(post|patch|put|delete)" backend/app/api/routes/` cross-checked against the matrix. Any route currently `trader`-gated but classified as risk_manager-only by the matrix is added to the implementation scope. Findings documented in PR body.
- [ ] `rg -nP 'topic.*rfq|websocket.*rfq|def subscribe' backend/app/api/routes/ws.py` confirms the RFQ WebSocket path covered by §3.8 is implemented, not left as conditional discovery.
- [ ] `rg -nP 'require_role|require_any_role' backend/app/api/routes/` — every mutation gate matches the matrix. Read gates may include all 3 human roles where appropriate.

### 6.5 Cross-cutting

- [ ] `docs/governance.md` diff is empty.
- [ ] No frontend file changed (`git diff main -- frontend-svelte/` empty).
- [ ] No nginx config changed.
- [ ] No new alembic migration. Single head remains `044_drop_deal_lifecycle_fields`.
- [ ] `mark_audit_success` calls on swapped mutation routes include the actor_sub (Cluster 2 pattern preserved).

## 7. Required Tests

### 7.1 New test file `backend/tests/test_rbac_matrix_enforcement.py`

Per-route role acceptance/rejection matrix. ONE test per (route, role, expected status code) tuple:

1. **`test_get_current_actor_roles_filters_unknown_values`** — JWT payload with `roles=["trader", "garbage", "admin"]` → returns `["trader"]`.
2. **`test_get_current_actor_roles_rejects_auditor_with_trader`** — JWT payload with `roles=["auditor", "trader"]` → raises HTTP 401 with detail "Invalid role combination".
3. **`test_get_current_actor_roles_rejects_auditor_with_risk_manager`** — same but `["auditor", "risk_manager"]` → raises HTTP 401.
4. **`test_get_current_actor_roles_accepts_trader_plus_risk_manager`** — JWT payload with `roles=["trader", "risk_manager"]` → returns `["risk_manager", "trader"]` (sorted).
5. **`test_counterparty_post_trader_rejects_broker`** — trader-only JWT POSTs counterparty with `type=broker` → 403.
6. **`test_counterparty_post_trader_accepts_customer`** — trader-only JWT POSTs counterparty with `type=customer` → 201.
7. **`test_counterparty_post_risk_manager_accepts_broker`** — risk_manager JWT POSTs counterparty with `type=broker` → 201.
8. **`test_counterparty_patch_trader_rejects_broker`** — fixture: existing broker counterparty. Trader-only JWT PATCHes → 404.
9. **`test_counterparty_patch_trader_accepts_customer`** — fixture: existing customer counterparty. Trader-only JWT PATCHes → 200.
10. **`test_counterparty_delete_trader_rejects_broker`** — fixture: existing broker. Trader-only JWT DELETEs → 404.
11. **`test_counterparty_get_list_trader_filters_broker_bank`** — fixture: 4 counterparties, one per type. Trader-only JWT GETs list → only customer + supplier rows returned.
12. **`test_counterparty_get_by_id_trader_404s_broker`** — fixture: existing broker. Trader-only JWT GETs by-id → 404.
13. **`test_counterparty_get_by_id_auditor_returns_broker`** — fixture: existing broker. Auditor JWT GETs by-id → 200 (auditor reads everything).

### 7.2 Per-route role rejection matrix

For each retired anomaly site, ONE test per (role, expected status):

14. **`test_westmetall_ingest_trader_rejected`** — trader JWT POSTs westmetall ingest → 403.
15. **`test_westmetall_ingest_service_identity_accepts`** — JWT with `sub="service:westmetall_ingest"` → 200 (or appropriate success).
16. **`test_rfq_create_trader_rejected`** — trader JWT POSTs RFQ → 403.
17. **`test_rfq_create_risk_manager_accepts`** — risk_manager JWT POSTs RFQ → 201.
18. **`test_rfq_award_trader_rejected`** — trader JWT POSTs RFQ award action → 403.
19. **`test_hedge_create_trader_rejected`** — trader JWT POSTs hedge contract → 403.
20. **`test_hedge_archive_trader_rejected`** — trader JWT PATCHes hedge archive → 403.
21. **`test_hedge_create_risk_manager_accepts`** — risk_manager JWT POSTs hedge contract → 201.
22. **`test_deal_create_trader_rejected`** — trader JWT POSTs deal create → 403.
23. **`test_deal_create_risk_manager_accepts`** — risk_manager JWT POSTs deal → 201.
24. **`test_deal_add_link_trader_rejected`** — trader JWT POSTs deal link → 403.
25. **`test_linkage_create_trader_rejected`** — trader JWT POSTs hedge-order linkage → 403.
26. **`test_linkage_create_risk_manager_accepts`** — risk_manager JWT POSTs linkage → 201.

### 7.3 webhook attribution

27. **`test_webhook_post_attributes_to_service_webhook_inbound`** — POST `/webhooks/whatsapp` with valid HMAC + Meta-shaped payload. Assert audit event row written for any downstream mutation has `metadata["actor_sub"] == "service:webhook_inbound"`.

### 7.4 RFQ WebSocket topic gate

28. **`test_ws_rfq_subscription_requires_risk_manager`** — authenticate with JWT roles `["trader"]`, send `{"action":"subscribe","topic":"rfq","id":"<uuid>"}`, assert `subscription_error` / forbidden and no subscription is recorded.
29. **`test_ws_rfq_subscription_accepts_risk_manager`** — authenticate with JWT roles `["risk_manager"]`, send the same RFQ subscription, assert `subscription_ack`.

### 7.5 Existing tests must continue to pass

- `backend/tests/test_audit_economic_mutations.py` and any other test that mocks JWT payloads MUST be updated to provide `roles=["risk_manager"]` (or appropriate) on mutation route fixtures since trader is no longer accepted on most mutation routes.
- `backend/tests/test_*.py` sweep: any existing test that sent `roles=["trader"]` to a now-risk_manager-only route MUST be updated.

## 8. Required Verification

```powershell
# Helper surface sweeps
rg -nP "def get_current_actor_roles" backend/app/core/auth.py
rg -nP "def require_service_identity" backend/app/core/auth.py
rg -nP "_VALID_HUMAN_ROLES|_INTERNAL_SERVICE_IDENTITIES" backend/app/core/auth.py

# Anomaly retirement sweeps (every one MUST be zero)
rg -nP 'require_role\("trader"\)' backend/app/api/routes/westmetall.py
rg -nP 'require_role\("trader"\)' backend/app/api/routes/rfqs.py
rg -nP 'require_role\("trader"\)' backend/app/api/routes/contracts.py
rg -nP 'require_role\("trader"\)' backend/app/api/routes/linkages.py

# Deal: trader allowed only on read routes
rg -nP 'require_any_role\("trader", "risk_manager"\)' backend/app/api/routes/deals.py
# (verify every match is on a GET handler, not POST/PATCH/DELETE)

# webhook attribution
rg -nP 'service:webhook_inbound' backend/app/api/routes/webhooks.py backend/app/services/whatsapp_*

# Counterparty per-type assertions present in routes
rg -nP 'CounterpartyType\.customer|CounterpartyType\.supplier' backend/app/api/routes/counterparties.py

# RFQ WebSocket topic gate
rg -nP 'topic.*rfq|websocket.*rfq|def subscribe' backend/app/api/routes/ws.py
rg -nP 'risk_manager|subscription_error' backend/app/api/routes/ws.py

# Cross-wave isolation
git diff main -- frontend-svelte/
git diff main -- frontend-svelte/nginx.conf
git diff main -- docs/governance.md

# Alembic invariant
cd backend ; python -m alembic heads ; cd ..

# Test suites
pytest -q backend/tests/test_rbac_matrix_enforcement.py
pytest -q backend/tests
```

`docs/governance.md` diff MUST be empty. Frontend + nginx diffs MUST be empty. Alembic head MUST be `044_drop_deal_lifecycle_fields`.

## 9. Out of Scope

- PR-CL3-2 territory: Clerk JWT validation swap, httpOnly cookie set/refresh, CSRF rotation, service-account JWT minting (the issuance side; this wave only adds the verification helpers).
- PR-CL3-3 territory: frontend Clerk SDK integration, kill `manualTokenLoginEnabled`.
- PR-CL3-4 territory: nginx CSP swap, violation reporter endpoint, XSS-sink inventory doc.
- Any change to `docs/governance.md` — the matrix is canonical and landed in PR #79.
- Any new IdP. The current JWKS validator stays.
- Frontend role-display changes (e.g. UI hiding broker/bank options for trader). The matrix is server-enforced; frontend hardening is a follow-up.
- Adding new audit event types or columns to `audit_events`. The actor_sub plumbing reuses existing schema.

## 10. PR Requirements

The implementing PR title must be:

```
fix(audit-followup): close Cluster 3 PR-CL3-1 (Backend RBAC matrix enforcement + service identities + anomaly retirement)
```

The PR body must include:

- **Findings closed:** explicit `D-3.1` reference + governance.md AUTHORIZATION MATRIX citation.
- **Files changed:** inventory grouped by helper / route / test.
- **Anomaly retirement matrix:** §3 inventory with line citations + before/after gates.
- **Sweep results:** §8 verification commands and outputs.
- **Newly-discovered anomalies (if any):** documented in PR body with line citations + retirement applied in this PR.
- **Hook artifact paths:** `.cache/dispatch_review/audit-followup-cluster-3-backend-rbac-{sha}.json` per push.
- **Governance statement:** `docs/governance.md` diff is empty.
- **Alembic statement:** single head `044_drop_deal_lifecycle_fields`.

## 11. Workflow

1. `git checkout -b audit-followup/cluster-3-backend-rbac` from `main @ e3ad0dffb` (post-PR #79).
2. Apply §4.1 (helpers) first. Run `pytest -q backend/tests/test_rbac_matrix_enforcement.py::test_get_current_actor_roles_*` (write tests in §7.1 first if TDD-ing).
3. Apply §4.2 (Counterparty per-type) — refactor the 5 routes.
4. Apply §4.3 (anomaly retirement) — swap each gate per the table. Sweep §8 between steps to confirm zero leftovers.
5. Apply §4.4 (service identity helpers).
6. Apply §4.5 (webhook attribution) — verify `mark_audit_success` calls receive the right actor_sub.
7. Apply §4.6 (RFQ WebSocket topic gate).
8. Update existing tests that broke (§7.4 sweep).
9. Run §8 verification locally; fix every hook v2 P1/P2 in place.
10. Push branch and open PR per §10.
11. Codex Connector review is the final gate. Address every Codex inline catch. **Do not merge** — Andrei merges with explicit authorization only.

## 12. Hook v2 + Codex calibration notes

- **Expected hook v2 surface area:** medium-large (helper additions + 5 Counterparty routes + ~20 anomaly site swaps + webhook attribution + ~27 new tests). Hook may flag prescription-vs-evidence on the new helper names (`get_current_actor_roles`, `require_service_identity`, `_VALID_HUMAN_ROLES`) before they exist — known FP class.
- **Expected Codex catches:**
  - Missing role-mutation rejection in PATCH Counterparty (catch the `payload_dict["type"]` rejection branch).
  - Missing 404-vs-403 for trader on broker/bank in GET by-id (information leakage).
  - Test fixtures that still send `roles=["trader"]` to risk_manager-only routes (broken existing tests).
  - Newly-discovered anomalies the dispatch §3 inventory missed — Codex inspects route-by-route and may surface routes the matrix prohibits but the dispatch didn't enumerate. Absorb by adding to anomaly retirement scope.
  - `webhook_inbound` actor_sub plumbing missing in any downstream sink (RFQ correlation, message persistence). Sweep both `webhooks.py` and `whatsapp_*` services.
  - `audit_events` table query MUST find rows with `metadata["actor_sub"] == "service:webhook_inbound"` after webhook POST — if Codex inspects test #27 and the fixture doesn't actually trigger an audit_event, the test is a regression-guard for nothing.
- **Padrão estabelecido por PR #79 (16 catches absorbed):** governance docs receive intense Codex scrutiny. The IMPLEMENTATION PR will be checked against the governance text rigorously. Every layer of the matrix WILL be cross-referenced. Be precise.
- **8-section sweep checklist from `feedback_dispatch_self_consistency`:** §3 evidence, §4 boundary, §6 acceptance, §7 tests, §8 verification, §11 workflow MUST consistently enumerate the same 8 anomaly categories + Counterparty per-type subsections + helpers. Drift between sections is the canonical authoring failure mode.
- **The largest authoring risk** is missing newly-discovered anomalies. The dispatch §3 inventory is the documented set, including the RFQ WebSocket topic gate discovered by sweep; the §6.4 sweep is the institutional protection for any additional route drift. If the executor skips the sweep, Codex WILL find anomalies the dispatch didn't enumerate (governance.md preamble explicitly mandates the sweep — "list is documented set, not exhaustive guarantee").
