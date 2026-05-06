# Hedge Control Platform — Backend

## Overview

FastAPI backend for the Alcast Hedge Control Platform — institutional commodity
trading and hedging. Provides REST APIs for exposures, orders, RFQs, contracts,
deals, counterparties, cashflow, P&L, MTM, scenarios, audit trail, and market data.

## Key directories

| Path              | Purpose                                    |
| ----------------- | ------------------------------------------ |
| `app/api/routes/` | FastAPI route modules (16 routers)         |
| `app/services/`   | Business-logic service layer (32 services) |
| `app/models/`     | SQLAlchemy ORM models                      |
| `app/schemas/`    | Pydantic request / response schemas        |
| `app/core/`       | Auth, database, config, rate-limiting      |
| `alembic/`        | Database migrations                        |
| `tests/`          | Pytest test suite                          |

## Run (development)

```bash
uvicorn app.main:app --reload
```

## Production deployment

Production runs on Railway. Operational configuration, service start commands,
healthchecks, environment variables, deployment workflow, and troubleshooting are
documented in [`../docs/runbook-railway.md`](../docs/runbook-railway.md).
