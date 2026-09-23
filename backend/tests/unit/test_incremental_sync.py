"""Tests for GmailService.sync_incremental (app/application/services/gmail_service.py).

Same fake-collaborator philosophy as test_gmail_service.py: every
network boundary (GmailClient) is faked, EmailParser runs for real
against hand-built Gmail-shaped fixtures.
"""

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.application.services.gmail_service import GmailService
from app.core.config import Settings
from app.domain.entities.oauth_token import OAuthToken
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.gmail import GmailAPIError, GmailSyncInProgressError

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


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _user() -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        full_name="Test User",
        google_sub_id="sub-1",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _oauth_token(user_id) -> OAuthToken:
    return OAuthToken(
        user_id=user_id,
        access_token="fake-access-token",
        refresh_token="fake-refresh-token",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
        granted_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )


def _raw_message(message_id: str, thread_id: str) -> dict:
    return {
        "id": message_id,
        "threadId": thread_id,
        "snippet": "Updated content",
        "internalDate": "1735689600000",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Updated subject"},
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "user@example.com"},
            ],
            "body": {"data": _b64url("Updated body.")},
        },
    }


class FakeGmailClient:
    """Stands in for GmailClient — list_history/get_message return
    fixtures the test controls directly."""

    def __init__(
        self,
        *,
        history_pages: list[dict],
        messages_by_id: dict[str, dict],
        initial_messages: list[dict] | None = None,
    ) -> None:
        self._history_pages = history_pages
        self._messages_by_id = messages_by_id
        self._initial_messages = initial_messages or []
        self._page_index = 0
        self.list_history_calls: list[tuple[str, str | None]] = []
        self.raise_on_list_history: Exception | None = None
        self.list_messages_calls: list[str | None] = []

    async def list_history(self, *, start_history_id: str, page_token: str | None = None):
        self.list_history_calls.append((start_history_id, page_token))
        if self.raise_on_list_history is not None:
            raise self.raise_on_list_history
        page = self._history_pages[self._page_index]
        self._page_index += 1
        return page

    async def get_message(self, message_id: str, *, format: str = "full"):
        return self._messages_by_id[message_id]

    async def list_messages(self, *, label_ids=None, page_token=None, max_results=100):
        self.list_messages_calls.append(page_token)
        return {"messages": self._initial_messages}

    async def get_profile(self):
        return {"historyId": "200"}


class FakeUserRepository:
    def __init__(self, *, oauth_token: OAuthToken | None, gmail_history_id: str | None) -> None:
        self._oauth_token = oauth_token
        self._gmail_history_id = gmail_history_id
        self.update_history_id_calls: list[str] = []

    async def get_oauth_tokens(self, user_id) -> OAuthToken | None:
        return self._oauth_token

    async def get_gmail_history_id(self, user_id) -> str | None:
        return self._gmail_history_id

    async def update_gmail_history_id(self, user_id, history_id: str) -> None:
        self._gmail_history_id = history_id
        self.update_history_id_calls.append(history_id)


class FakeThreadRepository:
    def __init__(self) -> None:
        self._threads: dict[tuple, object] = {}

    async def get_by_gmail_thread_id(self, user_id, gmail_thread_id):
        return self._threads.get((user_id, gmail_thread_id))

    async def upsert(self, *, user_id, gmail_thread_id, subject, snippet, history_id):
        from app.domain.entities.thread import Thread

        key = (user_id, gmail_thread_id)
        existing = self._threads.get(key)
        thread = Thread(
            id=existing.id if existing else uuid4(),
            user_id=user_id,
            gmail_thread_id=gmail_thread_id,
            subject=subject,
            snippet=snippet,
            history_id=history_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self._threads[key] = thread
        return thread


class FakeEmailRepository:
    def __init__(self) -> None:
        self._emails: dict[tuple, object] = {}
        self.upsert_calls = 0

    async def get_by_gmail_message_id(self, user_id, gmail_message_id):
        return self._emails.get((user_id, gmail_message_id))

    async def upsert(self, *, thread_id, user_id, parsed):
        from app.domain.entities.email import Email

        self.upsert_calls += 1
        key = (user_id, parsed.gmail_message_id)
        was_created = key not in self._emails
        email = Email(
            id=uuid4(),
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id=parsed.gmail_message_id,
            sender=parsed.sender,
            recipients=parsed.recipients,
            cc=parsed.cc,
            bcc=parsed.bcc,
            subject=parsed.subject,
            snippet=parsed.snippet,
            body_text=parsed.body_text,
            body_html=parsed.body_html,
            received_at=parsed.internal_date,
            is_read=True,
            is_starred=False,
            has_attachments=parsed.has_attachments,
            label_ids=parsed.label_ids,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self._emails[key] = email
        return email, was_created


def _make_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gmail_client: FakeGmailClient,
    oauth_token: OAuthToken | None,
    gmail_history_id: str | None,
    thread_repository: FakeThreadRepository | None = None,
    email_repository: FakeEmailRepository | None = None,
) -> tuple[GmailService, FakeUserRepository, FakeEmailRepository]:
    user_repository = FakeUserRepository(oauth_token=oauth_token, gmail_history_id=gmail_history_id)
    thread_repository = thread_repository or FakeThreadRepository()
    email_repository = email_repository or FakeEmailRepository()
    service = GmailService(
        user_repository=user_repository,
        thread_repository=thread_repository,
        email_repository=email_repository,
        settings=_settings(monkeypatch),
    )
    monkeypatch.setattr(
        "app.application.services.gmail_service.GmailClient",
        lambda *, oauth_token, settings: gmail_client,
    )
    return service, user_repository, email_repository


async def test_sync_incremental_falls_back_to_initial_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    initial_messages = [{"id": f"m{index}", "threadId": f"t{index}"} for index in range(11)]
    messages_by_id = {
        message["id"]: _raw_message(message["id"], message["threadId"])
        for message in initial_messages
    }
    gmail_client = FakeGmailClient(
        history_pages=[], messages_by_id=messages_by_id, initial_messages=initial_messages
    )
    service, user_repo, _ = _make_service(
        monkeypatch,
        gmail_client=gmail_client,
        oauth_token=_oauth_token(user.id),
        gmail_history_id=None,
    )

    summary = await service.sync_incremental(user)

    assert summary.success is True
    assert summary.emails_synced == 10
    assert summary.history_id == "200"
    assert gmail_client.list_messages_calls == [None]
    assert user_repo.update_history_id_calls == ["200"]


async def test_sync_incremental_success(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    messages_by_id = {"m1": _raw_message("m1", "t1"), "m2": _raw_message("m2", "t2")}
    history_pages = [
        {
            "history": [
                {"messagesAdded": [{"message": {"id": "m1", "threadId": "t1"}}]},
                {"labelsAdded": [{"message": {"id": "m2", "threadId": "t2"}}]},
            ],
            "historyId": "200",
        }
    ]
    gmail_client = FakeGmailClient(history_pages=history_pages, messages_by_id=messages_by_id)
    service, user_repo, email_repo = _make_service(
        monkeypatch,
        gmail_client=gmail_client,
        oauth_token=_oauth_token(user.id),
        gmail_history_id="100",
    )

    summary = await service.sync_incremental(user)

    assert summary.success is True
    assert summary.emails_synced == 2
    assert summary.threads_updated == 2
    assert summary.emails_skipped == 0
    assert summary.history_id == "200"
    assert email_repo.upsert_calls == 2
    assert user_repo.update_history_id_calls == ["200"]
    assert gmail_client.list_history_calls == [("100", None)]


async def test_sync_incremental_rejects_concurrent_run_for_same_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingGmailClient(FakeGmailClient):
        async def list_history(self, *, start_history_id: str, page_token: str | None = None):
            started.set()
            await release.wait()
            return {"history": [], "historyId": "200"}

    gmail_client = BlockingGmailClient(history_pages=[], messages_by_id={})
    service, _, _ = _make_service(
        monkeypatch,
        gmail_client=gmail_client,
        oauth_token=_oauth_token(user.id),
        gmail_history_id="100",
    )

    first_run = asyncio.create_task(service.sync_incremental(user))
    await started.wait()

    with pytest.raises(GmailSyncInProgressError):
        await service.sync_incremental(user)

    release.set()
    summary = await first_run
    assert summary.history_id == "200"


async def test_sync_incremental_allows_different_users_to_run_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = [_user(), _user()]
    started = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]

    def blocking_client(index: int) -> FakeGmailClient:
        class BlockingGmailClient(FakeGmailClient):
            async def list_history(
                self, *, start_history_id: str, page_token: str | None = None
            ):
                started[index].set()
                await release[index].wait()
                return {"history": [], "historyId": str(200 + index)}

        return BlockingGmailClient(history_pages=[], messages_by_id={})

    clients = {user.id: blocking_client(index) for index, user in enumerate(users)}
    services = []
    for user in users:
        service, _, _ = _make_service(
            monkeypatch,
            gmail_client=clients[user.id],
            oauth_token=_oauth_token(user.id),
            gmail_history_id="100",
        )
        services.append(service)
    monkeypatch.setattr(
        "app.application.services.gmail_service.GmailClient",
        lambda *, oauth_token, settings: clients[oauth_token.user_id],
    )

    first_run = asyncio.create_task(services[0].sync_incremental(users[0]))
    second_run = asyncio.create_task(services[1].sync_incremental(users[1]))
    await asyncio.gather(*(event.wait() for event in started))

    release[0].set()
    release[1].set()
    summaries = await asyncio.gather(first_run, second_run)

    assert {summary.history_id for summary in summaries} == {"200", "201"}


async def test_sync_incremental_with_no_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    history_pages = [{"history": [], "historyId": "101"}]
    gmail_client = FakeGmailClient(history_pages=history_pages, messages_by_id={})
    service, user_repo, email_repo = _make_service(
        monkeypatch,
        gmail_client=gmail_client,
        oauth_token=_oauth_token(user.id),
        gmail_history_id="100",
    )

    summary = await service.sync_incremental(user)

    assert summary.emails_synced == 0
    assert summary.threads_updated == 0
    assert summary.history_id == "101"
    # The cursor still advances even with zero changes — otherwise the
    # *next* incremental sync would needlessly re-scan the same range.
    assert user_repo.update_history_id_calls == ["101"]
    assert email_repo.upsert_calls == 0


async def test_sync_incremental_deduplicates_message_ids_across_history_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same message can appear under both messagesAdded and
    labelsAdded in one history record — must only be fetched/stored once."""
    user = _user()
    messages_by_id = {"m1": _raw_message("m1", "t1")}
    history_pages = [
        {
            "history": [
                {
                    "messagesAdded": [{"message": {"id": "m1", "threadId": "t1"}}],
                    "labelsAdded": [{"message": {"id": "m1", "threadId": "t1"}}],
                }
            ],
            "historyId": "200",
        }
    ]
    gmail_client = FakeGmailClient(history_pages=history_pages, messages_by_id=messages_by_id)
    service, _, email_repo = _make_service(
        monkeypatch,
        gmail_client=gmail_client,
        oauth_token=_oauth_token(user.id),
        gmail_history_id="100",
    )

    summary = await service.sync_incremental(user)

    assert summary.emails_synced == 1
    assert email_repo.upsert_calls == 1


async def test_sync_incremental_propagates_gmail_api_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    gmail_client = FakeGmailClient(history_pages=[], messages_by_id={})
    gmail_client.raise_on_list_history = GmailAPIError("Gmail returned a 500.")
    service, _, _ = _make_service(
        monkeypatch,
        gmail_client=gmail_client,
        oauth_token=_oauth_token(user.id),
        gmail_history_id="100",
    )

    with pytest.raises(GmailAPIError):
        await service.sync_incremental(user)


async def test_sync_incremental_run_twice_with_no_new_changes_second_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running incremental sync, then running it again immediately with
    no further Gmail-side changes, must not re-process or duplicate
    anything the second time."""
    user = _user()
    messages_by_id = {"m1": _raw_message("m1", "t1")}
    thread_repo = FakeThreadRepository()
    email_repo = FakeEmailRepository()

    # First run: one real change.
    gmail_client_1 = FakeGmailClient(
        history_pages=[
            {
                "history": [{"messagesAdded": [{"message": {"id": "m1", "threadId": "t1"}}]}],
                "historyId": "200",
            }
        ],
        messages_by_id=messages_by_id,
    )
    service_1, user_repo, _ = _make_service(
        monkeypatch,
        gmail_client=gmail_client_1,
        oauth_token=_oauth_token(user.id),
        gmail_history_id="100",
        thread_repository=thread_repo,
        email_repository=email_repo,
    )
    first_summary = await service_1.sync_incremental(user)

    # Second run: Gmail reports no changes since the new cursor (200).
    gmail_client_2 = FakeGmailClient(
        history_pages=[{"history": [], "historyId": "200"}], messages_by_id=messages_by_id
    )
    service_2, _, _ = _make_service(
        monkeypatch,
        gmail_client=gmail_client_2,
        oauth_token=_oauth_token(user.id),
        gmail_history_id=user_repo._gmail_history_id,  # picks up "200" from the first run
        thread_repository=thread_repo,
        email_repository=email_repo,
    )
    second_summary = await service_2.sync_incremental(user)

    assert first_summary.emails_synced == 1
    assert second_summary.emails_synced == 0
    assert second_summary.history_id == "200"
    assert gmail_client_2.list_history_calls == [("200", None)]
    # Still exactly one email row across both runs.
    assert email_repo.upsert_calls == 1


async def test_sync_incremental_follows_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    messages_by_id = {"m1": _raw_message("m1", "t1"), "m2": _raw_message("m2", "t2")}
    history_pages = [
        {
            "history": [{"messagesAdded": [{"message": {"id": "m1", "threadId": "t1"}}]}],
            "historyId": "150",
            "nextPageToken": "hist-page-2",
        },
        {
            "history": [{"messagesAdded": [{"message": {"id": "m2", "threadId": "t2"}}]}],
            "historyId": "200",
        },
    ]
    gmail_client = FakeGmailClient(history_pages=history_pages, messages_by_id=messages_by_id)
    service, _, email_repo = _make_service(
        monkeypatch,
        gmail_client=gmail_client,
        oauth_token=_oauth_token(user.id),
        gmail_history_id="100",
    )

    summary = await service.sync_incremental(user)

    assert summary.emails_synced == 2
    assert summary.history_id == "200"
    assert gmail_client.list_history_calls == [("100", None), ("100", "hist-page-2")]
    assert email_repo.upsert_calls == 2


async def test_sync_incremental_deduplicates_message_ids_across_history_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    messages_by_id = {"m1": _raw_message("m1", "t1")}
    history_pages = [
        {
            "history": [{"messagesAdded": [{"message": {"id": "m1", "threadId": "t1"}}]}],
            "historyId": "150",
            "nextPageToken": "hist-page-2",
        },
        {
            "history": [{"labelsAdded": [{"message": {"id": "m1", "threadId": "t1"}}]}],
            "historyId": "200",
        },
    ]
    gmail_client = FakeGmailClient(history_pages=history_pages, messages_by_id=messages_by_id)
    service, _, email_repo = _make_service(
        monkeypatch,
        gmail_client=gmail_client,
        oauth_token=_oauth_token(user.id),
        gmail_history_id="100",
    )

    summary = await service.sync_incremental(user)

    assert summary.emails_synced == 1
    assert email_repo.upsert_calls == 1
