from decimal import Decimal

import pytest
from app.services.sanctions_screening_service import map_score_to_result

from app.models.sanctions import ScreeningResult

REVIEW = Decimal("0.70")
HARD = Decimal("0.90")


@pytest.mark.parametrize(
    "score,expected",
    [
        ("0.00", ScreeningResult.clear),
        ("0.69", ScreeningResult.clear),
        ("0.70", ScreeningResult.flagged),
        ("0.89", ScreeningResult.flagged),
        ("0.90", ScreeningResult.blocked),
        ("1.00", ScreeningResult.blocked),
    ],
)
def test_boundaries(score, expected):
    assert map_score_to_result(Decimal(score), REVIEW, HARD) == expected
