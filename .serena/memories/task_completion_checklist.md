# Task Completion Checklist

When finishing a coding task in this repo, run the appropriate steps for the layer(s) you touched.

## Backend changes
1. **Lint & format**
   ```powershell
   cd backend
   ruff check .
   ruff format --check .
   ```
   Fix issues (`ruff check --fix .`, `ruff format .`) before claiming done.
2. **Tests**
   ```powershell
   python -m pytest -x -q
   ```
   - All tests must pass. No `xfail` workarounds without justification.
   - If you added/changed behavior, you MUST add or update tests in `backend/tests/` (`test_*.py`).
3. **Migrations** — if models changed:
   ```powershell
   alembic revision --autogenerate -m "<short message>"
   alembic upgrade head
   ```
   Review the generated migration manually (autogenerate is not always correct).
4. **OpenAPI/contract sync** — if public routes/Pydantic schemas changed:
   - Re-run `npm run api:types` in `frontend-svelte/` and commit the updated `src/lib/api/schema.d.ts`.
   - The CI guard `npm run api:types:check` will diff them.
5. **Audit, governance, observability** — if the change touches state mutation, RFQ flow, exposure/cashflow/MTM math, or scheduled tasks: re-read `docs/governance.md` and confirm no hard-fail rule is violated. Add structlog events and metrics where appropriate.

## Frontend (Svelte) changes
1. **Type check**
   ```powershell
   cd frontend-svelte
   npm run check
   ```
2. **Unit tests**
   ```powershell
   npm run test
   ```
3. **Build**
   ```powershell
   npm run build
   ```
   Static adapter must succeed.
4. **E2E (when relevant)** — Playwright suite if you touched user-facing flows:
   ```powershell
   npm run test:e2e
   ```
5. **API types** — if you regenerated/updated `schema.d.ts`, commit it.

## Cross-cutting
- **Phase / execution report**: produce a `PHASE_X_STEP_Y_EXECUTION_REPORT.md` (or appropriate name) at the repo root, stating:
  - what was implemented
  - what was intentionally NOT implemented
  - tests added/updated
  - any deviations from the plan and why
- **Schemas**: if you changed a canonical entity (cashflow / contract / exposure / orders / pl / rfq / scenario), update the matching JSON Schema in `/schemas/` and the corresponding backend Pydantic schema and frontend type generation.
- **Don't commit** unless the user asks for it. When you do, follow the existing commit-message style (`fix:`, `feat:`, scoped, lowercase).
