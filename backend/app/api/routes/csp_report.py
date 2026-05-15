"""
CSP violation reporter (PR-CL3-4). CSRF-exempt, rate-limited POST /csp/report.
Accepts legacy csp-report + modern Reporting API body; logs "csp_violation".
"""

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, Response
import structlog

from app.core.rate_limit import RATE_LIMIT_CSP_REPORT, limiter

router = APIRouter(tags=["csp"])
logger = structlog.get_logger(__name__)


@router.post("/report")
@limiter.limit(RATE_LIMIT_CSP_REPORT)
async def csp_report(request: Request) -> Response:
    """Accept CSP violation report (legacy or modern shape), log structured event, return 204."""
    try:
        body = await request.json()
    except Exception:
        logger.warning(
            "csp_report_validation_failed",
            reason="invalid JSON",
            status=400,
            path=str(request.url.path),
        )
        return JSONResponse(status_code=400, content={"detail": "invalid JSON"})

    # The browser sends one report object or an array of report objects.
    reports = body if isinstance(body, list) else [body]
    for report in reports:
        # Reports have a "csp-report" subkey under the legacy spec or
        # a "body" subkey under the modern Reporting API spec.
        violation = report.get("csp-report") or report.get("body") or report
        if not isinstance(violation, dict):
            logger.warning(
                "csp_report_validation_failed",
                reason="invalid report shape",
                status=400,
                path=str(request.url.path),
            )
            return JSONResponse(status_code=400, content={"detail": "invalid CSP report"})
        document_uri = (
            violation.get("document-uri")
            or violation.get("documentURL")
            or report.get("url")
        )
        directive = (
            violation.get("violated-directive")
            or violation.get("effective-directive")
            or violation.get("effectiveDirective")
        )
        if not document_uri or not directive:
            logger.warning(
                "csp_report_validation_failed",
                reason="missing required fields",
                status=400,
                path=str(request.url.path),
            )
            return JSONResponse(status_code=400, content={"detail": "missing required CSP report fields"})
        logger.warning(
            "csp_violation",
            blocked_uri=violation.get("blocked-uri") or violation.get("blockedURL"),
            violated_directive=directive,
            document_uri=document_uri,
            source_file=violation.get("source-file") or violation.get("sourceFile"),
            line_number=violation.get("line-number") or violation.get("lineNumber"),
            referrer=violation.get("referrer"),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
