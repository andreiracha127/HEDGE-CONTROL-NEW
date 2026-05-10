# Code Style & Conventions

## Backend (Python)
- **Python 3.11** target.
- **Ruff** is the single source of truth for lint+format (`backend/ruff.toml`):
  - line length 100
  - double quotes, space indent
  - rule sets: `E, W, F, I, N, UP, B, SIM, PLW, RUF`
  - ignored: `E501` (handled by formatter), `B008` (FastAPI `Depends` pattern is acceptable in default args)
  - per-file: `tests/**` ignore `B, SIM`; `alembic/**` ignore `E, F, UP`
- **Type hints** are pervasive on services and API layer. Pydantic v2 models for I/O; SQLAlchemy 2 typed ORM for persistence.
- **Naming**: PEP8 (`snake_case` for functions/vars, `PascalCase` for classes); module names match domain noun (e.g. `rfq_orchestrator.py`).
- **Configuration** centralized in `app/core/config.py::Settings` (`pydantic-settings`, reads `.env`). Use `get_settings()` cached accessor — do not read env vars directly elsewhere.
- **Logging**: `structlog` — emit structured key/value pairs. A `trace_id_middleware` adds correlation IDs.
- **Auth**: JWT/JWKS-based; disabled when `jwt_issuer` is empty (dev mode). Don't add ad-hoc auth checks — use the existing dependency from `app/core/auth.py`.
- **Rate limiting**: `slowapi` with named tiers (`rate_limit_scraping`, `rate_limit_mutation`, `rate_limit_read`). Apply via the existing decorators.
- **Audit**: events are HMAC-signed with `audit_signing_key`. Persistence is idempotent (see `test_audit_event_insert_idempotent.py`). Never bypass the audit_trail_service for state changes that need an audit record.
- **Service layer pattern**: routes (`app/api/routes/*.py`) stay thin and delegate to services in `app/services/`. Engines (`*_engine.py`) own deterministic domain logic; `*_service.py` typically own persistence + orchestration.
- **No silent fallbacks**: per the constitution, hard-fail rather than guess (missing evidence, ambiguous dates, unranked quotes, etc.).

## Frontend (Svelte)
- **Svelte 5** (runes era) + **TypeScript** strict via `svelte-check`.
- **Tailwind 4** for styling (via `@tailwindcss/vite`).
- **API access** through generated types: `src/lib/api/schema.d.ts` (regenerated with `npm run api:types`). Use **openapi-fetch**; do NOT hand-write fetch URLs.
- **Route groups**: `(protected)` vs `(public)` — auth boundary lives at the layout level.
- **Components / stores / utils** under `src/lib/`. Reusable UI from `bits-ui`; charts via `echarts`; tables via `@tanstack/table-core`.
- **Testing**: component tests with `vitest` + `@testing-library/svelte` (jsdom); E2E with Playwright in `e2e/`.
- **Adapter**: static (so the build is served by nginx in the container). Avoid SSR-only APIs.

## Cross-cutting
- **Schemas at the boundary**: JSON Schemas in `/schemas/` describe canonical entities and should remain in sync with backend Pydantic + frontend types. Treat them as contracts.
- **Phase reports are evidence**: every meaningful change is accompanied by a `PHASE_*_EXECUTION_REPORT.md` (or `FRONTEND_AGENT_*_EXECUTION_REPORT.md`) at the repo root. State explicitly what was implemented and what was intentionally NOT implemented.
- **Comments**: minimal — code should be self-explanatory; only add comments to explain *why* (non-obvious constraint), not *what*.
