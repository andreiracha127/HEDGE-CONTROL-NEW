# Tech Stack

## Backend
- **Python 3.11** (`target-version = "py311"` in ruff config)
- **FastAPI 0.135.1** + **Uvicorn 0.41** (dev) / **Gunicorn 23** (prod)
- **Pydantic 2.12** + **pydantic-settings 2.13** (env-driven `Settings` in `app/core/config.py`)
- **SQLAlchemy 2.0** ORM + **Alembic 1.18** migrations
- **psycopg 3** (Postgres driver)
- **python-jose[cryptography] 3.5** — JWT/JWKS verification
- **structlog 25.5** — structured logging
- **prometheus-fastapi-instrumentator 7.1** — metrics at `/metrics`
- **slowapi 0.1.9** — rate limiting
- **APScheduler 3.11** — scheduled jobs (gated by `SCHEDULER_DISABLED`)
- **tenacity 9.1** — retry with circuit-breaker pattern (see `test_retry_circuit_breaker.py`)
- **httpx 0.28** — outbound HTTP (WhatsApp, Westmetall)
- **openai 2.34** — OpenAI SDK for `llm_agent` (replaces former Azure OpenAI httpx integration, 2026-05-06)
- **python-multipart 0.0.20**

## Backend dev / quality
- **pytest 9.0.2** + **pytest-cov 6.1.1**
- **ruff** (config: `backend/ruff.toml`)
  - line-length 100, double quotes, space indent
  - selects: E, W, F, I, N, UP, B, SIM, PLW, RUF
  - ignores E501 (formatter handles), B008 (FastAPI Depends pattern)
  - `tests/**` skip B, SIM; `alembic/**` skip E, F, UP

## Frontend (Svelte — primary)
- **SvelteKit 2.50** with **Svelte 5.51**
- **Vite 7.3** + **@sveltejs/vite-plugin-svelte 6**
- **Tailwind CSS 4.2** via `@tailwindcss/vite`
- **TypeScript 5.9** + **svelte-check 4.4**
- **openapi-fetch 0.17** + **openapi-typescript 7.13** (generates `src/lib/api/schema.d.ts` from `/openapi.json`)
- **@tanstack/table-core 8.21**, **bits-ui 2.16**, **echarts 6**
- **Vitest 4.1** + **@testing-library/svelte** + **jsdom**
- **Playwright 1.58** for E2E
- Adapter: **@sveltejs/adapter-static** (and `adapter-auto` dev dep)
- Containerized via `frontend-svelte/Dockerfile` (nginx).

## Infrastructure
- **PostgreSQL 16-alpine** locally (via docker-compose volume `pgdata`); **Postgres template `ghcr.io/railwayapp-templates/postgres-ssl:18`** in production (Railway).
- **Docker Compose** (local) orchestrates: db, backend, frontend-svelte.
- **Railway** (production) — 4 services: `Postgres`, `backend`, `scheduler`, `frontend-svelte`. Config-as-code in `railway.json` (root) + `frontend-svelte/railway.json`. Per-service `Custom Start Command` + `Healthcheck Path` set in Railway dashboard (drift point — see `docs/runbook-railway.md`).
- **Locust** load tests in `locust/`.
