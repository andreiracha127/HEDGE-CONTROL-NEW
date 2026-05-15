from fastapi import status

from app.core.auth import SESSION_COOKIE_NAME, get_current_user
from app.main import app


def test_auth_invalid_token_returns_401(client) -> None:
    app.dependency_overrides.pop(get_current_user, None)
    client.cookies.set(SESSION_COOKIE_NAME, "invalid")
    response = client.get(
        "/exposures/commercial",
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
