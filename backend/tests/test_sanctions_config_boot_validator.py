import pytest

from app.core.config import Settings

PG = "postgresql://u:p@h/db"


def test_prod_enabled_missing_key_refuses_boot():
    with pytest.raises(ValueError, match="OPENSANCTIONS_API_KEY"):
        Settings(
            database_url=PG,
            app_env="production",
            audit_signing_key="x" * 16,
            sanctions_screening_enabled=True,
            opensanctions_api_key="",
        )


def test_prod_enabled_with_key_boots():
    s = Settings(
        database_url=PG,
        app_env="production",
        audit_signing_key="x" * 16,
        sanctions_screening_enabled=True,
        opensanctions_api_key="key-123",
    )
    assert s.opensanctions_api_key == "key-123"


def test_prod_disabled_missing_key_boots():
    s = Settings(
        database_url=PG,
        app_env="production",
        audit_signing_key="x" * 16,
        sanctions_screening_enabled=False,
        opensanctions_api_key="",
    )
    assert s.sanctions_screening_enabled is False


def test_dev_missing_key_boots():
    s = Settings(
        database_url=PG,
        app_env="development",
        sanctions_screening_enabled=True,
        opensanctions_api_key="",
    )
    assert s.app_env == "development"


def test_default_thresholds():
    from decimal import Decimal

    s = Settings(database_url="sqlite+pysqlite:///:memory:")
    assert s.sanctions_review_threshold == Decimal("0.70")
    assert s.sanctions_hard_threshold == Decimal("0.90")
