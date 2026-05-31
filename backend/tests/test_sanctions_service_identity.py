from app.core.auth import _INTERNAL_SERVICE_IDENTITIES


def test_sanctions_screening_identity_registered():
    assert "service:sanctions_screening" in _INTERNAL_SERVICE_IDENTITIES
