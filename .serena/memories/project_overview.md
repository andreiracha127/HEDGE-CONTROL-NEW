# Hedge Control Platform — Project Overview

## Purpose
Institutional commodity trading & hedging platform ("Alcast Hedge Control Platform"). Provides REST APIs for exposures, orders, RFQs, contracts, deals, counterparties, cashflow, P&L, MTM, scenarios (what-if), audit trail, and market data. Production-grade financial system — **not a prototype**.

## Top-level layout (monorepo)
- `backend/` — FastAPI service (Python 3.11)
- `frontend-svelte/` — SvelteKit frontend (Svelte 5, Tailwind v4) — sole frontend (UI5 was deprecated 2026-05-06).
- `docs/` — governance, plans, integration audit, performance, gap analysis, **`runbook-railway.md`** (Railway operational runbook).
- `schemas/` — JSON Schemas for canonical entities (cashflow, contract, exposure, orders, pl, rfq, scenario)
- `locust/` — load testing
- `docker-compose.yml`, root `Dockerfile`, `railway.json`, `frontend-svelte/railway.json` — local stack + Railway config-as-code.
- Many `PHASE_*_EXECUTION_REPORT.md` files at the root document each implementation phase locally — note: root `*.md` is gitignored per project convention; reports are local audit artifacts only.

## Backend structure (`backend/app/`)
- `api/routes/` — 18 FastAPI routers: audit, cashflow, cashflow_ledger, contracts, counterparties, deals, exposures, finance_pipeline, linkages, mtm, orders, pl, rfqs, scenario, webhooks, westmetall, ws
- `services/` — 31 domain services including: deal_engine, exposure_engine, rfq_engine, rfq_orchestrator, rfq_service, rfq_message_builder, contract_service, order_service, counterparty_service, audit_trail_service, finance_pipeline_service, linkage_service, mtm_contract_service, mtm_order_service, mtm_snapshot_service, cashflow_analytic_service, cashflow_baseline_service, cashflow_ledger_service, cashflow_projection_service, pl_calculation_service, pl_snapshot_service, price_lookup_service, scenario_whatif_service, llm_agent, lme_calendar, cash_settlement_prices, westmetall_cash_settlement, webhook_processor, whatsapp_service, whatsapp_providers
- `models/` — SQLAlchemy ORM (audit, base, cashflow, contracts, counterparty, deal, exposure, finance_pipeline, linkages, market_data, mtm, orders, pl, quotes, rfqs)
- `schemas/` — Pydantic request/response (mirrors models + extras like `exposure_engine.py`, `llm.py`, `whatsapp.py`)
- `core/` — auth (JWT/JWKS), config (pydantic-settings), database, logging (structlog), metrics (prometheus), pagination, rate_limit (slowapi), utils
- `tasks/` — APScheduler jobs (rfq_timeout_task, westmetall_task, scheduler)
- `alembic/` — migrations
- `tests/` — pytest suite (50+ test files, named `test_*.py`)

## Frontend (svelte) structure (`frontend-svelte/src/`)
- `app.html`, `app.css`, `app.d.ts` — SvelteKit root
- `lib/api/` (openapi-fetch + generated `schema.d.ts`), `lib/components/`, `lib/stores/`, `lib/utils/`, `lib/assets/`
- `routes/(protected)/`, `routes/(public)/` — route groups
- `tests/` — vitest specs; `e2e/` — Playwright

## Key dependencies
**Backend:** fastapi 0.135, pydantic 2.12, pydantic-settings, uvicorn, gunicorn, SQLAlchemy 2.0, alembic, psycopg 3, httpx, python-jose, structlog, prometheus-fastapi-instrumentator, slowapi, tenacity, apscheduler.
**Backend dev:** pytest 9, pytest-cov, ruff (config in `backend/ruff.toml`).
**Svelte frontend:** SvelteKit 2, Svelte 5, Vite 7, Tailwind 4, openapi-fetch, openapi-typescript, ECharts 6, @tanstack/table-core, bits-ui, Playwright, Vitest.

## Database
PostgreSQL 16 (via docker-compose); SQLite (`test.db`) used for tests. Connection via `DATABASE_URL` env var.

## Known integrations
- **WhatsApp** providers: Meta Graph API and Twilio (configurable via `whatsapp_provider`)
- **OpenAI** for `llm_agent` (env: `OPENAI_API_KEY`, `OPENAI_MODEL` — migrated from Azure OpenAI 2026-05-06)
- **Westmetall** cash settlement prices (scheduled)
- **LME calendar**

## Production deployment
- **Railway** project `hedge-control` (4 services: `Postgres` template, `backend`, `scheduler`, `frontend-svelte`). Operational details: `docs/runbook-railway.md`. Auto-deploy disabled; deploys triggered manually via dashboard.
