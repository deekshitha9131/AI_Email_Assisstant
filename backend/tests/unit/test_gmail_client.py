"""Tests for app/infrastructure/gmail/client.py.

Mocks googleapiclient's `build()` entirely — no live Gmail API call is
ever made. This is a test of GmailClient's request construction, error
translation, and async bridging, not a test of Gmail itself, matching
the same philosophy test_oauth_client.py uses for the OAuth handshake
(fake the far end, exercise the real client code in between).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httplib2
import pytest
from googleapiclient.errors import HttpError

from app.core.config import Settings
from app.domain.entities.oauth_token import OAuthToken
from app.domain.exceptions.gmail import (
    GmailAPIError,
    GmailAuthenticationError,
    GmailHistoryExpiredError,
)
from app.infrastructure.gmail.client import GmailClient

BASE_ENV = {
    "APP_ENV": "development",
    "APP_DEBUG": "true",
    "APP_SECRET_KEY": "dev-secret",
    "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
    "REDIS_URL": "redis://h:6379/0",
    "CELERY_BROKER_URL": "redis://h:6379/1",
    "CELERY_RESULT_BACKEND": "redis://h:6379/1",
    "TOKEN_ENCRYPTION_KEY": "test-token-encryption-key-value",
    "CORS_ORIGINS": "http://localhost:5173",
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
}


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _oauth_token() -> OAuthToken:
    return OAuthToken(
        user_id=uuid4(),
        access_token="fake-access-token",
        refresh_token="fake-refresh-token",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
        granted_scopes=["openid", "https://www.googleapis.com/auth/gmail.readonly"],
    )


def _http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b'{"error": "mocked"}')


def _client(monkeypatch: pytest.MonkeyPatch) -> GmailClient:
    return GmailClient(oauth_token=_oauth_token(), settings=_settings(monkeypatch))


@patch("app.infrastructure.gmail.client.build")
async def test_get_profile_success(mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.getProfile.return_value.execute.return_value = {
        "emailAddress": "user@example.com",
        "messagesTotal": 42,
    }
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    result = await client.get_profile()

    assert result["emailAddress"] == "user@example.com"
    mock_service.users.return_value.getProfile.assert_called_once_with(userId="me")


@patch("app.infrastructure.gmail.client.build")
async def test_list_messages_passes_filters_through(
    mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "m1", "threadId": "t1"}],
        "nextPageToken": "next-token",
    }
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    result = await client.list_messages(
        query="is:unread", label_ids=["INBOX"], page_token="prev-token", max_results=25
    )

    assert result["messages"] == [{"id": "m1", "threadId": "t1"}]
    mock_service.users.return_value.messages.return_value.list.assert_called_once_with(
        userId="me",
        q="is:unread",
        labelIds=["INBOX"],
        pageToken="prev-token",
        maxResults=25,
    )


@patch("app.infrastructure.gmail.client.build")
async def test_list_history_translates_expired_cursor(
    mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.history.return_value.list.return_value.execute.side_effect = (
        _http_error(404)
    )
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    with pytest.raises(GmailHistoryExpiredError):
        await client.list_history(start_history_id="stale-history")


@patch("app.infrastructure.gmail.client.build")
async def test_get_message_uses_full_format_by_default(
    mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": "m1",
        "payload": {},
    }
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    result = await client.get_message("m1")

    assert result["id"] == "m1"
    mock_service.users.return_value.messages.return_value.get.assert_called_once_with(
        userId="me", id="m1", format="full"
    )


@patch("app.infrastructure.gmail.client.build")
async def test_list_history_success(mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.history.return_value.list.return_value.execute.return_value = {
        "history": [{"id": "h1"}],
        "historyId": "h1",
    }
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    result = await client.list_history(start_history_id="h0")

    assert result["historyId"] == "h1"
    mock_service.users.return_value.history.return_value.list.assert_called_once_with(
        userId="me", startHistoryId="h0", pageToken=None
    )


@patch("app.infrastructure.gmail.client.build")
async def test_send_message_includes_thread_id_when_given(
    mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent-1",
        "threadId": "t1",
    }
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    result = await client.send_message(raw_message="base64url-mime-payload", thread_id="t1")

    assert result["id"] == "sent-1"
    mock_service.users.return_value.messages.return_value.send.assert_called_once_with(
        userId="me", body={"raw": "base64url-mime-payload", "threadId": "t1"}
    )


@patch("app.infrastructure.gmail.client.build")
async def test_send_message_omits_thread_id_when_not_given(
    mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent-2"
    }
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    await client.send_message(raw_message="base64url-mime-payload")

    mock_service.users.return_value.messages.return_value.send.assert_called_once_with(
        userId="me", body={"raw": "base64url-mime-payload"}
    )


@patch("app.infrastructure.gmail.client.build")
async def test_get_profile_raises_gmail_authentication_error_on_401(
    mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.getProfile.return_value.execute.side_effect = _http_error(401)
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    with pytest.raises(GmailAuthenticationError):
        await client.get_profile()


@patch("app.infrastructure.gmail.client.build")
async def test_get_profile_raises_gmail_authentication_error_on_403(
    mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.getProfile.return_value.execute.side_effect = _http_error(403)
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    with pytest.raises(GmailAuthenticationError):
        await client.get_profile()


@patch("app.infrastructure.gmail.client.build")
async def test_get_profile_raises_api_error_on_rate_limit(
    mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.getProfile.return_value.execute.side_effect = HttpError(
        httplib2.Response({"status": "403"}),
        b'{"error":{"errors":[{"reason":"rateLimitExceeded"}]}}',
    )
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    with pytest.raises(GmailAPIError, match="rate-limited"):
        await client.get_profile()


@patch("app.infrastructure.gmail.client.build")
async def test_get_profile_raises_api_error_when_gmail_api_is_not_enabled(
    mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.getProfile.return_value.execute.side_effect = HttpError(
        httplib2.Response({"status": "403"}),
        b'{"error":{"errors":[{"reason":"accessNotConfigured"}]}}',
    )
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    with pytest.raises(GmailAPIError, match="not enabled"):
        await client.get_profile()


@patch("app.infrastructure.gmail.client.build")
async def test_get_profile_raises_gmail_api_error_on_other_http_errors(
    mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.getProfile.return_value.execute.side_effect = _http_error(500)
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    with pytest.raises(GmailAPIError):
        await client.get_profile()


@patch("app.infrastructure.gmail.client.build")
async def test_service_is_built_once_and_memoized(
    mock_build: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.getProfile.return_value.execute.return_value = {}
    mock_build.return_value = mock_service

    client = _client(monkeypatch)
    await client.get_profile()
    await client.get_profile()

    assert mock_build.call_count == 1


@patch("app.infrastructure.gmail.client.Credentials")
@patch("app.infrastructure.gmail.client.build")
async def test_credentials_are_built_from_stored_oauth_tokens(
    mock_build: MagicMock, mock_credentials_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.getProfile.return_value.execute.return_value = {}
    mock_build.return_value = mock_service

    settings = _settings(monkeypatch)
    oauth_token = _oauth_token()
    client = GmailClient(oauth_token=oauth_token, settings=settings)

    await client.get_profile()

    mock_credentials_cls.assert_called_once_with(
        token=oauth_token.access_token,
        refresh_token=oauth_token.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=oauth_token.granted_scopes,
    )
