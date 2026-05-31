from app.core.config import Settings


def test_gleif_base_url_default():
    s = Settings(database_url="sqlite+pysqlite:///:memory:")
    assert s.gleif_api_base_url == "https://api.gleif.org/api/v1"


def test_gleif_base_url_overridable():
    s = Settings(
        database_url="sqlite+pysqlite:///:memory:", gleif_api_base_url="http://mock/api/v1"
    )
    assert s.gleif_api_base_url == "http://mock/api/v1"
