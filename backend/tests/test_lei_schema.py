from datetime import UTC, datetime

from app.schemas.lei import LeiValidationRead


def test_lei_validation_read_shape():
    r = LeiValidationRead(
        lei="5493001KJTIIGC8Y1R12",
        lei_status="issued",
        lei_legal_name="Bloomberg Finance L.P.",
        lei_checked_at=datetime.now(UTC),
        warnings=["GLEIF registration status: RETIRED"],
    )
    assert r.lei_status == "issued"
    assert r.warnings == ["GLEIF registration status: RETIRED"]


def test_lei_validation_read_allows_nulls_and_empty_warnings():
    r = LeiValidationRead(
        lei=None, lei_status="not_provided", lei_legal_name=None, lei_checked_at=None, warnings=[]
    )
    assert r.lei is None
    assert r.warnings == []
