import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.sanctions import (
    AdjudicationDecision,
    SanctionsAdjudication,
    SanctionsPartnerType,
    SanctionsScreening,
    ScreeningResult,
    ScreeningStatus,
)
from app.schemas.sanctions import (
    SanctionsAdjudicationRead,
    SanctionsAdjudicationRequest,
    SanctionsScreeningRead,
)


def test_reason_min_length_enforced():
    with pytest.raises(ValidationError):
        SanctionsAdjudicationRequest(decision="clear", reason="short")  # < 8 chars


def test_decision_must_be_clear_or_blocked():
    ok = SanctionsAdjudicationRequest(decision="clear", reason="valid reason text")
    assert ok.decision == "clear"
    with pytest.raises(ValidationError):
        SanctionsAdjudicationRequest(decision="flagged", reason="valid reason text")


def test_whitespace_only_reason_rejected():
    # eight spaces passes min_length=8 but is not meaningful rationale for an
    # immutable risk_manager sanctions override.
    with pytest.raises(ValidationError):
        SanctionsAdjudicationRequest(decision="clear", reason="        ")


def _make_screening() -> SanctionsScreening:
    obj = SanctionsScreening()
    obj.id = uuid.uuid4()
    obj.partner_id = uuid.uuid4()
    obj.partner_type = SanctionsPartnerType.commercial
    obj.screened_at = datetime.now(tz=UTC)
    obj.provider = "opensanctions"
    obj.algorithm = "exact"
    obj.query_hash = "abc123"
    obj.top_score = Decimal("0.9500")
    obj.match_count = 1
    obj.result = ScreeningResult.clear
    obj.status = ScreeningStatus.success
    obj.actor_sub = "test|sub"
    return obj


def test_screening_read_enum_coercion():
    """SanctionsScreeningRead.model_validate coerces ORM enum columns to str."""
    read = SanctionsScreeningRead.model_validate(_make_screening())
    assert isinstance(read.result, str)
    assert isinstance(read.status, str)
    assert read.result == "clear"
    assert read.status == "success"


def test_adjudication_read_enum_coercion():
    """SanctionsAdjudicationRead.model_validate coerces ORM enum columns to str."""
    screening = _make_screening()
    obj = SanctionsAdjudication()
    obj.id = uuid.uuid4()
    obj.partner_id = uuid.uuid4()
    obj.partner_type = SanctionsPartnerType.commercial
    obj.superseded_screening_id = screening.id
    obj.decision = AdjudicationDecision.clear
    obj.reason = "Manual review; confirmed false positive on name match"
    obj.adjudicated_at = datetime.now(tz=UTC)
    obj.adjudicating_actor_sub = "risk|sub"

    read = SanctionsAdjudicationRead.model_validate(obj)
    assert isinstance(read.decision, str)
    assert read.decision == "clear"
