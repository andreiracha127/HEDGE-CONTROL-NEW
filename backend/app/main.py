import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.auth import get_auth_settings, validate_auth_config
from app.core.config import get_settings
from app.core.csrf import csrf_middleware
from app.core.database import engine
from app.core.logging import configure_logging, get_logger
from app.core.metrics import request_latency_seconds
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.tasks.scheduler import start_scheduler, stop_scheduler

from app.api.routes import (
    audit,
    auth,
    cashflow,
    cashflow_ledger,
    contracts,
    counterparties,
    deals,
    exposures,
    finance_pipeline,
    linkages,
    mtm,
    orders,
    pl,
    rfqs,
    scenario,
    webhooks,
    westmetall,
)

configure_logging()
logger = get_logger()

validate_auth_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


_cfg = get_settings()

app = FastAPI(
    title="Hedge Control Platform",
    version=_cfg.app_version,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


class _StripApiPrefixMiddleware:
    """Raw ASGI middleware that strips the ``/api`` prefix from the request
    path.  Some reverse proxies forward ``/api/*`` to the app with the prefix
    intact.  This middleware normalises the path so that existing routes
    (``/orders``, ``/contracts``, …) continue to work whether the request
    arrives via a proxy or directly."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            path: str = scope.get("path", "/")
            if path == "/api" or path == "/api/":
                scope = dict(scope, path="/")
            elif path.startswith("/api/"):
                scope = dict(scope, path=path[4:])  # strip leading "/api"
        await self.app(scope, receive, send)


class _StripTrailingSlashMiddleware:
    """Raw ASGI middleware that strips trailing slashes from request paths
    before they reach the router.  This prevents 307 redirect loops when a
    reverse-proxy (e.g. fiori-tools-proxy) appends a trailing slash to
    forwarded requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path: str = scope.get("path", "/")
            if path != "/" and path.endswith("/"):
                scope = dict(scope, path=path.rstrip("/"))
        await self.app(scope, receive, send)


class _CatchAllMiddleware:
    """Raw ASGI middleware that catches unhandled exceptions and returns a JSON
    500 response.  Registered *before* CORSMiddleware so that in the built
    middleware stack it runs *inside* CORS, ensuring error responses still
    receive the correct Access-Control-Allow-Origin header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            logger.error(
                "unhandled_exception",
                path=scope.get("path", ""),
                error=str(exc),
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error"},
            )
            await response(scope, receive, send)


# Order matters: add_middleware uses insert(0, ...) so the LAST added
# middleware becomes the outermost.  We want CORSMiddleware outermost
# and _CatchAllMiddleware inside it to guarantee CORS headers on errors.
# Execution order (from outermost to innermost):
#   CORS → CatchAll → StripApiPrefix → StripTrailingSlash → Router
app.add_middleware(_StripTrailingSlashMiddleware)
app.add_middleware(_StripApiPrefixMiddleware)
app.add_middleware(_CatchAllMiddleware)

cors_allow_origins = _cfg.cors_origins_list

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Trace-Id", "X-CSRF-Token"],
)

instrumentator = Instrumentator()
instrumentator.instrument(app).expose(app, endpoint="/metrics")


@app.middleware("http")
async def csrf_http_middleware(request: Request, call_next):
    return await csrf_middleware(request, call_next)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    start_time = time.monotonic()
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    if not request.url.path.startswith("/metrics"):
        duration = max(time.monotonic() - start_time, 0.0)
        request_latency_seconds.labels(
            method=request.method,
            path=request.url.path,
            status=str(response.status_code),
        ).observe(duration)
        logger.info(
            "request",
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception as exc:  # pragma: no cover - explicit readiness failure path
        logger.error("readiness_db_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="db_unavailable") from exc

    if _cfg.auth_enabled:
        try:
            settings = get_auth_settings()
            response = httpx.get(settings.jwks_url, timeout=5.0)
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover
            logger.error("readiness_jwks_failed", error=str(exc))
            raise HTTPException(status_code=503, detail="jwks_unavailable") from exc

    return {"status": "ready"}


app.include_router(
    counterparties.router, prefix="/counterparties", tags=["Counterparties"]
)
app.include_router(orders.router, prefix="/orders", tags=["Orders"])
app.include_router(exposures.router, prefix="/exposures", tags=["Exposures"])
app.include_router(deals.router, prefix="/deals", tags=["Deals"])
app.include_router(contracts.router, prefix="/contracts", tags=["Contracts"])
app.include_router(linkages.router, prefix="/linkages", tags=["Linkages"])
app.include_router(rfqs.router, prefix="/rfqs", tags=["RFQs"])
app.include_router(cashflow.router, prefix="/cashflow", tags=["CashFlow"])
app.include_router(cashflow_ledger.router, prefix="/cashflow", tags=["CashFlowLedger"])
app.include_router(pl.router, prefix="/pl", tags=["P&L"])
app.include_router(scenario.router, prefix="/scenario", tags=["Scenario"])
app.include_router(audit.router, prefix="/audit", tags=["Audit"])
app.include_router(
    westmetall.router, prefix="/market-data/westmetall", tags=["MarketData"]
)
app.include_router(mtm.router, prefix="/mtm", tags=["MTM"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
app.include_router(auth.router)
app.include_router(
    finance_pipeline.router, prefix="/finance/pipeline", tags=["FinancePipeline"]
)

# WebSocket endpoint (no prefix — registered directly)
from app.api.routes.ws import websocket_endpoint

app.add_api_websocket_route("/ws", websocket_endpoint)
