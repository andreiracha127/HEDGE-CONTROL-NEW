# E2E Production Readiness — Implementation Dispatch

Cycle: Pilot Hard Blockers (June 2026 launch)
Wave: E2E gate (cross-HB, pre-deploy)
Constitutional anchor: `docs/systemconstitucion.md` (invariants enforced by the suite) + `docs/governance.md` AUTHORIZATION MATRIX appendix + MARKET-DATA GOVERNANCE appendix (3-tier provider trust, 424 on unprovable)
Pilot brief anchor: `docs/audits/2026-05-17-pilot-go-no-go-brief.md` (4 HBs gating pilot; HB-1/HB-2/HB-3 landed via PRs #95/#99/#100; HB-4 still outstanding — this E2E suite is the pre-requisite for HB-4)
Design spec: `docs/superpowers/specs/2026-05-25-e2e-production-readiness-design.md` (commit `9d10d3e`)
Implementation plan: `docs/superpowers/plans/2026-05-25-e2e-production-readiness.md` (commit `ab030ed` — post-Codex-absorption)
Prior precedent: HB-3 implementation dispatch + executor PR #100 (one dispatch = one executor PR pattern)
Findings closed by this wave: enables HB-4 (does not close it directly); institutionalizes regression gate for the constitutional invariants currently relied on by all 3 landed HBs.
Status: READY

---

## §1 Scope

This dispatch prescribes the implementation contract for a single executor PR that will land the full pytest + Playwright E2E production-readiness suite per the implementation plan at `docs/superpowers/plans/2026-05-25-e2e-production-readiness.md` (post-Codex-amendment commit `ab030ed`). The executor PR will land: (a) the backend E2E package `backend/tests/e2e/` containing `__init__.py`, `conftest.py`, `_personas.py`, `_fixtures.py`, `_journey_steps.py`, and SIX spec files (`test_journey_full.py`, `test_rbac_matrix.py`, `test_audit_hmac_chain.py`, `test_precision_contract.py`, `test_market_data_governance.py`, `test_scenario_isolation.py`) per plan Phases 1–7 with TDD discipline (test-first, every step verified); (b) three new Playwright persona specs `frontend-svelte/e2e/journey-trader.spec.ts`, `journey-risk-manager.spec.ts`, `journey-auditor.spec.ts` plus the `_personas.ts` real-backend helper per plan Phase 8; (c) the go/no-go orchestrator pair `scripts/e2e_go_no_go_report.py` (Python aggregator) + `scripts/run_go_no_go.js` (Node orchestrator) plus its unit-test counterpart `scripts/test_e2e_go_no_go_report.py` per plan Phase 9; (d) two GitHub-Actions jobs `e2e-smoke` (blocking on PR) and `e2e-full-post-merge` (artifact upload on push to main) in `.github/workflows/ci.yml` per plan Phase 10; (e) the dual-gated cleanup endpoint `POST /internal/test/cleanup` at `backend/app/api/routes/internal_test.py` with the `require_e2e_cleanup_identity` dependency, the conditional `app.include_router` in `backend/app/main.py` keyed on `APP_ENV=test`, and the SIX acceptance tests in `backend/tests/test_internal_test_endpoint_gated.py` per plan Phase 11 (post-Codex-amendment); (f) four new monorepo-root `package.json` scripts (`test:e2e:smoke`, `test:e2e:backend`, `test:e2e:frontend`, `test:go-no-go`) per plan Phase 0.2; and (g) the `pytest-json-report==1.5.0` dependency in `backend/requirements.txt` per plan Phase 0.3.

The TDD step ordering inside every phase (write failing test → run to verify fail → implement minimal code → run to verify pass → commit) is **binding**, not advisory. Skipping the "run to verify fail" step is a P2 dispatch violation. Each plan task corresponds to one commit on the executor branch; commits are squashed on merge but the per-task commit history MUST be preserved in the PR for reviewer auditability.

The plan is **complete and self-sufficient**: the executor does NOT need to re-derive design choices, file layout, or test shapes. Code blocks in the plan are the binding shape of the deliverable; the executor copies them verbatim and adjusts ONLY the cases enumerated in §4 below.

This dispatch itself is documentation-only — no code change lands via the PR shipping this file. The executor PR opens against the post-dispatch-merge HEAD and is the next task in the orchestrator's pre-HB-4 sequence.

## §2 Boundary

This PR does NOT:

- **Close HB-4.** HB-4 (Audit Daily Report) is explicitly out of scope per spec §1, §2, §8, §10. The suite MUST run green WITHOUT HB-4 — that is the institutional point of this wave (a pre-existing-invariants regression gate that lets HB-4 land against a known-stable surface). The executor MUST NOT add an HB-4 spec file, an audit-daily-report assertion, or any test that depends on HB-4 endpoints/state. If a test fails because an HB-4 surface is missing, that is a dispatch defect (file a follow-up), not a license to write HB-4.
- **Loosen any failing test to make the suite green.** Spec §1 binds: "if a test fails, treat as a production-readiness defect, file a follow-up dispatch, pause execution." The executor MUST NOT weaken assertions, mark tests `xfail`/`skip`, downgrade `assert ==` to `assert in`, or convert status-code assertions to ranges that would have passed under buggy behavior. If a route contract diverges from what the journey-step primitives expect (e.g. the `RFQ#<n>` canonical id format, the D-1 settlement assertion, the 424 on unprovable price), that divergence is the production-readiness defect surfaced by the suite — write the defect up, do NOT erode the test.
- **Introduce silent fallbacks in seed helpers.** Spec §4.1 + plan Task 1.2 bind: seed helpers raise on failure (e.g. `raise TypeError(...)` when float is requested), never silently accept floats and convert them, never silently swap a missing route for a no-op, never return success when the underlying POST/GET reported a non-success status. The institutional rule "no silent fallback, no implicit inference, no heuristic correction" applies to the test infrastructure with equal force.
- **Weaken the dual gate on `/internal/test/cleanup`.** Spec §6 + plan Phase 11 (post-Codex-amendment commit `ab030ed`) bind two independent gates: (i) env gate via `APP_ENV=test`-conditional `app.include_router`, (ii) identity gate via `Depends(require_e2e_cleanup_identity)` rejecting every actor whose `sub != "service:e2e_cleanup"`. The executor MUST NOT drop either gate, MUST NOT widen the identity check to accept role-based actors, MUST NOT replace 403 on wrong-identity with a redirect/200, and MUST NOT swallow deletion errors with a broad `except` (the Codex review absorbed into commit `ab030ed` is binding precedent — the broad `except Exception` was explicitly rejected). The six gating tests enumerated in plan Phase 11 Step 1 are the floor, not the ceiling; the executor may add more, but MUST NOT remove any of the six.
- **Reuse the existing mock-based `frontend-svelte/e2e/helpers.ts` for the new persona specs.** The existing helper module mocks `/auth/*` endpoints via `page.route(...).fulfill(...)` — that is what the legacy `login.spec.ts`/`contracts.spec.ts`/`rfq-lifecycle.spec.ts`/`csp.spec.ts` use. The new persona specs MUST use the NEW `_personas.ts` module per plan Task 8.1 (real backend traffic; `page.route` mocks are forbidden in the journey-* spec files). Cross-importing `loginAsTrader` from the legacy `helpers.ts` defeats the point of the suite. Both helper files coexist; the legacy one is left untouched.
- **Add a new alembic migration.** The full institutional journey (RFQ → Deal → Contract → MTM → P&L → Cashflow → Audit) runs against the **current** schema as of branch HEAD. The cleanup endpoint reads/deletes from existing tables; it does NOT add columns or tables. If a seed helper or journey step turns out to need a schema element that does not exist (e.g. a `trace_id` column on a table that lacks one), that is a production-readiness gap surfaced by the suite — file a separate dispatch, do NOT bundle a migration into this PR.
- **Modify the existing `e2e-playwright` CI job.** Plan Phase 10 Task 10.2 Step 1 binds: "The existing step `run: npx playwright test` runs the entire `e2e/` directory, so the new persona specs are picked up automatically. No edit needed for inclusion." The executor MUST NOT add the persona specs to the existing job's filter, change its `needs:` block, or alter its env/setup. Only the NEW `e2e-smoke` and `e2e-full-post-merge` jobs are added.
- **Touch production code beyond the cleanup-endpoint conditional include.** The only production-code edit in the whole PR is the `if APP_ENV == "test": app.include_router(internal_test_router)` block in `backend/app/main.py` per plan Phase 11 Step 4. The executor MUST NOT refactor existing routes, services, models, or schemas to "make the tests easier." If a route is hard to test, that is a structural finding worth surfacing — file a follow-up, leave the existing code alone. The exception is genuinely contract-level adjustments forced by the suite (e.g. if `/counterparties` returns 200 instead of the matrix-mandated 404 for trader+broker access, that fix is a constitutional bug that MUST be addressed BEFORE the suite can be green; but such a fix lands in a SEPARATE preceding PR, not in this one).
- **Run the full `test:go-no-go` orchestrator from inside CI as a blocking signal.** Per plan §7 and Phase 10 Task 10.2, the orchestrator-driven full run is invoked ONLY on push-to-main (post-merge, non-blocking) and on local pre-deploy. CI smoke is `e2e-smoke` (pytest only, ~90 s). The executor MUST NOT add `npm run test:go-no-go` to the PR-blocking required-checks set. Adding it post-merge as a notify-only artifact uploader is fine and is what plan Phase 10 Task 10.2 already prescribes.
- **Expand persona coverage beyond the matrix-bound set.** Plan Task 1.1 fixes the human-role set at `{trader, risk_manager, auditor}` and the service-identity set at `{service:westmetall_ingest, service:rfq_outbound, service:cashflow_pipeline, service:webhook_inbound, service:e2e_cleanup}`. The webhook_inbound identity is exercised via Meta `X-Hub-Signature-256` HMAC, not JWT — the plan's `as_meta_webhook(raw_body)` helper IS the integration mechanism. The executor MUST NOT add additional roles, additional service identities, or a JWT path for webhook_inbound.

## §3 Pre-step (manual)

Empty for the code PR itself. The executor's branch opens against current main HEAD post-dispatch-merge and runs without infrastructure changes.

Two operational pre-conditions exist BUT they belong to the development environment, NOT to the executor PR:

1. **`pytest-json-report` availability**: plan Phase 0 Task 0.3 appends `pytest-json-report==1.5.0` to `backend/requirements.txt` and runs `pip install -r requirements.txt`. The executor MUST run that install step before attempting Phase 9 Task 9.1 (the report-generator test invokes pytest with `--json-report`); without the dep, the smoke tests still pass but the orchestrator turn fails. This is a sequencing constraint, not a config gap.

2. **Docker stack for Playwright phase**: plan Phase 8 specs (`journey-trader.spec.ts` / `journey-risk-manager.spec.ts` / `journey-auditor.spec.ts`) require the docker-compose stack to be running (`docker compose up -d db backend frontend-svelte`) per existing E2E precedent. The executor MUST verify the stack is up BEFORE attempting Phase 12 Task 12.2; if not up, the failures are environmental and NOT real test failures. Confirm with `curl -sf http://localhost:8000/health`. CI's `e2e-playwright` job already brings up the stack via `docker compose up -d db backend` (no `frontend-svelte` — the workflow builds + serves the frontend manually with `npx serve`); the executor MUST preserve that pattern in CI for the new persona specs.

## §4 Backend changes

The plan defines binding code shapes per phase. The executor copies code blocks verbatim with the following narrow adjustments allowed:

### §4.1 Allowed adjustments to plan code blocks

The plan was authored without exhaustive grep against current `main`. The executor MUST adjust the following IF the actual codebase contract differs from what the plan assumed, but ONLY in the directions enumerated below:

1. **Route paths** — if a route shown in the plan (e.g. `POST /counterparties`, `GET /audit/events`, `POST /mtm/contracts/{id}/snapshot`, `POST /market-data/westmetall/ingest`) is at a different path in `backend/app/api/routes/`, the executor adjusts the helper/test to the actual path. The executor MUST NOT invent a route that does not exist — if the contract is missing, that is a real production-readiness defect (file a follow-up, pause this phase).

2. **Request/response field names** — if the plan's seed helper or journey step expects a JSON field (e.g. `canonical_id`, `mark_value`, `settlement_date`, `signature`, `sequence`, `canonical_payload`, `price_evidence_id`) whose actual key differs in the codebase, the executor adjusts the helper to the actual name AND uses a constant for the renamed field at the top of the helper module so the binding is auditable. The executor MUST NOT silently rename test assertions to whatever the route returns — that erodes the invariant. If the route returns a field shape that violates the spec (e.g. `mark_value` returned as a float), that is the production-readiness defect; file a follow-up.

3. **Status codes** — the plan accepts ranges (e.g. `(200, 201)`, `(200, 201, 409)`) where idempotency or method semantics make multiple responses correct. The executor MUST NOT widen these ranges to include codes that mask bugs (e.g. accepting `500` because "the test isn't ready"). The matrix-bound 404-vs-403 leak guard for trader+broker MUST stay exactly `404`; widening it to `(403, 404)` is forbidden.

4. **Model attribute names** — `AuditEvent.canonical_payload` is the plan's assumption; if the actual column is e.g. `payload_canonical` or `signed_payload`, the executor reads `backend/app/models/audit.py` and adjusts the test. The executor MUST NOT introduce a `canonical_payload` property on the model to make the test happy — adjust the test side to the model.

5. **Cleanup-table set** — plan Phase 11 Step 3 lists `tables_with_trace = ("audit_events", "rfqs", "deals", "hedge_contracts", "counterparties")`. If a listed table does NOT have a `trace_id` column in the actual schema, the executor either (a) adds a `trace_id` parameter to the seed helper that creates rows there (so future runs can clean up), OR (b) accepts that table as one whose cleanup is best-effort and removes it from the set. Option (a) is preferred when feasible. The executor MUST NOT silently `try/except` over the missing column — the post-Codex amendment removed the broad except for precisely this reason; the schema introspection check (`if t not in existing_tables: deleted[t] = -1`) is the binding pattern.

6. **`get_current_user` return shape** — plan Task 1.1 + Task 11.1 assume `{"sub": str, "roles": list[str]}`. If the actual dependency returns a Pydantic model or a different dict shape (e.g. `actor_sub` instead of `sub`), the executor adjusts the dependency override AND the identity-check guard (`if user.get("sub") != "service:e2e_cleanup"` → `if user.actor_sub != ...`). The executor MUST NOT change the production `get_current_user` shape to match the plan; adjust the test side.

### §4.2 Forbidden adjustments

- Replacing the `Depends(require_e2e_cleanup_identity)` guard with a role-based check (`require_role("auditor")`, `require_any_role(...)`, etc.). The identity gate is intentionally narrower than any role; using `auditor` would let a real auditor delete rows in test env, which is the exact failure mode the dual gate prevents.
- Replacing the `if APP_ENV == "test"` boot-time conditional with a "register-always, deny-in-non-test" pattern. Boot-time absence is the strong defense; deny-at-runtime is the secondary defense; both are required.
- Replacing `Decimal(str(...))` with `Decimal(...)` from floats anywhere in `_fixtures.py` or seed helpers. The plan's `seed_westmetall_prices` enforces `raw_floats: bool = False` and `raises TypeError`; the executor MUST preserve that fail-closed shape verbatim.
- Replacing `httpx.Client` with `requests` in `_personas.as_service`/`_persona` full-stack path. The plan binds httpx; the project already depends on httpx via `pip install httpx` in CI.

## §5 Frontend changes

Per plan Phase 8 only. Three new spec files + one new helper module. No edits to existing helpers, no edits to existing specs, no edits to route components.

The persona helper `_personas.ts` ships a `bootstrapPersona` pattern that does NOT call `page.route(...)` to intercept backend traffic. The journey-* spec files must:

- Hit real backend endpoints through the docker-compose stack.
- Render assertions against actual DOM output produced by the real route handlers.
- Use the `data-testid` selectors enumerated in plan Tasks 8.2/8.3/8.4 (`rfq-canonical-id`, `mtm-mark-value`, `audit-event-row`, `audit-event-signature`). If a `data-testid` is missing on the actual Svelte component, the executor adds it (one-line attribute) — this is a permitted UI-test-hook adjustment and the only frontend production-code edit allowed in this PR. Add the attribute with the exact name from the plan.

If a UI surface (e.g. the audit-trail viewer page at `/audit`) does not exist yet in the frontend, that is a production-readiness defect surfaced by the suite — file a follow-up dispatch for the frontend gap and mark the affected Playwright spec `test.skip` with a `// TODO: enable when /audit lands` comment AND a TODO entry in the PR description. This is the ONE place where `test.skip` is permitted; it is not a precedent for skipping any other test.

## §6 Tests

The entire PR IS the tests. Coverage breakdown (mandatory):

- **6 backend e2e spec files** under `backend/tests/e2e/` per plan Phases 2–7. Total expected test count: at least 1 (journey_full) + 13 (rbac_matrix parametrized + mixed-role) + 5 (audit_hmac_chain) + 3 (precision_contract) + 4 (market_data_governance) + 2 (scenario_isolation) = **28 backend e2e tests** at minimum.
- **6 cleanup-endpoint gating tests** per plan Phase 11 Step 1 (correct identity in test env; unauthenticated; wrong service identity; human role including auditor; production env; staging env).
- **3 fixture tests + 3 journey-step tests** under `backend/tests/e2e/test_fixtures.py` + `test_journey_steps.py` per plan Tasks 1.2/1.3.
- **3 orchestrator unit tests** under `scripts/test_e2e_go_no_go_report.py` per plan Task 9.1 (GO verdict, NO-GO on critical failure, override-only-on-non-critical).
- **3 Playwright journey specs** per plan Phase 8.

The pre-existing backend test suite (`backend/tests/test_*.py`, ~1500+ tests) MUST continue to pass unchanged. The pre-existing Playwright specs (`login.spec.ts`/`contracts.spec.ts`/`rfq-lifecycle.spec.ts`/`csp.spec.ts`) MUST continue to pass unchanged. The executor MUST run `cd backend && pytest -v` (full suite) at least once before opening the PR.

## §7 Documentation

The PR ships no new doc files outside the dispatch itself. The plan + spec are already on disk and referenced by anchor. Two documentation updates ARE required as part of the PR:

1. **`CLAUDE.md`** — append a one-line entry under "Common Commands" → frontend section: `npm run test:e2e:smoke              # backend e2e smoke gate`. And under the monorepo root section: `npm run test:go-no-go                 # pre-deploy full E2E with markdown report`. Two lines total.

2. **`docs/runbook-railway.md`** — append a paragraph under the pre-deploy section noting that `npm run test:go-no-go` is the mandatory pre-deploy gate when deploying past pilot day 1, that it writes to `docs/audits/<UTC-date>-go-no-go.md`, and that a `NO-GO` verdict requires either fixing the underlying defect OR explicit `OVERRIDE_RATIONALE=<text>` env var (only valid for `test_scenario_isolation` failures per spec §4.11). Three sentences.

The runbook-railway.md update is institutional: the constitutional invariants the suite enforces ARE the pre-deploy gate, and the runbook is the authoritative operational handle.

## §8 Audit trail

This wave introduces NO new HMAC-signed audit event types. The cleanup endpoint at `POST /internal/test/cleanup` is destructive but exists ONLY in test env (boot-time absent in production/staging); emitting audit events from it would pollute test runs without adding production value. The endpoint's identity gate provides 401/403 rejection observability via standard request-logging infrastructure (Prometheus `request_latency_seconds` + `trace_id` log lines).

The suite consumes the existing audit-trail surface — every journey step asserts HMAC signature integrity on read (`step_read_audit_trail` + `test_audit_hmac_chain.py`). This is the relationship: the suite is a **consumer** of the audit trail, never a **producer**. The executor MUST NOT add `AuditTrailService.record(...)` calls in the cleanup endpoint or in any seed helper.

## §9 Migration plan

Empty. No alembic revisions land in this PR. The current alembic head (`047_pilot_hb_3_finance_pipeline` per HB-3 closure, or whatever the post-HB-3 head is at branch-open time) MUST remain unchanged. The single-head invariant is enforced by `backend/tests/test_alembic_chain.py` and that test MUST continue to pass.

If a fixture or journey step surfaces a need for a `trace_id` column on a table that lacks one (see §4.1 item 5), the executor opens a SEPARATE preceding PR with the migration, lands it, then opens THIS PR on top. The migration PR is out of scope here.

## §10 Acceptance criteria

The PR is mergeable iff ALL of the following are simultaneously true:

1. **All 12 phases of the plan are landed.** Each phase's commit list (per plan Task numbering) is preserved in the PR commit history. Phases skipped or merged together break reviewer auditability; the executor MUST land them in order.

2. **`npm run test:e2e:smoke` passes locally** (≤2 min) — covers `test_journey_full.py` + `test_rbac_matrix.py`.

3. **`npm run test:e2e:backend` passes locally** (full backend e2e, ~5 min) — covers all 6 backend e2e spec files PLUS the orchestrator unit tests under `scripts/`.

4. **Pre-existing backend suite passes** (`cd backend && pytest -v` returns exit 0 across the full ~1500-test suite). Regressions are blocking.

5. **All 3 new Playwright persona specs pass** against a running docker-compose stack (`cd frontend-svelte && npx playwright test journey-trader.spec.ts journey-risk-manager.spec.ts journey-auditor.spec.ts`).

6. **Pre-existing Playwright specs pass** (`login.spec.ts`/`contracts.spec.ts`/`rfq-lifecycle.spec.ts`/`csp.spec.ts`) — regressions are blocking.

7. **`npm run test:go-no-go`** (executed locally with docker stack up) produces `docs/audits/<UTC-date>-go-no-go.md` with `Verdict: GO`, exit code 0.

8. **`POST /internal/test/cleanup` is provably absent in non-test envs.** The two acceptance tests (`test_cleanup_absent_when_production_env`, `test_cleanup_absent_when_staging_env`) pass; manual sanity check: `APP_ENV=production python -c "from app.main import app; print([r.path for r in app.routes if '/internal/test' in getattr(r, 'path', '')])"` returns `[]`.

9. **`POST /internal/test/cleanup` rejects every non-`service:e2e_cleanup` actor** in test env. The four identity-gate tests pass (correct identity → 200; unauthenticated → 401; wrong service identity → 403; human role including auditor → 403).

10. **CI `e2e-smoke` job is required for PR merge.** GitHub Actions branch protection on `main` includes `e2e-smoke` in required status checks AFTER this PR merges (configuration step is a one-line dashboard change post-merge; not blocking PR review).

11. **`CLAUDE.md` and `docs/runbook-railway.md` updated** per §7.

12. **Zero new alembic revisions.** `find backend/alembic/versions/ -name '*.py' -newer <branch-base>` returns empty.

13. **No production code modified beyond the conditional cleanup-router include in `main.py` and (if needed) `data-testid` attribute additions on existing Svelte components per §5.** A `git diff --stat <base>..HEAD -- backend/app/ frontend-svelte/src/` review confirms this. New files under `backend/app/api/routes/internal_test.py` count as new test infrastructure, not "production code modification" in the boundary sense.

14. **`pytest-json-report==1.5.0` is the only new entry in `backend/requirements.txt`.** No incidental dep bumps.

## §11 PR shape

**Branch name:** `feat/e2e-production-readiness`

**Commit history (preserved on PR, squashed on merge):** one commit per plan task. Naming convention: `<type>(e2e): <plan task summary>`. Example sequence:

```
test(e2e): scaffold backend/tests/e2e/ package                         # 0.1
build(e2e): expose test:e2e:smoke / test:go-no-go scripts              # 0.2
build(e2e): add pytest-json-report for go/no-go aggregator             # 0.3
test(e2e): add persona context managers (tri-persona + service ids)    # 1.1
test(e2e): idempotent seeders for counterparties / westmetall / lme    # 1.2
test(e2e): journey step primitives with local invariant assertions     # 1.3
test(e2e): conftest with trace_id and seeded fixtures                  # 1.4
test(e2e): full institutional narrative journey (smoke)                # 2.1
test(e2e): RBAC matrix enforcement under composed journey state        # 3.1
test(e2e): audit HMAC chain integrity + append-only + delete denial    # 4.1
test(e2e): precision contract decimal end-to-end + float reject        # 5.1
test(e2e): market-data governance 3-tier + 424 unprovable + stale      # 6.1
test(e2e): scenario whatif + cashflow projection zero side-effects     # 7.1
test(e2e): persona helpers for real-backend Playwright specs           # 8.1
test(e2e): playwright trader journey spec                              # 8.2
test(e2e): playwright risk-manager journey spec                        # 8.3
test(e2e): playwright auditor journey spec                             # 8.4
feat(e2e): go/no-go report generator with verdict classification       # 9.1
feat(e2e): run_go_no_go.js orchestrator for pre-deploy validation      # 9.2
ci(e2e): add e2e-smoke job blocking PR merge                           # 10.1
ci(e2e): add post-merge full go-no-go job with artifact upload         # 10.2
feat(e2e): /internal/test/cleanup with dual gate (env + identity)      # 11.1
docs(e2e): document test:go-no-go in CLAUDE.md + runbook-railway       # 7 (this dispatch §7)
docs(audits): baseline E2E go-no-go report (suite green)               # 12.3
```

**PR title:** `test(e2e): production readiness suite (pre-HB-4 gate)`

**PR body (template):**

```markdown
## Summary
Implements the E2E production-readiness suite per dispatch
`docs/audits/2026-05-25-e2e-production-readiness-dispatch.md` and plan
`docs/superpowers/plans/2026-05-25-e2e-production-readiness.md`
(post-Codex-amendment commit `ab030ed`).

- 6 backend pytest e2e spec files (~28+ tests) covering the full
  institutional journey + 5 constitutional invariant dimensions.
- 3 Playwright persona journey specs hitting the real docker-compose
  stack via `frontend-svelte/e2e/_personas.ts`.
- `scripts/e2e_go_no_go_report.py` + `scripts/run_go_no_go.js`
  orchestrator producing `docs/audits/<UTC-date>-go-no-go.md`.
- New CI jobs `e2e-smoke` (blocking on PR, ~90s) and
  `e2e-full-post-merge` (artifact upload on main).
- `POST /internal/test/cleanup` with dual gate (`APP_ENV=test` boot
  conditional + `service:e2e_cleanup` identity Depends), 6 acceptance
  tests covering unauthenticated / wrong-identity / wrong-role /
  wrong-env scenarios per Codex review (commit `ab030ed`).

HB-4 (Audit Daily Report) is explicitly out of scope; suite runs
green WITHOUT HB-4 and is a pre-requisite for HB-4 to land.

## Test plan
- [ ] `cd backend && pytest -v` — full backend suite (no regressions)
- [ ] `npm run test:e2e:smoke` — ~90s, GREEN
- [ ] `npm run test:e2e:backend` — all 6 backend e2e files GREEN
- [ ] `npm run test:e2e:frontend` against running docker stack — GREEN
- [ ] `npm run test:go-no-go` — produces `docs/audits/<UTC-date>-go-no-go.md`
      with `Verdict: GO`, exit 0
- [ ] Manual: `APP_ENV=production python -c "..."` confirms cleanup
      route absent in production env

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

**Reviewers:** orchestrator (Andrei) + Greptile auto-trigger + AugmentCode auto-trigger. Codex review is mandatory before merge — invoke `/codex:review` against the branch diff.

**Expected absorption volume:** based on prior precedent (HB-1: 14 fixes / 8 cycles; HB-2: 22 fixes / 9 cycles; HB-3: 7/7 CI / Greptile 5/5 on first push) and the size of this PR (~30+ new files, ~2,800 lines of test code), expect **5–10 absorption iterations**. The pattern-completion-sweep lesson from PR #98 applies in force: when a reviewer flags a structural defect (e.g. a missing `Depends` on one route handler), the executor MUST sweep ALL parallel sites in the same iteration to avoid serialized round-trips.

**Hook v2 behavior:** the dispatch text in this file will trigger the pre-push LLM review hook when the dispatch PR (i.e. THIS file) is pushed. The hook is expected to be green on this dispatch — there are no P1-shaped patterns (no FLOAT_LITERAL on ingest, no DELETE on audit, no role-bypass, no schema mutation, no silent fallback). Any P1 the hook surfaces against THIS dispatch is itself a dispatch defect to absorb pre-merge.

**Post-merge:** the executor PR opens immediately against the post-dispatch-merge HEAD. The orchestrator does NOT batch other waves into the same executor session; this is one dispatch = one PR = one executor session.
