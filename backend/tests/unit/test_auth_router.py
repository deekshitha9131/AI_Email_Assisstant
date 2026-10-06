"""Tests for app/presentation/api/v1/routers/auth.py.

Overrides get_auth_service and get_current_user with fakes/stubs, the
same dependency_overrides pattern established for the health router
tests — this exercises real HTTP behavior (cookies, redirects, status
codes) without a live database, Redis, or Google.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.constants import OAUTH_STATE_COOKIE_NAME, SESSION_COOKIE_NAME
from app.core.di_container import get_auth_service, get_current_user, get_settings_dependency
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.auth import InvalidOAuthStateError, SessionNotFoundError


class FakeAuthService:
    def __init__(self) -> None:
        self.login_calls = 0
        self.logout_calls: list[str] = []
        self._state = "fixed-test-state"
        self._sessions: dict[str, User] = {}

    def build_login_redirect(self) -> tuple[str, str]:
        self.login_calls += 1
        return f"https://accounts.google.com/fake?state={self._state}", self._state

    async def handle_callback(self, *, code: str, state: str, state_cookie_value: str | None):
        if state_cookie_value is None or state != state_cookie_value:
            raise InvalidOAuthStateError("state mismatch")
        user = User(
            id=uuid4(),
            email="user@example.com",
            full_name="Test User",
            google_sub_id="sub-123",
            status=UserStatus.ACTIVE,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self._sessions["fake-session-id"] = user
        return user, "fake-session-id"

    async def logout(self, session_id: str) -> None:
        self.logout_calls.append(session_id)
        self._sessions.pop(session_id, None)

    async def get_current_user(self, session_id: str | None) -> User:
        # Mirrors the real AuthService.get_current_user: every failure
        # mode (missing cookie, unknown session) raises the same error.
        if session_id is None or session_id not in self._sessions:
            raise SessionNotFoundError("No active session.")
        return self._sessions[session_id]


def _fake_current_user() -> User:
    return User(
        id=uuid4(),
        email="loggedin@example.com",
        full_name="Logged In User",
        google_sub_id="sub-456",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def fake_auth_service(app_no_lifespan: FastAPI) -> FakeAuthService:
    service = FakeAuthService()
    app_no_lifespan.dependency_overrides[get_auth_service] = lambda: service
    return service


def test_login_redirects_to_google_and_sets_state_cookie(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_auth_service: FakeAuthService
) -> None:
    response = unit_client.get("/api/v1/auth/google/login", follow_redirects=False)

    assert response.status_code == 302
    assert "accounts.google.com" in response.headers["location"]
    assert response.cookies.get(OAUTH_STATE_COOKIE_NAME) == "fixed-test-state"
    assert fake_auth_service.login_calls == 1


def test_production_login_state_cookie_is_secure_and_cross_site_get_compatible(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_auth_service: FakeAuthService
) -> None:
    app_no_lifespan.dependency_overrides[get_settings_dependency] = lambda: Settings(
        _env_file=None,
        APP_ENV="production",
        APP_SECRET_KEY="unit-test-secret",
        DATABASE_URL="postgresql://localhost/test",
    )

    response = unit_client.get("/api/v1/auth/google/login", follow_redirects=False)

    assert response.status_code == 302
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie


def test_callback_with_valid_state_sets_session_cookie_and_redirects(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_auth_service: FakeAuthService
) -> None:
    unit_client.cookies.set(OAUTH_STATE_COOKIE_NAME, "fixed-test-state")

    response = unit_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": "fixed-test-state"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.cookies.get(SESSION_COOKIE_NAME) == "fake-session-id"


def test_callback_with_mismatched_state_is_rejected(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_auth_service: FakeAuthService
) -> None:
    unit_client.cookies.set(OAUTH_STATE_COOKIE_NAME, "fixed-test-state")

    response = unit_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": "an-attacker-supplied-state"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_OAUTH_STATE"


def test_callback_with_no_state_cookie_is_rejected(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_auth_service: FakeAuthService
) -> None:
    # No cookie set at all — simulates a callback hit directly, never
    # having gone through /login first.
    response = unit_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": "anything"},
        follow_redirects=False,
    )

    assert response.status_code == 400


def test_session_endpoint_returns_current_user(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    app_no_lifespan.dependency_overrides[get_current_user] = _fake_current_user

    response = unit_client.get("/api/v1/auth/session")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "loggedin@example.com"
    assert "google_sub_id" not in body


def test_session_endpoint_requires_authentication(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_auth_service: FakeAuthService
) -> None:
    # No session cookie set — fake_auth_service.get_current_user(None)
    # raises SessionNotFoundError, exactly matching what the real
    # AuthService does in this situation.
    response = unit_client.get("/api/v1/auth/session")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_logout_clears_session_cookie(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_auth_service: FakeAuthService
) -> None:
    unit_client.cookies.set(SESSION_COOKIE_NAME, "fake-session-id")

    response = unit_client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert fake_auth_service.logout_calls == ["fake-session-id"]
    set_cookie_header = response.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie_header


def test_logout_without_a_session_cookie_still_succeeds(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_auth_service: FakeAuthService
) -> None:
    response = unit_client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert fake_auth_service.logout_calls == []
