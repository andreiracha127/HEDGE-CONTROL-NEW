# Suggested Commands (Windows / PowerShell)

> Working directory: `D:\Projetos\Hedge-Control-New`. Adjust paths if running elsewhere.
> Default shell here is PowerShell 7+; Bash is also available via the harness.

## Backend (FastAPI)

```powershell
cd D:\Projetos\Hedge-Control-New\backend

# install deps (use a virtualenv — pick your tool)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt

# run dev server (also exposed via root npm script)
uvicorn app.main:app --reload --port 8000

# tests
python -m pytest -x -q                       # backend test suite
python -m pytest path/to/test_file.py -x     # single file
python -m pytest -k "rfq and orchestrator"   # filter
python -m pytest --cov=app --cov-report=term # with coverage

# lint / format (ruff)
ruff check .
ruff check --fix .
ruff format .

# DB migrations (alembic)
alembic upgrade head
alembic revision --autogenerate -m "<message>"
alembic downgrade -1
```

Root-level shortcut from monorepo root:
```powershell
npm run backend:dev
npm run backend:test
```

## Frontend (Svelte — primary)

```powershell
cd D:\Projetos\Hedge-Control-New\frontend-svelte

npm install
npm run dev                # vite dev server (default :5173)
npm run build              # production build
npm run preview            # preview built output
npm run check              # svelte-check + svelte-kit sync
npm run test               # vitest run
npm run test:watch
npm run test:coverage
npm run test:e2e           # Playwright (needs backend running for relevant flows)
npm run test:e2e:ui

# regenerate API types (backend must be on :8000)
npm run api:types
npm run api:types:check    # diff against committed schema.d.ts (CI guard)
```

## Docker / Compose (full stack)

```powershell
docker compose up -d --build
docker compose logs -f backend
docker compose down -v       # destroys pgdata volume
```

Service ports (local):
- backend → http://localhost:8000 (`/docs`, `/openapi.json`, `/health`, `/metrics`)
- frontend-svelte → http://localhost:5173
- postgres → localhost:5432 (user `hc`, db `hedgecontrol`)

## Railway (production)

For production operations (logs, redeploy, secrets, troubleshooting), see `docs/runbook-railway.md`. Quick reference:

```powershell
railway logs --service backend
railway logs --service backend --build
railway variables --service backend
railway variables --service backend --set KEY=VALUE
railway redeploy --service backend
```

Railway CLI auth: `admin@investintell.com`. Some operations (template install, GitHub repo link, volume add) hit `Unauthorized` or CLI panics — fall back to dashboard. Auto-deploy is OFF on all services; deploys are manual via dashboard.

## Git / GitHub

```powershell
git status
git log --oneline -20
git diff
gh pr list
gh pr view <num>
gh pr checks <num>
```

## Windows shell cheatsheet (PowerShell ≠ Bash)
- list dir → `Get-ChildItem` / `ls`
- env var → `$env:DATABASE_URL = "..."` (NOT `export`)
- null device → `$null` (NOT `/dev/null`)
- chain commands → `&&` works (PowerShell 7+); else `;`
- find files → use Glob tool, not `Get-ChildItem -Recurse`
- search content → use Grep tool, not `Select-String`
- read file → use Read tool, not `Get-Content`
