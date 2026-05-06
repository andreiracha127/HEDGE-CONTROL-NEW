# Phase A1 — PR #7 Dispatch — Audit Emission for Economic Mutations

**Wave:** 2
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-06
**Findings covered:** J-A1-02 (Tier 1)
**Branch name:** `audit-a1/audit-economic-mutations`
**Base:** `main` (latest, post #15 + #13 + ideally also #14 + #16)
**Upstream deps satisfied:** PR #13 (UoW boundary) MERGED — `unit_of_work` context manager is the boundary into which audit commit plugs; this PR fills it.

---

## 1. Mission

Wire signed audit emission for every route and service path that mutates `Deal`, `DealLink`, `DealPNLSnapshot`, `Exposure`, or hedge task economic status, so that **no economic mutation lands without HMAC-signed audit evidence committed atomically with the mutation**.

PR #13 already shipped the `unit_of_work` context manager that commits route-level mutations and deferred audit rows in one transaction. This PR plugs the missing routes/services into that mechanism — currently `routes/linkages.py` is the only route correctly wired; deal mutation routes and the exposure reconcile route bypass the audit boundary entirely.

**Persona:** Senior engineer enforcing institutional auditability. Constitution §2.6 ("no mutation without evidence") and §2.7 (precise, verifiable, audit-friendly). A signed audit row is the only acceptable proof that a mutation happened.

---

## 2. Reference docs (read before coding)

- **`docs/audits/2026-05-06-phase-a1-jury-verdict.md`** — §2 J-A1-02. Read in full.
- **`docs/governance.md`** — §2.6, §2.7.
- **`docs/audits/2026-05-06-phase-a1-findings-opus.md`** — F-A1-OPUS-02 for full Opus mechanism.
- **Code currently in main (read these before writing):**
  - `backend/app/api/dependencies/audit.py` — `audit_event(...)` factory + `mark_audit_success(request, entity_id)` helper. The canonical emission pattern.
  - `backend/app/api/dependencies/uow.py:9-28` — `unit_of_work` context manager. It calls `request.state.audit_commit()` BEFORE `session.commit()`, atomically.
  - `backend/app/api/routes/linkages.py:48-64` — the **canonical example** of correct wiring. Mirror this pattern exactly; do NOT reinvent.
  - `backend/app/services/audit_trail_service.py:60-98` — `AuditTrailService.record(...)` signature. HMAC-signs payload via `compute_signature(checksum, signing_key)`. The dependency factory uses this service.

The existing pattern at `routes/linkages.py:48-64`:

```python
@router.post(...)
def create_linkage(
    request: Request,
    _: None = Depends(
        audit_event(entity_type="linkage", event_type="created", ...)
    ),
    session: Session = Depends(get_session),
) -> HedgeOrderLinkageRead:
    with unit_of_work(session, request=request):
        linkage = LinkageService.create(session, payload.order_id, payload.contract_id, payload.quantity_mt)
        mark_audit_success(request, linkage.id)
    return HedgeOrderLinkageRead.model_validate(linkage)
```

This is the target shape for every route this PR touches.

---

## 3. Scope IN

### 3.1 Deal mutation routes

**File:** `backend/app/api/routes/deals.py`

Routes to wire (verify exact set by `grep -n "@router\\.\\(post\\|put\\|patch\\|delete\\)" backend/app/api/routes/deals.py`):

- `create_deal` — entity_type="deal", event_type="created"
- `add_link` (or whatever the link-add route is named) — entity_type="deal_link", event_type="created"
- `remove_link` (if exists) — entity_type="deal_link", event_type="deleted"
- `compute_pnl_snapshot` (P&L creation) — entity_type="deal_pnl_snapshot", event_type="created"
- Any other deal-mutating route the executor finds

For each route:
1. Add `request: Request` parameter
2. Add `_: None = Depends(audit_event(entity_type="...", event_type="..."))`
3. Wrap the service call(s) in `with unit_of_work(session, request=request):`
4. Call `mark_audit_success(request, <entity_id>)` immediately after the service returns the entity
5. Remove any direct `session.commit()` from the route (PR-3 already enforced this; verify and clean up if any leftover)

**Service-side:** if any deal service still calls `session.commit()` (it shouldn't post-PR-3 but verify by `grep -n "session\\.commit" backend/app/services/deal_engine.py`), replace with `session.flush()`.

**Special case — services that return `None` (e.g., delete routes).** Verified: `DealEngineService.remove_link(...) -> None` returns nothing. If the executor follows step 4 literally and writes `mark_audit_success(request, service_result)` for a void-returning service, `entity_id` is `None`, the deferred audit dependency raises "entity_id missing", and `unit_of_work` rolls back — every successful delete becomes a 500. Skipping `mark_audit_success` is also wrong: the audit dependency was registered but not finalized, leaving an unaudited committed mutation (the very §2.6 violation this PR removes).

**Fix directive for void-returning services:** use the **path parameter** as the entity_id. Example:

```python
@router.delete("/{deal_id}/links/{link_id}")
def remove_link(
    deal_id: UUID,
    link_id: UUID,
    request: Request,
    _: None = Depends(audit_event(entity_type="deal_link", event_type="deleted")),
    session: Session = Depends(get_session),
):
    with unit_of_work(session, request=request):
        DealEngineService.remove_link(session, deal_id, link_id)
        mark_audit_success(request, link_id)  # ← path parameter, not service result
    return Response(status_code=204)
```

The path parameter is known to the route layer before the service runs and is the canonical identifier of the entity that was just deleted — perfect anchor for the audit row. This pattern applies to **any** delete route (and any service that mutates state but returns `None`); apply it without changing the service signature. Do NOT modify `DealEngineService.remove_link` to return the deleted link just to satisfy the audit pattern — that's needless coupling. The route already has the id.

**Acceptance:** route delete tests must assert (a) the AuditEvent row exists post-delete with `entity_id == link_id`, (b) the link is gone from the DB, (c) HTTP 204 returned (or whatever the existing convention is — verify before assuming).

### 3.2 Exposure reconcile route + service

**File:** `backend/app/api/routes/exposures.py:51-57` (verify line range — main may have shifted post #15 and #13).

The reconcile route currently reads:

```python
@router.post("/reconcile", response_model=ReconcileResponse)
def reconcile_exposures(
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    result = ExposureEngineService.reconcile_from_orders(session)
```

No audit dependency. Reconcile mutates / creates `Exposure` rows without evidence.

**Fix directive — split into two parts:**

**(a) Reconcile run anchor (durable entity for audit_id).** The audit row schema requires `entity_id`. Reconcile doesn't currently produce a durable entity to anchor the audit on. Two options:

- **(a.i) Persist a `ReconciliationRun` row.** New table with id, started_at, completed_at, summary (rows_created, rows_updated, errors). The route emits an audit row with `entity_type="exposure_reconciliation"`, `entity_id=<run.id>`. This is the institutional path — every reconcile produces a durable, queryable anchor.

- **(a.ii) Emit audit per-Exposure-row mutated.** Granular but high-volume; might emit 100s of audits per reconcile invocation. Useful for forensics but expensive.

**Recommendation:** (a.i) for the route-level audit; (a.ii) is out of scope for this PR (would be a Phase A5 concern about cross-cutting audit granularity).

Decide and document in PR description.

**(b) Wire the audit on the reconcile route** with the chosen anchor:

```python
@router.post("/reconcile", response_model=ReconcileResponse)
def reconcile_exposures(
    request: Request,
    _: None = Depends(audit_event(entity_type="exposure_reconciliation", event_type="executed")),
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    with unit_of_work(session, request=request):
        run, result = ExposureEngineService.reconcile_from_orders(session)  # service now returns the run row + summary
        mark_audit_success(request, run.id)
    return ReconcileResponse(...)
```

`ExposureEngineService.reconcile_from_orders` is updated to:
1. Insert a `ReconciliationRun` row at start (status=running)
2. Process orders → update `Exposure` rows
3. On success: update run.status=succeeded, run.summary
4. On any over-allocation hard-fail (PR-4 territory): the exception propagates; `unit_of_work` rolls back; run row is rolled back too — no leftover

**Coordinate with PR #4** which also touches `reconcile_from_orders` (adds the residual hard-fail). Either:
- PR-4 lands first → this PR adds `ReconciliationRun` anchor on top
- This PR lands first → PR-4 rebases onto the new signature

The orchestrator coordinates merge order. From this PR's point of view: **assume PR-4 has not landed yet**; if it has, harmonize the exception handling so the rollback path is consistent.

### 3.3 Hedge task execution route — REQUIRED, not catch-all

**File:** `backend/app/api/routes/exposures.py:85-93` (verify by grep — line numbers may shift).

This is currently:

```python
@router.post("/tasks/{task_id}/execute")
def execute_hedge_task(
    task_id: UUID,
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    with unit_of_work(session):
        task = ExposureEngineService.execute_task(session, task_id)
    return HedgeTaskRead.model_validate(task)
```

`ExposureEngineService.execute_task` mutates `task.status = executed` — a **hedge task economic status** change explicitly named in jury §2 J-A1-02 mission ("...mutates `Deal`, `DealLink`, `DealPNLSnapshot`, `Exposure`, or **hedge task economic status**"). Today it commits via `unit_of_work(session)` but with NO `audit_event` Depends and NO `mark_audit_success` call — the route satisfies the boundary mechanism but not the audit invariant.

**Fix directive (REQUIRED, not optional, not catch-all):**

```python
@router.post("/tasks/{task_id}/execute")
def execute_hedge_task(
    task_id: UUID,
    request: Request,
    _: None = Depends(audit_event(entity_type="hedge_task", event_type="executed")),
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    with unit_of_work(session, request=request):
        task = ExposureEngineService.execute_task(session, task_id)
        mark_audit_success(request, task.id)
    return HedgeTaskRead.model_validate(task)
```

Note that `unit_of_work(session)` becomes `unit_of_work(session, request=request)` so the boundary picks up `request.state.audit_commit`. The `audit_event` Depends factory must include this entity_type/event_type pair in any allowlist that exists in `dependencies/audit.py` — verify and extend if needed (read the current state of that file before assuming).

**Acceptance:** failing to wire this route is the difference between J-A1-02 closed and J-A1-02 left open. The checklist in §6 below makes this row explicit.

### 3.4 Audit signing must be fail-closed (REQUIRED)

**Codex catch on PR #17:** `AuditTrailService.record(...)` currently allows `signature=None` when `_get_signing_key()` returns None (e.g., `AUDIT_SIGNING_KEY` env var unset/empty/misconfigured). Audit row commits unsigned. The §1 mission "no economic mutation lands without HMAC-signed audit evidence" silently fails in any environment where the key isn't configured — exactly the §2.6 violation this PR exists to prevent. The original §6 acceptance "non-NULL when signing key is configured" left this loophole open by qualifier.

**Two layers of defense (both REQUIRED):**

**Layer 1 — Runtime guard in `AuditTrailService.record`:**

Currently:

```python
signing_key = _get_signing_key()
signature = compute_signature(checksum, signing_key) if signing_key else None
audit_event = AuditEvent(..., signature=signature)  # may be None
```

Fix directive (this is a small, scope-local change to `audit_trail_service.py` — explicitly allowed despite the broader scope-out in §4):

```python
signing_key = _get_signing_key()
if not signing_key:
    raise MissingAuditSigningKey(
        "Audit emission attempted without AUDIT_SIGNING_KEY configured. "
        "Audit rows MUST be HMAC-signed; refusing to persist unsigned evidence."
    )
signature = compute_signature(checksum, signing_key)
audit_event = AuditEvent(..., signature=signature)  # always non-NULL
```

`MissingAuditSigningKey` is a new exception class — small, in `audit_trail_service.py`. Routes do not need to catch it; under `unit_of_work` it propagates and rolls back the entire mutation, achieving fail-closed.

**Layer 2 — Startup validation:**

The application settings (typically a `pydantic-settings` BaseSettings subclass at `backend/app/core/config.py` — verify by grep) MUST require `AUDIT_SIGNING_KEY` as non-empty in every environment that exposes a mutation route. Concretely: the field is `str` (not `str | None`) with `Field(min_length=N)` validator, OR a model_validator that enforces presence based on environment.

The aim: production / staging cannot boot without a key. Test environments may set a deterministic test key in `conftest.py` (already convention — verify).

**Both layers required:** Layer 1 alone allows production to boot then fail-closed at first mutation (operator surfaces issue, but only at first emission). Layer 2 alone catches misconfig at boot but doesn't defend against post-boot key removal / dynamic reload edge cases. Together, they make unsigned audit emissions structurally impossible.

### 3.5 Verify other mutation surfaces

The jury cited `routes/deals.py:70-170`, `routes/exposures.py:51-57`, `services/exposure_engine.py:95-122`. Beyond §3.1–3.3, the executor should enumerate every mutating route across the codebase and verify audit emission. Use this two-step procedure (the original one-liner I drafted was broken — `grep -n` emits `file:line:match` records that `head` cannot consume as a file path):

```bash
# Step 1 — list files that contain mutating decorators
grep -rl -E "^@router\.(post|put|patch|delete)" backend/app/api/routes/

# Step 2 — for each file from step 1, list its mutating routes with line numbers
grep -nE "^@router\.(post|put|patch|delete)" backend/app/api/routes/<file>.py
```

Or in one shell-safe pipeline (no xargs substitution into `head`):

```bash
for f in $(grep -rl -E "^@router\.(post|put|patch|delete)" backend/app/api/routes/); do
  echo "=== $f ==="
  grep -nE "^@router\.(post|put|patch|delete)" "$f"
done
```

(Quote the filename in the inner `grep` so paths with spaces or special characters work.)

For each mutating route NOT in `routes/linkages.py` or already-audited surfaces, verify:
- Has `audit_event` dependency? → keep
- Lacks it but is in-scope (deal/exposure/order economic mutation)? → wire it per §3.1 pattern
- Lacks it but is OUT of in-scope (e.g., `/contracts` route — that's PR-6 scope; verify its audit posture but don't modify here unless missing)

Document the audit coverage matrix in the PR description as a table.

---

## 4. Scope OUT — explicitly NOT in PR-7

- **Audit emission for read-only routes** — irrelevant; reads don't mutate
- **Per-row audit on reconcile** — defer to Phase A5
- **HMAC signing key rotation** — Phase A5 territory
- **`audit_trail_service.py` signing logic refactor** — out of scope EXCEPT for the scope-local fail-closed change in §3.5 (a single guard in `record()` to raise when `_get_signing_key()` returns None). Broader changes to HMAC algorithm, signing key derivation, or rotation strategy stay out of scope (Phase A5).
- **RFQ/Quote audit** — Phase A2 territory
- **MTM/Cashflow/P&L audit beyond `compute_pnl_snapshot` route** — Phase A3
- **Authentication/authorization** — Phase A5
- **Rate limiting on mutation routes** — Phase A5

---

## 5. Constitutional rules (binding)

- **§2.6** — "No mutation without evidence." Atomicity required: mutation and audit row land together or neither lands. `unit_of_work` already guarantees atomicity; this PR ensures every mutation is wired to it.
- **§2.7** — Output contract: precise, verifiable, audit-friendly. HMAC-signed audit rows satisfy verifiability; a missing audit row is the violation.

---

## 6. Acceptance criteria (from jury §2 J-A1-02)

- [ ] **Coverage:** every deal-mutating route (create_deal, add/remove_link, compute_pnl_snapshot) emits a signed `AuditEvent` on success
- [ ] **Coverage:** the reconcile route emits a signed `AuditEvent` anchored on a persisted `ReconciliationRun` (entity_id = run.id)
- [ ] **Coverage:** `POST /exposures/tasks/{task_id}/execute` emits a signed `AuditEvent` with entity_type=`hedge_task`, event_type=`executed`, entity_id=`task.id` — fails the test if missing (per §3.3)
- [ ] **Atomicity:** failure-injection test — service raises after `mark_audit_success` is called → `unit_of_work` rollback → no AuditEvent persisted, no Deal/DealLink/Exposure mutation persisted
- [ ] **Atomicity:** failure-injection test — `request.state.audit_commit()` raises (e.g., signing key missing) → `unit_of_work` rollback → no mutation persisted
- [ ] **HMAC fail-closed:** with `AUDIT_SIGNING_KEY` set, `AuditTrailService.record(...)` produces a non-NULL `signature`. With `AUDIT_SIGNING_KEY` absent or empty, `record(...)` MUST raise `MissingAuditSigningKey` (or chosen exception) — NOT persist an unsigned `AuditEvent`. Both paths covered by tests. Per §3.5: any code path persisting `signature=NULL` is forbidden.
- [ ] **Startup validation:** the application's settings validator (e.g., pydantic-settings model) rejects boot when `AUDIT_SIGNING_KEY` is missing in any environment that emits audit events. Verified by a config-loading test.
- [ ] **Verify by inspection:** every mutating route in scope has `audit_event(...)` Depends and is wrapped in `unit_of_work(...)` — prove via a test that scans the FastAPI app's routes and asserts the dependency chain (or a static assertion if scanning is too brittle)
- [ ] **No regression of PR-3:** `test_uow_boundary.py` tests still pass (post-flush audit failure → rollback; post-audit DB commit failure → rollback)
- [ ] **PR description includes audit coverage matrix:** table showing every mutation route and its audit posture (pre/post this PR)

---

## 7. Test coverage required

| Test file | Status | Covers |
|---|---|---|
| `backend/tests/test_audit_economic_mutations.py` | NEW | §6 acceptance criteria; per-route audit emission verification |
| `backend/tests/test_uow_boundary.py` | EXTEND | additional failure-injection cases for the new wired routes |
| `backend/tests/test_deal_engine.py` | EXTEND | deal mutations now require `request` + audit context; refactor existing fixtures if signatures shifted |
| `backend/tests/test_exposure_engine.py` | EXTEND | reconcile now returns `(run, summary)` if §3.2(a.i) chosen; update fixtures |
| `backend/tests/test_reconciliation_run.py` | NEW | `ReconciliationRun` model, migration, service behavior |

Test posture for HMAC: use the project's existing test fixture for signing key (look in `backend/tests/conftest.py` for an `audit_signing_key` fixture pattern; reuse don't reinvent).

---

## 8. Critical sequencing

- **Upstream:** PR #13 (UoW) MERGED. Verify by `grep -l "from app.api.dependencies.uow" backend/app/api/routes/`.
- **Coordinate:** PR-4 (linkage hardening) modifies `reconcile_from_orders` to hard-fail on over-allocation. Either PR-4 lands first (preferred) and this PR's reconcile audit picks up cleanly, or this PR lands first and PR-4 rebases. See §3.2 for handling.
- **Downstream:** none directly. PR-5 and PR-8 are independent of this.

If during implementation you discover that a route already has `audit_event` Depends but is NOT wrapped in `unit_of_work` (the pre-PR-3 pattern), wrap it. That's a regression of PR-3 boundary; surface it to the orchestrator separately.

---

## 9. PR shape

**Title:** `fix(audit-a1): PR-7 — audit emission for deal/exposure economic mutations (J-A1-02)`

**Body skeleton:**

```markdown
## Summary

Wire HMAC-signed audit emission for every economic mutation route that
currently bypasses the audit boundary. Routes covered: deal create,
deal-link add/remove, deal P&L snapshot creation, exposure reconcile.

Builds on PR #13 (`unit_of_work` boundary) — this PR plugs the missing
routes into the existing mechanism. Constitutional §2.6, §2.7.

## Boundary anchor for reconcile
- Chose §3.2 option {a.i / a.ii / hybrid}
- Rationale: <why>

## Audit coverage matrix
| Route | Pre-PR | Post-PR |
|---|---|---|
| POST /linkages | ✓ (PR-3) | ✓ |
| POST /deals | ✗ | ✓ |
| POST /deals/{id}/links | ✗ | ✓ |
| ... | | |

## Files changed
- Routes: deals.py, exposures.py
- Services: deal_engine.py (flush only), exposure_engine.py (returns run+summary)
- Models: reconciliation_run.py (new) [if §3.2(a.i)]
- Alembic: migration `0XX_reconciliation_run.py` [if §3.2(a.i)]
- Tests: test_audit_economic_mutations.py (new), test_reconciliation_run.py (new),
  test_uow_boundary.py, test_deal_engine.py, test_exposure_engine.py

## Acceptance evidence
- Audit coverage matrix in PR description
- Failure-injection tests pass (§6)
- HMAC signature verified non-NULL for signed events

## Out of scope
- Read-only audit (Phase A5)
- Per-row reconcile audit (Phase A5)
- HMAC key rotation (Phase A5)
- RFQ/Quote audit (Phase A2)

## Closes
J-A1-02.
```

---

## 10. Constraints — what NOT to do

- DO NOT modify `audit_trail_service.py` HMAC signing logic
- DO NOT reinvent the audit emission pattern — copy from `routes/linkages.py:48-64`
- DO NOT call `session.commit()` from any route or service (PR-3 boundary preserved)
- DO NOT add audit emission to read-only routes
- DO NOT change `request.state.audit_commit` mechanism (PR-3 owns it)
- DO NOT add audit for RFQ/Quote routes (Phase A2)
- DO NOT add audit for MTM/Cashflow/P&L beyond P&L snapshot creation (Phase A3)
- DO NOT skip the HMAC signature assertion in tests — verifiable signing is the institutional invariant
- DO NOT use `--no-verify`, no force-push, no auto-merge
- DO NOT auto-merge — Codex review mandatory

---

## 11. Workflow

1. `git fetch origin && git checkout -b audit-a1/audit-economic-mutations origin/main`
2. Verify upstream: `git log --oneline origin/main | head -10` shows #13 merge
3. Read jury §2 J-A1-02 + Opus F-A1-OPUS-02 in full
4. Read `routes/linkages.py:48-64` + `dependencies/audit.py` + `dependencies/uow.py`
5. Choose §3.2 option (a.i recommended); document in PR description draft
6. Map every mutating route in `routes/` → audit coverage matrix; identify gaps
7. Implement: model `ReconciliationRun` + migration → reconcile service refactor → routes wiring → tests
8. Run `pytest backend/tests/test_audit_economic_mutations.py backend/tests/test_uow_boundary.py -v` between steps
9. `git push -u origin audit-a1/audit-economic-mutations`
10. `gh pr create --base main`
11. **STOP. Wait for Codex review.**
12. Address feedback in new commits

---

## 12. Final report shape

- Branch + PR URL + final SHA
- §3.2 option chosen + rationale
- Audit coverage matrix (full)
- Failure-injection test results
- HMAC signature verification evidence
- Codex verdict
- Any new findings outside scope (route audit gaps you found that aren't in jury — surface as follow-up issues, do NOT fix in this PR)

Under 600 words.

Boa caça.
