"""Domain-agnostic sanctions screening + adjudication orchestration.

Writes immutable ``sanctions_screenings`` / ``sanctions_adjudications`` rows,
sets the entity ``sanctions_status``, and emits HMAC audit events. Reuses the
``kyc_gate`` dual-session pattern to record provider-error evidence that
survives the request ``unit_of_work`` rollback.
"""

from __future__ import annotations

import hashlib  # noqa: F401
import json  # noqa: F401
import uuid  # noqa: F401
from datetime import UTC, datetime  # noqa: F401
from decimal import Decimal

from fastapi import HTTPException, status  # noqa: F401
from sqlalchemy import select  # noqa: F401
from sqlalchemy.orm import Session  # noqa: F401

from app.core.config import get_settings  # noqa: F401
from app.core.database import SessionLocal  # noqa: F401
from app.models.commercial_partner import CommercialPartner  # noqa: F401
from app.models.counterparty import Counterparty, SanctionsStatus  # noqa: F401
from app.models.sanctions import (
    AdjudicationDecision,  # noqa: F401
    SanctionsAdjudication,  # noqa: F401
    SanctionsPartnerType,  # noqa: F401
    SanctionsScreening,  # noqa: F401
    ScreeningResult,
    ScreeningStatus,  # noqa: F401
)
from app.services.audit_trail_service import AuditTrailService  # noqa: F401
from app.services.opensanctions_client import ScreeningProviderError, screen_entity  # noqa: F401

_PROVIDER = "opensanctions"


def map_score_to_result(
    top_score: Decimal, review_threshold: Decimal, hard_threshold: Decimal
) -> ScreeningResult:
    if top_score >= hard_threshold:
        return ScreeningResult.blocked
    if top_score >= review_threshold:
        return ScreeningResult.flagged
    return ScreeningResult.clear
