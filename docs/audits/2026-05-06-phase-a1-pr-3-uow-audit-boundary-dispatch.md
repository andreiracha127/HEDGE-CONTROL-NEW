# Phase A1 — PR #3 Dispatch — Unit-of-Work / Audit Boundary

**Wave:** 1 (no dependencies)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-06
**Findings covered:** J-A1-OPUS-06 (Tier 2)
**Branch name:** `audit-a1/uow-audit-boundary`
**Base:** `main` (latest)

---

## 1. Mission

Establish a single, defined boundary where economic mutation commits and signed audit-trail commits compose atomically. Today the service layer commits internally (e.g., `LinkageService.create` calls `session.commit()`) and the route layer marks audit success **after** the commit returned — leaving a window where a crashed/raced post-commit step persists an economic mutation without its audit row.

PR #7 (audit emission for Deal/Exposure routes) depends on this PR — wiring audit calls without first defining the transaction boundary just multiplies the same race surface.

**Persona:** Senior engineer who has lost sleep to half-committed financial transactions in the past. Constitution §2.6 ("no mutation without evidence") and §2.7 (audit-friendly) require evidence and mutation to be atomic. "Almost atomic" is not atomic.

---

## 2. Reference docs

- **`docs/audits/2026-05-06-phase-a1-jury-verdict.md`** — finding J-A1-OPUS-06 (§3 Opus-only). Read in full.
- **`docs/governance.md`** — §2.6, §2.7.
- **`docs/audits/2026-05-06-phase-a1-findings-opus.md`** — F-A1-OPUS-10 for the full Opus mechanism.
- **`backend/app/services/audit_trail_service.py`** — current audit emission pattern (HMAC signing, idempotency expected).
- **`backend/app/api/routes/linkages.py:42-63`** — current "good" wiring (audit_event + mark_audit_success + audit_commit). Use as reference, not target — the goal is to make this pattern enforceable, not to copy it ad-hoc to every route.

---

## 3. Scope IN

### 3.1 Define the boundary

Decide and document one of the following boundary patterns. Choose based on what fits best with the existing audit pattern in `routes/linkages.py:42-63` — this PR's job is to surface that decision and apply it consistently:

**Option A — Service flushes, route commits** (recommended if `audit_trail_service` already supports deferred emission)
- Services use `session.flush()` (not `session.commit()`) so domain objects get IDs without committing
- A FastAPI dependency / context manager owns the commit; emits audit + commits DB in sequence within `try/except` with rollback
- Routes never call `session.commit()` directly

**Option B — Service-managed boundary with audit-aware service**
- Services accept an `audit_context` and emit audit + commit themselves in a single ordered step
- Routes never directly invoke audit; the service is the boundary

**Option C — Outbox pattern**
- Audit row INSERTed in same transaction as economic mutation
- Background worker processes outbox to sign/persist
- Heavier; only choose if A/B can't satisfy "must commit atomically"

**Default recommendation:** Option A unless evidence in the existing code argues for B. Document the choice + reasoning in the PR description.

### 3.2 Refactor the in-scope service paths

Per jury §3 J-A1-OPUS-06, files cited:
- `backend/app/services/linkage_service.py:69` — remove `session.commit()`; flush only
- `backend/app/services/exposure_engine.py:122` — `reconcile_from_orders` commit move
- `backend/app/services/deal_engine.py:143`, `:498` — `create_deal`, `compute_deal_pnl` commit moves
- Any other service in scope with `session.commit()`: grep `backend/app/services/{deal,linkage,exposure,contract}_*.py` and audit each.

For each `commit()` removed:
- Replace with `flush()` if the caller (route) needs IDs for response building
- Otherwise just remove and let the route's commit close the transaction

### 3.3 Update the in-scope routes

Files cited (jury §3 J-A1-OPUS-06):
- `backend/app/api/routes/linkages.py:58-62` — already has audit pattern; refactor to use the new boundary mechanism (dependency / context manager) defined in §3.1.
- `backend/app/api/routes/deals.py` — explicitly out of scope for **adding** audit emission (PR-7 territory). However, when service-layer commits are removed from `DealEngineService`, deal routes MUST consume the **same** boundary mechanism defined in §3.1 — they MUST NOT add bare `session.commit()` calls of their own. The boundary is unified across linkage, deal, exposure routes; PR-7 then plugs `audit_event` emission INTO that single boundary, not around per-route commits. If you add per-route bare commits here, you reintroduce the half-managed commit/audit pattern this PR is meant to eliminate.
- `backend/app/api/routes/exposures.py` — same rule as deals: consume the unified boundary; no bare commits.

Concretely, after this PR every in-scope route should look like one of:
- (Option A) the route relies on a FastAPI dependency that opens a transaction, calls the service (which only flushes), and commits on dependency exit; OR
- (Option B / C as defined in §3.1) the equivalent unified boundary chosen.

A route that calls `session.commit()` directly is a regression of this PR.

### 3.4 Test boundary coverage

The acceptance test for this PR is a failure-injection regression:

- Mock or monkeypatch the audit emission to raise after the service flushes but before the DB commit
- Assert: economic mutation is NOT committed (rolled back)
- Mock the audit emission to succeed but DB commit to fail
- Assert: audit row is NOT persisted (rolled back)
- Mock both succeed
- Assert: both rows present (happy path)

Without this regression test, the boundary fix is unverifiable.

---

## 4. Scope OUT

- **Adding audit emission to Deal/Exposure routes** — PR-7
- **Decimal primitives** — PR-1
- **Order commodity** — PR-2
- **Linkage hardening (over-allocation TOCTOU, direction)** — PR-4
- **Snapshot lifecycle filters** — PR-5
- **Classification invariant** — PR-6
- **P&L price evidence** — PR-8
- **Refactoring HMAC signing in `audit_trail_service`** — leave as-is

---

## 5. Constitutional rules (binding)

- **§2.6** — "No mutation without evidence." Atomicity required: mutation and evidence land together or neither lands.
- **§2.7** — Output contract: audit-friendly. Half-audited mutations are not audit-friendly.

---

## 6. Acceptance criteria (from jury §3 J-A1-OPUS-06)

- [ ] All in-scope service methods (linkage, deal, exposure_engine) no longer call `session.commit()` directly
- [ ] Routes / a designated dependency / context manager own the commit step
- [ ] Audit emission and DB commit are ordered within one defined boundary
- [ ] Failure-injection test: post-flush audit failure rolls back economic mutation
- [ ] Failure-injection test: post-audit DB commit failure rolls back audit
- [ ] Existing happy-path tests pass
- [ ] No service has half-managed commit (mix of flush + commit in same path)
- [ ] PR description documents Option chosen (A/B/C) and rationale

---

## 7. Test coverage required

- `backend/tests/test_uow_boundary.py` — **NEW** — failure injection tests above
- `backend/tests/test_linkages.py` — refactor existing happy-path tests if API surface of `LinkageService.create` changes (likely: no longer commits → callers must commit)
- `backend/tests/test_deal_engine.py` — same: refactor for new boundary
- `backend/tests/test_exposure_engine.py` — same

---

## 8. Critical sequencing

- **Wave 1, no upstream dependencies** — runs in parallel with PR-1, PR-2, PR-6.
- **Downstream:** PR-4 (linkage hardening) depends on PR-1 + this PR. PR-7 depends on this PR.
- If your boundary refactor touches `LinkageService.create` signature, coordinate with PR-4 dispatch (orchestrator will rebase PR-4 on this once it merges).

---

## 9. PR shape

**Title:** `fix(audit-a1): PR-3 — UoW commit/audit boundary (J-A1-OPUS-06)`

**Body skeleton:**

```markdown
## Summary

Establish single defined boundary for economic mutation commits + signed
audit emission. Removes the post-commit window where mutations could land
without audit evidence. Phase A1 jury Tier 2 fix per finding J-A1-OPUS-06
(constitutional §2.6, §2.7).

## Boundary pattern chosen
- Option {A / B / C}
- Rationale: <why>

## Files changed
- Services: linkage_service.py, deal_engine.py, exposure_engine.py
- Routes: linkages.py, deals.py, exposures.py (commit move only — audit wiring in PR-7)
- New: <dependency / context manager file>
- Tests: test_uow_boundary.py + refactored existing service tests

## Acceptance evidence
- Failure-injection tests pass (post-flush audit fail → rollback; post-audit
  commit fail → rollback)
- Existing happy-path tests pass

## Out of scope
- Audit emission on Deal/Exposure routes (PR-7 — depends on this)
- Linkage hardening (PR-4)

## Closes
J-A1-OPUS-06.
```

---

## 10. Constraints

- DO NOT add audit emission to Deal/Exposure routes (PR-7 territory). For this PR, those routes get only the commit-move plumbing.
- DO NOT change `audit_trail_service` HMAC logic
- DO NOT introduce a new ORM session factory — work within `get_session` pattern
- DO NOT use `--no-verify`, no force-push, no auto-merge

---

## 11. Workflow

1. `git fetch origin && git checkout -b audit-a1/uow-audit-boundary origin/main`
2. Read jury verdict §3 J-A1-OPUS-06 + Opus F-A1-OPUS-10 in full
3. Read `routes/linkages.py:42-63` + `audit_trail_service.py` to understand current pattern
4. Decide Option A/B/C; document in PR description draft before coding
5. Implement boundary refactor + tests
6. `git push -u origin audit-a1/uow-audit-boundary`
7. `gh pr create --base main`
8. **STOP. Wait for Codex review.**
9. Address feedback in new commits

---

## 12. Final report shape

- Branch + PR URL + final SHA
- Boundary option chosen + rationale
- Files touched
- Failure-injection test results
- Codex verdict

Under 500 words.

Boa caça.
