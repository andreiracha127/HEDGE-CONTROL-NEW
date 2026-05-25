# E2E Production Readiness — Design

- **Status:** Draft (pending user review)
- **Date:** 2026-05-25
- **Author:** Andrei Rachadel (Claude Opus 4.7 brainstorming session)
- **Scope:** Define the end-to-end test suite that gates production readiness for the Hedge Control platform pilot.

## 1. Purpose & success criteria

Produce a suite of automated tests that, when green, give institutional confidence that the platform is fit to enter the conditional-go pilot defined in the brief at `docs/audits/2026-05-17-pilot-go-no-go-brief.md` (HBs already delivered: HB-1 KYC gate, HB-2 Workflow Approvals, HB-3 Finance Pipeline daily). HB-4 (Audit Daily Report) is explicitly out of scope for this design — the suite must run green **without** HB-4 and serve as a pre-requisite for HB-4 to land.

Success = the suite covers the full institutional journey (RFQ → Deal → Contract → MTM → P&L → Cashflow → Audit) exercised by all three human personas (trader, risk_manager, auditor) and all four service identities (`service:westmetall_ingest`, `service:rfq_outbound`, `service:cashflow_pipeline`, `service:webhook_inbound`), asserting constitutional invariants at every step, with two operational modes:

- **Smoke** — fast (~90s) subset that blocks PRs in CI.
- **Full** — complete (~10 min) suite that produces a markdown go/no-go report consumed pre-deploy.

## 2. Scope decisions (locked)

| Dimension | Choice |
|-----------|--------|
| Coverage scope | Full institutional journey (RFQ→Deal→Contract→MTM→P&L→Cashflow→Audit) |
| Test harness | Pytest backend suite **and** Playwright frontend suite, coordinated |
| Seed strategy | Self-seeding via API per run; cleanup by `trace_id` prefix |
| HB-4 coverage | Out of scope; suite must run green pre-HB-4 |
| Personas | Tri-persona (trader/risk_manager/auditor) + 4 service identities |
| Operational mode | Both: smoke (CI-blocking) + full (manual pre-deploy with markdown report) |

## 3. Architecture & layout

### 3.1 Backend (pytest)

Lives under `backend/tests/e2e/` to keep separate from the existing unit/integration suites under `backend/tests/`.

```
backend/tests/e2e/
├── __init__.py
├── conftest.py                       # Live HTTP client, JWT minters, trace_id, cleanup fixtures
├── _fixtures.py                      # Idempotent seeding helpers
├── _personas.py                      # JWT/HMAC minters for 3 human roles + 4 service identities
├── _journey_steps.py                 # Reusable journey primitives (create_rfq, award, mtm, ...)
├── test_journey_full.py              # Narrative end-to-end (smoke subset)
├── test_rbac_matrix.py               # AUTHORIZATION MATRIX enforcement parametrized (smoke subset)
├── test_audit_hmac_chain.py          # Audit append-only chain + HMAC signature integrity
├── test_precision_contract.py        # Decimal end-to-end; reject float on Westmetall ingest
├── test_market_data_governance.py    # 3-tier provider trust + 424 on unprovable + canonical lookup
└── test_scenario_isolation.py        # Scenario + cashflow_projection in-memory only (no persistence)
```

### 3.2 Frontend (Playwright)

Adds three persona-scoped specs alongside the existing five specs.

```
frontend-svelte/e2e/
├── helpers.ts                        # (existing; extended with persona helpers)
├── _personas.ts                      # Clerk dev session bootstrappers per role
├── journey-trader.spec.ts            # UX path: RFQ creation, supplier hand-off, contract intake
├── journey-risk-manager.spec.ts      # UX path: deal approval, MTM/P&L view, kyc-status surface
├── journey-auditor.spec.ts           # UX path: audit-trail viewer, HMAC chain visualization
├── (existing) contracts.spec.ts
├── (existing) csp.spec.ts
├── (existing) login.spec.ts
└── (existing) rfq-lifecycle.spec.ts
```

### 3.3 Orchestration

```
scripts/
└── e2e_go_no_go_report.py            # Aggregates pytest-json + playwright-json → markdown report
```

`package.json` shortcuts (root):

```json
"test:e2e:smoke": "pytest backend/tests/e2e/test_journey_full.py backend/tests/e2e/test_rbac_matrix.py -v",
"test:go-no-go": "node scripts/run_go_no_go.js"
```

`run_go_no_go.js` orchestrates: docker-compose up → pytest full e2e → playwright full → invoke `e2e_go_no_go_report.py` → write `docs/audits/<UTC-date>-go-no-go.md`.

## 4. Components

### 4.1 `_fixtures.py` — idempotent seeders

- `seed_counterparties(trace_id) -> dict[str, int]`: creates one of each type (customer, supplier, broker, bank). Returns id map. Idempotent: re-run is no-op.
- `seed_westmetall_prices(trace_id, date_range)`: POSTs cash settlement prices for `date_range` via `service:westmetall_ingest`. Decimal-only (strings parsed via `Decimal(str(...))`). Honors 3-tier provider trust matrix.
- `seed_lme_calendar(date_range)`: ensures calendar coverage for tenor lookup spans the journey horizon.
- `cleanup(trace_id)`: deletes all artifacts (counterparties, RFQs, deals, contracts, audit events) prefixed with the trace_id. Implemented via a test-only endpoint `POST /internal/test/cleanup` that is **registered only when `APP_ENV=test`** and gated by service identity `service:e2e_cleanup` (new identity declared in test config; never exists in prod env).

### 4.2 `_personas.py` — identity minters

Each returns a context manager yielding an `httpx.Client` with proper auth state:

- `as_trader()`, `as_risk_manager()`, `as_auditor()`: mint internal JWT via test helper, set `Authorization: Bearer <token>`, perform CSRF double-submit dance (GET `/csrf` then attach `X-CSRF-Token`).
- `as_service(identity_name)` for `service:westmetall_ingest`, `service:rfq_outbound`, `service:cashflow_pipeline`: mint service-identity JWT.
- `as_meta_webhook()`: special — computes Meta `X-Hub-Signature-256` HMAC with `META_APP_SECRET` from test env; bypasses internal JWT per `service:webhook_inbound` ingress contract.

### 4.3 `_journey_steps.py` — journey primitives

Each step performs one canonical action and asserts its local invariant:

| Step | Persona | Local invariant asserted |
|------|---------|--------------------------|
| `step_create_rfq` | trader | Returned id matches `RFQ#<number>` canonical id format |
| `step_simulate_outbound` | service:rfq_outbound | RFQ-outbound-evidence row written; canonical id propagated |
| `step_simulate_inbound_quote` | webhook (HMAC) | Webhook idempotency: 2nd POST with same signature is no-op |
| `step_award_quote` | risk_manager | Deal lifecycle state advances atomically with audit event |
| `step_link_contract` | risk_manager | Linkage created; counterparty type respected |
| `step_run_mtm` | risk_manager | MTM uses D-1 cash settlement (not D); snapshot is immutable |
| `step_compute_pl` | risk_manager | P&L snapshot append-only; price evidence attached |
| `step_compute_cashflow` | service:cashflow_pipeline | Baseline is persistent; projection refuses 424 if price unprovable |
| `step_read_audit_trail` | auditor | HMAC chain verifies; events are append-only |

### 4.4 `test_journey_full.py` — narrative test

Single function `test_full_institutional_journey` runs all 9 steps in order, with a per-test `trace_id` generated at start, asserts the full audit chain integrity at the end, and lets the autouse cleanup fixture tear down on exit.

### 4.5 `test_rbac_matrix.py` — parametrized matrix enforcement

Reads the AUTHORIZATION MATRIX appendix from `docs/governance.md` (already parsed by the existing `tests/test_rbac_matrix_enforcement.py` — reuse the same fixture data). Parametrizes `(role, route, method, expected_status)`. Critical assertions:

- Trader access to broker/bank counterparties returns **404, not 403** (existence-leak guard).
- Trader writes on HedgeContracts, RFQs, Deals, Linkages, Scenario, MTM/P&L, audit log all return 403/404 per matrix.
- Audit log routes are auditor-only; **no role — not even auditor — can delete audit events** (DELETE returns 405 or 403).
- Mixed-set JWTs (e.g. `{trader, auditor}`) are rejected at 401 before any route gate.

### 4.6 `test_audit_hmac_chain.py`

Mutates state across multiple endpoints, then re-reads the audit log and:
- Verifies every event has a non-empty HMAC signature.
- Verifies signatures replay against `AUDIT_SIGNING_KEY`.
- Verifies append-only ordering by sequence number.
- Tampering simulation: directly mutating an event row in test DB and re-verifying → fail.

### 4.7 `test_precision_contract.py`

- POST raw Westmetall payload with a `float` literal field → expect 4xx with `precision_violation` reason.
- POST with stringified Decimal → expect 201 and stored value matches Decimal-exact.
- End-to-end: MTM and P&L computed from seeded prices match expected Decimal values exactly (no rounding drift).

### 4.8 `test_market_data_governance.py`

- Seeded canonical-tier price feeds Deal/MTM/P&L; seeded trusted-tier non-canonical price does **not** (audit_only).
- Cashflow projection at asof date outside seeded price range returns **HTTP 424** (no silent fallback).
- Stale-feed detection: insert price with timestamp older than per-instrument max-gap → marked stale; downstream consumers refuse it.
- Reconciliation: when canonical and trusted-tier observation_keys match with drift > tolerance, drift event is emitted.

### 4.9 `test_scenario_isolation.py`

- Run `scenario_whatif_service` with a perturbation; assert (a) response payload is correct, (b) **no rows are written** to any persistent table (snapshot before/after diff = empty).
- Run cashflow projection; assert same: no persistent side-effect.

### 4.10 Frontend Playwright specs

Each persona spec:
1. Bootstraps a Clerk dev session via `_personas.ts`.
2. Navigates the user through that persona's UX path of the journey (data is seeded via the same backend `_fixtures.py` invoked through an admin route).
3. Asserts rendered Decimal display, status badges, and audit-trail viewer content match the backend state.

Auditor spec specifically renders the audit-trail viewer with HMAC chain visualization and confirms 200 OK + correct event count.

### 4.11 `e2e_go_no_go_report.py` — report generator

Reads:
- `backend/tests/e2e/report.json` (from `pytest --json-report`)
- `frontend-svelte/playwright-report/report.json`

Emits `docs/audits/<UTC-date>-go-no-go.md`:

```markdown
# Go/No-Go Report — 2026-05-25T10:30Z

## Backend (pytest)
- [PASS] journey_full (1/1)
- [PASS] rbac_matrix (47/47)
- [PASS] audit_hmac_chain (8/8)
- [FAIL] precision_contract (12/13) — test_reject_float_on_westmetall_ingest FAILED
- [PASS] market_data_governance (9/9)
- [PASS] scenario_isolation (4/4)

## Frontend (Playwright)
- [PASS] journey-trader (1/1)
- [PASS] journey-risk-manager (1/1)
- [PASS] journey-auditor (1/1)

## Verdict: NO-GO
**1 invariant failure (precision)** — see backend/tests/e2e/report.json for full trace.
```

Verdict logic:

- **Critical specs** (any failure ⇒ unconditional NO-GO, no override possible): `test_journey_full`, `test_rbac_matrix`, `test_audit_hmac_chain`, `test_precision_contract`, `test_market_data_governance`. Plus any failed Playwright persona spec.
- **Non-critical specs** (failure ⇒ NO-GO by default, deploy override possible): `test_scenario_isolation` only. Override requires passing `--override-rationale=<text>` to the report generator; the rationale is recorded verbatim in the markdown report under a "Deploy override" section.

## 5. Data flow

```
[fixture: session scope]
  trace_id = "e2e-" + uuid4().hex[:8]
  seed_counterparties(trace_id)
  seed_westmetall_prices(trace_id, D-30..D)
  seed_lme_calendar(D-30..D+30)
       │
       ▼
[journey + invariants tests: function scope]
  Each test uses a sub-trace_id derived from session trace_id, runs in parallel
  where read-only, sequential where stateful.
       │
       ▼
[teardown: session scope, autouse]
  cleanup(trace_id) regardless of pass/fail
       │
       ▼
[orchestrator]
  pytest --json-report-file=backend/tests/e2e/report.json
  playwright --reporter=json
  python scripts/e2e_go_no_go_report.py → docs/audits/<date>-go-no-go.md
```

## 6. Error handling & determinism

| Risk | Mitigation |
|------|------------|
| Parallel run pollution | Per-run `trace_id` prefix on all seeded artifacts; cleanup by prefix |
| Wall-clock flakiness | All MTM/P&L use seeded `asof_date`; no dependency on `datetime.now()` |
| Cleanup leakage on failure | Autouse session-scope fixture with `try/finally` cleanup |
| Webhook replay | Idempotency key on Meta signature ensures 2nd POST is no-op (this is asserted) |
| Float ingest contamination | Explicit negative test (`test_precision_contract.py`) |
| Test-only endpoint reaching prod | `POST /internal/test/cleanup` registered **only when `APP_ENV=test`**; boot validator refuses registration otherwise |

## 7. Operational modes

| Mode | Command | Scope | Time | Gating |
|------|---------|-------|------|--------|
| Smoke | `npm run test:e2e:smoke` (auto on every PR in CI) | `test_journey_full.py` + `test_rbac_matrix.py` | ~90s | Blocks PR merge |
| Full | `npm run test:go-no-go` (manual pre-deploy) | All backend e2e + all Playwright + markdown report | ~8-10min | Blocks deploy; override needs `--override-rationale` |
| CI post-merge | GitHub Actions on push to main | Same as Full, no manual report | ~5-7min | Notifies (does not auto-revert) |

CI integration (`.github/workflows/ci.yml`):
- New job `e2e-smoke`: depends on `backend-tests`; spins docker-compose; runs smoke. Required for PR merge.
- New job `e2e-full-post-merge`: only on push to main; runs full; uploads report markdown as artifact.

## 8. Out of scope (explicit)

- HB-4 (Audit Daily Report) — to be added when HB-4 lands.
- Performance/load testing — separate concern.
- Browser cross-compat — only Chromium target, matching existing Playwright config.
- Constitution-style adversarial review of the suite itself — handled by the existing audit cycle protocol if needed.

## 9. Open questions

None at design time. (Implementation may surface specifics around the test-only cleanup endpoint surface and whether Meta webhook signature can be replayed against a sandbox `META_APP_SECRET`, but those are implementation details, not design unknowns.)

## 10. Acceptance criteria

- [ ] `backend/tests/e2e/` module exists with all 6 spec files and shared `_fixtures`/`_personas`/`_journey_steps`.
- [ ] `frontend-svelte/e2e/journey-*.spec.ts` exist for trader/risk_manager/auditor.
- [ ] `scripts/e2e_go_no_go_report.py` emits markdown report matching the §4.11 schema.
- [ ] `package.json` exposes `test:e2e:smoke` and `test:go-no-go`.
- [ ] `.github/workflows/ci.yml` runs `e2e-smoke` blocking on PRs.
- [ ] Smoke runs green in <2 minutes on the docker-compose stack.
- [ ] Full runs green in <12 minutes and produces a valid go-no-go report.
- [ ] Test-only `/internal/test/cleanup` endpoint is **provably absent** when `APP_ENV != test` (covered by a dedicated unit test).
- [ ] Suite runs green on `main` HEAD (with HBs 1/2/3 landed, HB-4 absent).

## 11. References

- `docs/systemconstitucion.md` — constitutional invariants the suite must enforce.
- `docs/governance.md` — AUTHORIZATION MATRIX (RBAC source of truth), MARKET-DATA GOVERNANCE appendix.
- `docs/audits/2026-05-17-pilot-go-no-go-brief.md` — conditional-go pilot brief defining HB requirements.
- `docs/audits/2026-05-18-pilot-hb-1-kyc-gate-dispatch.md` — HB-1 contract.
- `docs/audits/2026-05-20-pilot-hb-2-workflow-approvals-dispatch.md` — HB-2 contract.
- `docs/audits/2026-05-20-pilot-hb-3-finance-pipeline-dispatch.md` — HB-3 contract.
- `backend/tests/test_rbac_matrix_enforcement.py` — existing per-route matrix tests (reused for §4.5).
- `frontend-svelte/playwright.config.ts` — existing Playwright config (extended, not replaced).
