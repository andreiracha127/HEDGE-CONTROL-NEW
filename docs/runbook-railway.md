# Hedge Control - Railway Runbook

Date: 2026-05-06

This runbook is the operational reference for the Hedge Control Platform production deployment on Railway. It records the live service topology, dashboard-owned configuration, operational commands, deployment workflow, secret handling, and troubleshooting decisions that must remain reconstructable for audit and incident response.

## Project Topology

Railway project: `hedge-control`

Project ID: `d2840a3a-47fd-4bf9-9bf6-10048986349f`

Environment: `production`

| Service | Source | Public endpoint | Role | Depends on |
| --- | --- | --- | --- | --- |
| `Postgres` | Railway template `ghcr.io/railwayapp-templates/postgres-ssl:18` | None | Primary production database | Railway volume |
| `backend` | GitHub repo `andreiracha127/HEDGE-CONTROL-NEW`, branch `main`, root `/`, `Dockerfile` | `https://backend-production-d61b2.up.railway.app` | FastAPI API service | `Postgres` |
| `scheduler` | Same repo and root as `backend`, `Dockerfile` | None | Background scheduler process | `Postgres` |
| `frontend-svelte` | Same repo, root `frontend-svelte`, `Dockerfile` | `https://frontend-svelte-production-815d.up.railway.app` | Svelte/nginx web frontend | `backend` |

Text topology:

```text
users
  -> frontend-svelte (public Railway domain)
      -> backend (public Railway domain)
          -> Postgres (private Railway network)

scheduler (private Railway service)
  -> Postgres (private Railway network)
  -> OpenAI API, when scheduled LLM work is enabled by application flow
```

Postgres runtime details:

| Item | Value |
| --- | --- |
| Template image | `ghcr.io/railwayapp-templates/postgres-ssl:18` |
| Volume mount | `/var/lib/postgresql/data` |
| Database | `railway` |
| User | `postgres` |
| Private host | `postgres-4cab.railway.internal:5432` |

## Service Configuration

The settings in this section are load-bearing and are owned by the Railway dashboard, not by `railway.json`.

| Service | Custom Start Command | Healthcheck Path | Healthcheck Timeout | Target Port |
| --- | --- | --- | --- | --- |
| `backend` | `/bin/sh -c 'SCHEDULER_DISABLED=true exec gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT:-8000}'` | `/health` | `30s` | `8000` |
| `scheduler` | `/bin/sh -c 'exec python -m app.scheduler_main'` | Empty | n/a | n/a, no public domain |
| `frontend-svelte` | Image default nginx command | `/` | Railway default | Autodetect |

Critical variables by service:

| Service | Variable | Required value or source | Notes |
| --- | --- | --- | --- |
| `backend` | `DATABASE_URL` | Reference to `Postgres` | Must use the Railway internal database reference for runtime traffic. |
| `backend` | `SCHEDULER_DISABLED` | `true` | Also enforced in the custom start command to prevent duplicate scheduler execution in web workers. |
| `backend` | `CORS_ALLOW_ORIGINS` | Reference to frontend public domain | Must include `https://frontend-svelte-production-815d.up.railway.app`. |
| `backend` | `OPENAI_API_KEY` | Secret value | Never commit. Rotate from Railway variables. |
| `backend` | `OPENAI_MODEL` | Model name | Keep aligned with scheduler when operational behavior must match. |
| `scheduler` | `DATABASE_URL` | Same `Postgres` reference as backend | Required for scheduled jobs that read or mutate database-backed state. |
| `scheduler` | `SCHEDULER_DISABLED` | `false` | The scheduler service is the only production process expected to run scheduled work. |
| `scheduler` | `OPENAI_API_KEY` | Secret value | Never commit. Rotate from Railway variables. |
| `scheduler` | `OPENAI_MODEL` | Model name | Keep aligned with backend when operational behavior must match. |
| `frontend-svelte` | `VITE_API_BASE_URL` | Reference to backend public domain | Build-time variable. Redeploy frontend after changing it. |

## Operational Commands

Run Railway CLI commands from the repository root after selecting project `hedge-control` and environment `production`.

CLI account currently used for operations: `admin@investintell.com`.

Some operations that touch GitHub OAuth or templates can return `Unauthorized` in this workspace. Use the Railway dashboard for those cases.

```bash
# Stream service runtime logs
railway logs --service backend
railway logs --service scheduler
railway logs --service frontend-svelte

# Inspect build logs
railway logs --service backend --build
railway logs --service frontend-svelte --build

# Inspect recent logs only
railway logs --service backend --since 5m
railway logs --service scheduler --since 5m

# Read variables for a service
railway variables --service backend
railway variables --service scheduler
railway variables --service frontend-svelte

# Set or rotate a variable
railway variables --service backend --set OPENAI_MODEL=gpt-4o-mini
railway variables --service scheduler --set OPENAI_MODEL=gpt-4o-mini

# Redeploy a service without pushing code
railway redeploy --service backend
railway redeploy --service scheduler
railway redeploy --service frontend-svelte

# Inspect or create service domains
railway domain --service backend
railway domain --service frontend-svelte
```

For variables containing secrets, prefer the Railway dashboard or a secure terminal session. Do not paste secret values into issue trackers, commits, PR descriptions, or chat logs.

## Deployment Workflow

Auto-deploy is disabled for all production services. A merge to `main` does not automatically promote to production.

Production deployment is manual:

1. Merge the reviewed change to `main`.
2. Confirm the target service and whether the change affects backend, scheduler, frontend, or shared configuration.
3. Deploy from the Railway dashboard using the service `Deploy` button, or run `railway redeploy --service <service>`.
4. For `backend`, confirm `/health` on the public domain after deploy.
5. For `scheduler`, inspect logs because the service has no HTTP healthcheck.
6. For `frontend-svelte`, confirm the public domain loads and calls the backend domain configured in `VITE_API_BASE_URL`.

Use service-specific redeploys when the blast radius is narrow. Redeploy all dependent services only when a shared contract, environment variable, or image change requires it.

## Connection and Database Access

Runtime application traffic should use the private Railway database reference exposed through `DATABASE_URL`.

External operator access requires a public database path. The current production Postgres service is recorded with no public endpoint, so incident responders must first confirm that a TCP Proxy is enabled before relying on Railway CLI database access.

Approved external access paths:

1. If the Railway TCP Proxy is enabled for Postgres, use `railway connect Postgres` from an authenticated CLI session. This command depends on Railway's public database URL/proxy path and will fail when no TCP Proxy is available.
2. If Railway exposes `DATABASE_PUBLIC_URL`, use it from an approved external SQL client.
3. If no TCP Proxy or `DATABASE_PUBLIC_URL` is enabled, use the Railway dashboard to enable an approved temporary TCP Proxy or perform access from an environment that can reach the private Railway network. Record the access method in the incident or execution report.

Example external connection pattern:

```bash
# Option 1: Railway-managed interactive connection.
# Requires TCP Proxy/public database URL.
railway connect Postgres

# Option 2: psql through the public database URL, when enabled.
psql "$DATABASE_PUBLIC_URL"
```

Access rules:

- Do not commit connection strings.
- Do not store production database URLs in local `.env` files that can be shared.
- Do not assume `railway connect Postgres` will work for a private-only database. Confirm TCP Proxy status first.
- Prefer read-only inspection during incidents unless a documented corrective action requires mutation.
- Record manual data changes in the incident or execution report with timestamp, operator, command intent, and affected records.

## Secrets Management

Secrets live in Railway variables by service. They are not represented in repository files.

Required production secret-bearing variables:

| Service | Secret variables |
| --- | --- |
| `backend` | `DATABASE_URL`, `OPENAI_API_KEY` |
| `scheduler` | `DATABASE_URL`, `OPENAI_API_KEY` |
| `frontend-svelte` | None expected, but `VITE_API_BASE_URL` is operational configuration and is evaluated at build time |

OpenAI key rotation:

1. Create the replacement key in the OpenAI account.
2. Update `OPENAI_API_KEY` on `backend` and `scheduler` in Railway.
3. Redeploy `backend` and `scheduler`.
4. Verify backend health and scheduler logs.
5. Revoke the old key only after both services are confirmed on the new key.
6. Record the rotation date and operator in the operational log or execution report.

Model changes:

- Keep `OPENAI_MODEL` explicit on both backend and scheduler.
- Treat model changes as behavioral changes. Record the reason and redeploy both services that use the model.

## Troubleshooting

### `railway.json` overrides dashboard start and healthcheck settings

Symptom: a service deploys with a start command or healthcheck that differs from the dashboard configuration, or a scheduler receives an HTTP healthcheck intended for the backend.

Root cause: `railway.json` deploy fields can override dashboard `startCommand` and healthcheck settings.

Resolution: keep production start commands and healthchecks in the Railway dashboard. Do not add `startCommand` back to `railway.json` without testing precedence on all services that share the repo root.

### Backend public domain returns 502 while gunicorn is running

Symptom: `curl` against `https://backend-production-d61b2.up.railway.app` returns 502, but logs show gunicorn listening successfully.

Root cause: Railway public domain target port is not always auto-detected for Dockerfile deployments.

Resolution: in Railway dashboard, open backend service settings, then Networking, and confirm Target Port is `8000`.

### Frontend nginx cannot create runtime `config.json`

Symptom: frontend deploy starts nginx entrypoint but fails when generating or writing runtime `config.json`.

Root cause: `nginxinc/nginx-unprivileged` runs without root filesystem ownership for `/usr/share/nginx/html`.

Resolution: keep the explicit `chown` of `/usr/share/nginx/html` in the frontend Dockerfile. This was fixed in PR #7. Do not remove it during image cleanup.

### Railway Dockerfile start commands need shell wrapping for env expansion

Symptom: `${PORT:-8000}` or inline variable prefixes are not expanded, or command parsing differs from local shell behavior.

Root cause: Railway Dockerfile deployments run custom start commands in exec form.

Resolution: wrap commands that need shell features in `/bin/sh -c '...'`. Use `exec` before the real process so PID 1 receives signals correctly. Current backend and scheduler dashboard commands follow this rule.

### CI green is not sufficient for deployment correctness

Symptom: GitHub CI passes, but Railway deployment fails due to platform-specific behavior.

Root cause: CI does not exercise Railway dashboard configuration, domain target port resolution, Railway command execution form, or template/volume behavior.

Resolution: require Codex Connector or equivalent deployment-environment validation before merging deployment-sensitive changes. Treat green CI as necessary but not sufficient for Railway platform changes.

### `railway add --database postgres` returns `Unauthorized`

Symptom: Railway CLI returns `Unauthorized` when adding Postgres in this workspace.

Root cause: this CLI authentication context can fail on actions that touch Railway templates or GitHub OAuth state.

Resolution: add the Postgres template from the Railway dashboard instead of the CLI when this error appears.

### `railway volume add --mount-path` panics

Symptom: Railway CLI exits with a Rust panic while adding a volume with `--mount-path`.

Root cause: Railway CLI bug observed in this workspace.

Resolution: create and attach volumes from the Railway dashboard. The current Postgres volume must remain mounted at `/var/lib/postgresql/data`.

## Architecture Decisions

### Dashboard-owned start commands

Start commands and healthchecks were moved to the Railway dashboard because backend and scheduler share the repository root and root Dockerfile. Keeping service-specific process commands in the dashboard avoids accidental cross-service overrides from a shared `railway.json`.

### Separate scheduler service

The scheduler is a separate Railway service so scheduled work has a single production owner. The backend web service sets `SCHEDULER_DISABLED=true`, preventing duplicate background execution across gunicorn workers and keeping API request serving separate from scheduled processing.

### Manual Postgres template and volume setup

The production database uses the Railway Postgres SSL template with an explicit volume at `/var/lib/postgresql/data`. CLI template and volume creation were unreliable in this workspace, so dashboard setup is the recorded operational path. Backup policy and restore drills remain operational responsibilities outside repository configuration.

### Manual production deploys

Auto-deploy is disabled to preserve explicit production promotion. This is consistent with institutional controls: deployment should be an auditable action, not an implicit side effect of merging to `main`.

## Manual TODOs That Drift Over Time

Check these periodically and after any Railway platform change:

- Backend Target Port remains `8000`.
- Backend Custom Start Command exactly matches the dashboard command recorded in this runbook.
- Backend Healthcheck Path remains `/health` with timeout `30s`.
- Scheduler Custom Start Command remains `/bin/sh -c 'exec python -m app.scheduler_main'`.
- Scheduler has no public domain and no HTTP healthcheck.
- `backend` has complete variables: `DATABASE_URL`, `SCHEDULER_DISABLED=true`, `CORS_ALLOW_ORIGINS`, `OPENAI_API_KEY`, `OPENAI_MODEL`.
- `scheduler` has complete variables: `DATABASE_URL`, `SCHEDULER_DISABLED=false`, `OPENAI_API_KEY`, `OPENAI_MODEL`.
- `frontend-svelte` has `VITE_API_BASE_URL` pointing to the backend production domain.
- Auto-deploy remains disabled on all production services.
- Postgres volume remains attached at `/var/lib/postgresql/data`.
- CLI account and dashboard access are available to at least two authorized operators.
