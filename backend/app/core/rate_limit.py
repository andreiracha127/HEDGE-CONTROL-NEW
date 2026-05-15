"""
Rate limiting configuration using slowapi.

Limits are configurable via environment variables:
  - RATE_LIMIT_SCRAPING:  default "5/minute"   (Westmetall ingest)
  - RATE_LIMIT_MUTATION:  default "60/minute"   (POST / PUT / PATCH / DELETE)
  - RATE_LIMIT_READ:      default "120/minute"  (GET)
  - RATE_LIMIT_CSP_REPORT: default "50/minute"  (CSP violation reports from browsers)

Each value follows the slowapi/limits format: "<count>/<period>"
Examples: "10/minute", "100/hour", "5/second"

NOTE: The default storage backend is **in-memory** (per-process).  When running
behind Gunicorn/Uvicorn with multiple workers each worker maintains its own
counter, so the effective limit is multiplied by the number of workers.
For production deployments with >1 worker, switch to a shared backend:

    from slowapi import Limiter
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri="redis://localhost:6379/0",
    )

See: https://limits.readthedocs.io/en/stable/storage.html
"""

import os

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

RATE_LIMIT_SCRAPING = os.getenv("RATE_LIMIT_SCRAPING", "5/minute")
RATE_LIMIT_MUTATION = os.getenv("RATE_LIMIT_MUTATION", "60/minute")
RATE_LIMIT_READ = os.getenv("RATE_LIMIT_READ", "120/minute")
RATE_LIMIT_CSP_REPORT = os.getenv("RATE_LIMIT_CSP_REPORT", "50/minute")

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[RATE_LIMIT_READ],
)


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return a JSON 429 response with rate-limit headers injected by slowapi."""
    response = JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )
    try:
        response = request.app.state.limiter._inject_headers(
            response, request.state.view_rate_limit
        )
    except Exception:  # pragma: no cover – headers are best-effort
        pass
    return response
