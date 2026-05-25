# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Hedge Control Platform — institutional commodity trading and hedging system (LME aluminium and related metals). FastAPI backend + SvelteKit frontend, deployed on Railway. PostgreSQL in production, SQLite in tests.

**This is an institutional financial system, not a prototype.** The Constitution + Governance documents (`docs/systemconstitucion.md`, `docs/governance.md`) are the supreme authority — they override convenience, UX, and "what usually works." When a requested action would violate an explicit constitutional rule, halt and answer with `BLOCKED — requires governance decision`. Optimize for economic correctness, determinism, auditability, and reconstructability.

Non-negotiable rules:
- No silent fallback, no implicit inference, no heuristic correction.
- No mixed pricing/methodology regimes within one endpoint.
- No mutation without evidence (audit trail with HMAC signature).
- Backend is authoritative for economics; frontend is a presenter only.

## Repository Layout

- `backend/` — FastAPI app (Python 3.11/3.12). Entrypoint `app/main.py`. Routers under `app/api/routes/`, services under `app/services/`, ORM models under `app/models/`, Pydantic schemas under `app/schemas/`, core infra (`auth`, `config`, `csrf`, `database`, `rate_limit`, `precision`, `pricing`) under `app/core/`. Alembic migrations under `backend/alembic/versions/` (numbered `001` through `044` plus a fork-merge `036_merge_w1_heads`).
- `frontend-svelte/` — SvelteKit 2 / Svelte 5 / Vite 7 / TS / Tailwind 4. Production frontend. Uses `@clerk/clerk-js` for auth, `openapi-fetch` + generated `src/lib/api/schema.d.ts` for typed API calls, ECharts for charts, Bits UI + Tanstack Table Core for UI. E2E under `frontend-svelte/e2e/` (Playwright). Unit tests under `src/**/*.test.ts` (Vitest + jsdom).
- `frontend/` — **Legacy SAP UI5 frontend, deprecated.** Do not extend it.
- `docs/` — `systemconstitucion.md`, `governance.md` (constitutional source of truth), `runbook-railway.md`, `dev-setup.md`, `audit-protocol/dispatch-review-rules.md`, audit cycle artifacts under `docs/audits/`.
- `.githooks/pre-push` + `scripts/pre_push_review.py` — pre-push LLM dispatch-review hook (see "Pre-push hook" below).
- `Dockerfile` — backend production image; `frontend-svelte/Dockerfile` — frontend image with nginx.
- `docker-compose.yml` — local stack (Postgres 16 + backend + frontend-svelte).

## Common Commands

Backend (run from `backend/`):

```sh
uvicorn app.main:app --reload                    # dev server on :8000
python -m pytest -x -q                           # full test suite (sqlite in-memory)
python -m pytest tests/test_orders.py            # single file
python -m pytest tests/test_orders.py::test_x    # single test
python -m pytest -k "rfq and ranking"            # by keyword
ruff check .                                     # lint (config: backend/ruff.toml)
ruff format .                                    # format
alembic upgrade head                             # apply migrations
alembic revision -m "msg"                        # new migration
```

Frontend (run from `frontend-svelte/`):

```sh
npm run dev                                      # vite dev on :5173
npm run build                                    # production build
npm run check                                    # svelte-kit sync + svelte-check
npm run test                                     # vitest run
npm run test:watch
npm run test:coverage
npm run test:e2e                                 # playwright (needs docker stack running)
npm run test:e2e:smoke                           # backend e2e smoke gate
npm run api:types                                # regen src/lib/api/schema.d.ts from running backend's /openapi.json
npm run api:types:check                          # CI drift guard
```

Monorepo root (`package.json` shortcuts):

```sh
npm run backend:dev                              # backend uvicorn
npm run backend:test                             # backend pytest
npm run test:go-no-go                            # pre-deploy full E2E with markdown report
```

Local stack:

```sh
docker compose up -d db backend frontend-svelte
```

Tests are SQLite-in-memory by default (`tests/conftest.py` autouse fixture drops/creates schema between every test). Most tests run with `app.dependency_overrides[get_current_user]` mocked; JWT auth tests use helpers in `backend/tests/auth_token_helpers.py`. Some autouse fixtures (e.g. `mock_whatsapp`) can be opted out via marker `no_mock_whatsapp` (registered in `backend/pytest.ini`).

## Architecture

### Backend request pipeline

`backend/app/main.py` wires (outer → inner): CORS → CatchAll → StripApiPrefix (`/api/...` → `/...`) → StripTrailingSlash → CSRF (`app/core/csrf.py`) → trace_id (sets `X-Trace-Id`, logs request, records Prometheus `request_latency_seconds`) → router stack. Prometheus instrumentator exposes `/metrics`. Rate limiting via `slowapi` (configured in `app/core/rate_limit.py`, limits set in `Settings.rate_limit_*`).

Routers (mounted in `main.py`): `counterparties`, `orders`, `exposures`, `deals`, `contracts`, `linkages`, `rfqs`, `cashflow`, `cashflow_ledger`, `pl`, `scenario`, `audit`, `westmetall` (under `/market-data/westmetall`), `mtm`, `webhooks`, `csp_report` (under `/csp`), `auth` (no prefix), `finance_pipeline` (under `/finance/pipeline`). WebSocket at `/ws`.

Background scheduler (`app/tasks/scheduler.py`, started via FastAPI lifespan) is **disabled in web workers** via `SCHEDULER_DISABLED=true` (set in Dockerfile CMD + Railway start command). A separate Railway `scheduler` service runs `python -m app.scheduler_main` with `SCHEDULER_DISABLED=false`. Never run two scheduler instances against the same DB.

### Service / domain layout

Services in `app/services/` are the business-logic layer; routers should remain thin (validation + dependency wiring + service call + serialize). Key engines:

- `order_service`, `contract_service`, `counterparty_service` — domain CRUD with audit-trail emission.
- `exposure_engine` + `exposure_service` — commercial + global exposure computation; consumed by `scenario_whatif_service` (read-only, in-memory) for parity.
- `deal_engine` — Deal lifecycle (RFQ → Quote → Award → Contract → Link).
- `rfq_engine` + `rfq_service` + `rfq_orchestrator` + `rfq_message_builder` — RFQ lifecycle + message governance (terms sent = terms stored, canonical id `RFQ#<number>`). Outbound via `whatsapp_providers` (Meta + Twilio). Inbound via `webhook_processor`.
- `mtm_*_service` (`contract`, `order`, `snapshot`) + `pl_calculation_service` + `pl_snapshot_service` — MTM uses D-1 cash settlement; snapshots are append-only / immutable.
- `cashflow_analytic_service` (non-persistent), `cashflow_baseline_service` (persistent record), `cashflow_ledger_service` (accounting), `cashflow_projection_service` (forward-looking, non-persistent, hard-fails on unprovable price refs → HTTP 424). What-if is `scenario_whatif_service` (in-memory only).
- `westmetall_cash_settlement` + `cash_settlement_prices` + `price_lookup_service` + `lme_calendar` — market-data ingest and lookup. **Pricing must come from the canonical provider for the instrument; non-canonical trusted-tier prices are `audit_only` and never feed deals/MTM/P&L/scenarios.** See `docs/governance.md` "MARKET-DATA GOVERNANCE" section.
- `audit_trail_service` — HMAC-signed append-only audit. `AUDIT_SIGNING_KEY` is required (non-empty) in production/staging; `APP_ENV` gates the boot validator.
- `llm_agent` + `whatsapp_service` — LLM-driven WhatsApp message parsing for RFQ inbound.

### RBAC / Authorization

Authoritative matrix is `docs/governance.md` "AUTHORIZATION MATRIX". Three human roles (`trader`, `risk_manager`, `auditor`) + four service identities (`service:westmetall_ingest`, `service:rfq_outbound`, `service:cashflow_pipeline`, `service:webhook_inbound`). Key invariants:

- `auditor` is exclusive — JWT validator rejects mixed sets (e.g. `{trader, auditor}`) with 401 before any route gate.
- `trader` has **per-type Counterparty access** (customer + supplier only; broker/bank rows must be invisible — GET returns 404, never 403, to avoid existence leak).
- `trader` cannot touch HedgeContracts, RFQs, Deals, Linkages, Scenario, MTM/P&L writes, or audit log.
- Audit log routes are auditor-only (no role — not even auditor — can delete audit events).
- `service:webhook_inbound` is exempt from the internal-JWT pattern; provider authentication (Meta `X-Hub-Signature-256` HMAC for POST; Meta `hub.verify_token` shared secret for GET verification challenge) is preserved at ingress.
- Per-route gates live as decorators (`require_role`, `require_any_role`) in `app/core/auth.py`. The RBAC matrix tests are in `tests/test_rbac_matrix_enforcement.py`.

### Database / migrations

SQLAlchemy 2.0 + Alembic. Migrations under `backend/alembic/versions/` follow a numeric chain (`001` → `044`). Chain has one historical merge revision (`036_merge_w1_heads`) — never rewrite ancestry; use a no-op merge revision with a tuple `down_revision` to close forks. `tests/test_alembic_chain.py` guards single-head. SQLite-compatible DDL — Postgres-only types/CHECKs need `with_variant` fallbacks (P2 dispatch rule).

### Precision contract

Money/quantity values are `Decimal` end-to-end. Live float parsing is prohibited on the ingest path — Westmetall ingest must reject `float` inputs and construct via `Decimal(str(raw))` only. See `app/core/precision.py` and `docs/governance.md` "MARKET-DATA GOVERNANCE" precision rules.

### Frontend

SvelteKit 2 + Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`). Routes split by access:
- `src/routes/(public)/` — sign-in
- `src/routes/(protected)/` — authenticated pages

API calls go through `src/lib/api/client.ts` (typed via `src/lib/api/schema.d.ts`, regenerated from backend `/openapi.json`). Auth is Clerk SDK + httpOnly session cookies; CSRF is double-submit cookie + `X-CSRF-Token` header. **VITE_* env vars must live in `frontend-svelte/.env`, not the repo-root `.env`** (Vite envDir). Charts via ECharts (manual chunk split in `vite.config.ts`). CSP is enforced at nginx (`frontend-svelte/nginx.conf`) — Report-Only ramp with violation reporter to `/csp/report`.

## CI / Deployment

GitHub Actions (`.github/workflows/ci.yml`): frontend `npm run check` + `npm run test` + `npm run build` (with ECharts bundle-size budget via `frontend-svelte/scripts/check-bundle-size.sh`); backend `pytest -v` on SQLite-in-memory; E2E Playwright against `docker-compose` stack.

Production runs on Railway (`docs/runbook-railway.md` — read this before touching deployment config). Services: `Postgres`, `backend` (FastAPI + gunicorn + uvicorn workers, healthcheck `/health`), `scheduler` (`python -m app.scheduler_main`, no public domain), `frontend-svelte` (nginx). Critical env vars (`DATABASE_URL`, `SCHEDULER_DISABLED`, `CORS_ALLOW_ORIGINS`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `AUDIT_SIGNING_KEY`, `APP_ENV`, `JWT_ISSUER`, `JWT_AUDIENCE`, `JWKS_URL`, `VITE_API_BASE_URL`, `VITE_CLERK_PUBLISHABLE_KEY`) are owned by the Railway dashboard, **not** by `railway.json`.

## Pre-push dispatch review hook

Repo ships a versioned `.githooks/pre-push` hook that runs an LLM first-sieve review on `docs/**/*-dispatch.md` files before they reach the Codex Connector reviewer. Install once per clone:

```sh
python scripts/install_git_hooks.py
```

This sets `core.hooksPath = .githooks`. The hook needs `ANTHROPIC_API_KEY` in env (loads from `.env` at repo root). Triggers only when dispatch markdown files are in the push range; code-only pushes skip in ~100 ms. Hook blocks (exit 1) on any P1 finding; P2/P3 pass. Bypass with `git push --no-verify` — institutional debt; only do this with explicit orchestrator authorization. Rule sheet: `docs/audit-protocol/dispatch-review-rules.md`. See `docs/dev-setup.md` for full description.

## Audit cycle protocol

Multi-stage adversarial review pattern (Phase A1–A6 closed; Clusters 1–4 cross-phase follow-up in progress). For each audit cycle:
1. Stage 1/2/3 adversarial findings (different frontier models).
2. Jury verdict in `docs/audits/<date>-<phase>-jury-verdict.md`.
3. One dispatch markdown per remediation wave (`docs/audits/<date>-<phase>-pr-N-<topic>-dispatch.md`).
4. Executor session implements one dispatch per PR; Codex Connector reviews.

Codex Connector silent 👍 ships as a `+1` reaction on the PR (not a review). Query `/issues/{N}/reactions` not just `/pulls/{N}/reviews` when checking. Codex catches things that frontier models miss — treat as a high-trust signal.
