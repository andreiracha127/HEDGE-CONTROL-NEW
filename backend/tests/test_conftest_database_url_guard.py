import conftest


def test_regular_pytest_uses_sqlite_even_when_shell_exports_postgres() -> None:
    env = {
        "DATABASE_URL": "postgresql+psycopg://hc:hc@localhost:5433/hedgecontrol",
    }

    assert conftest._database_url_for_tests(env) == "sqlite+pysqlite:///:memory:"


def test_full_stack_e2e_preserves_external_database_url() -> None:
    url = "postgresql+psycopg://hc:hc@localhost:5433/hedgecontrol"
    env = {
        "DATABASE_URL": url,
        "E2E_FULL_STACK": "1",
    }

    assert conftest._database_url_for_tests(env) == url
