from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.auth import require_role
from app.core.database import get_session
from app.core.rate_limit import RATE_LIMIT_MUTATION, limiter
from app.schemas.scenario import ScenarioWhatIfRunRequest, ScenarioWhatIfRunResponse
from app.services.price_lookup_service import PriceReferenceUnprovable
from app.services.scenario_whatif_service import run_what_if


router = APIRouter()


@router.post(
    "/what-if/run",
    response_model=ScenarioWhatIfRunResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit(RATE_LIMIT_MUTATION)
def run_what_if_scenario(
    request: Request,
    payload: ScenarioWhatIfRunRequest,
    _: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> ScenarioWhatIfRunResponse:
    try:
        return run_what_if(session, payload)
    except PriceReferenceUnprovable as exc:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail=str(exc),
        ) from exc
