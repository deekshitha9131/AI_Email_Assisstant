import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.application.services.gmail_service import GmailService
from app.core.config import Settings
from app.domain.entities.oauth_token import OAuthToken
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus

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


def _user(user_id=None) -> User:
    return User(
        id=user_id or uuid4(),
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


def _raw_message(message_id: str, thread_id: str, *, with_attachment: bool = False) -> dict:
    payload = {
        "mimeType": "multipart/mixed" if with_attachment else "text/plain",
        "headers": [
            {"name": "Subject", "value": "Test subject"},
            {"name": "From", "value": "sender@example.com"},
            {"name": "To", "value": "user@example.com"},
        ],
    }
    if with_attachment:
        payload["parts"] = [
            {"mimeType": "text/plain", "body": {"data": _b64url("Body text.")}},
            {
                "mimeType": "application/pdf",
                "filename": "invoice.pdf",
                "body": {"attachmentId": "att-1", "size": 2048},
            },
        ]
    else:
        payload["body"] = {"data": _b64url("Body text.")}

    return {
        "id": message_id,
        "threadId": thread_id,
        "snippet": "snippet",
        "internalDate": "1735689600000",
        "labelIds": ["INBOX"],
        "payload": payload,
    }


class FakeGmailClient:
    def __init__(self, *, pages: list[dict], messages_by_id: dict[str, dict]) -> None:
        self._pages = pages
        self._messages_by_id = messages_by_id
        self._page_index = 0

    async def list_messages(self, *, query=None, label_ids=None, page_token=None, max_results=100):
        page = self._pages[self._page_index]
        self._page_index += 1
        return page

    async def get_message(self, message_id: str, *, format: str = "full"):
        return self._messages_by_id[message_id]

    async def get_profile(self):
        return {}


class FakeUserRepository:
    def __init__(self, *, oauth_token: OAuthToken | None) -> None:
        self._oauth_token = oauth_token

    async def get_oauth_tokens(self, user_id) -> OAuthToken | None:
        return self._oauth_token

    async def update_gmail_history_id(self, user_id, history_id: str) -> None:
        return None


class FakeThreadRepository:
    """Tracks every upsert call so tests can assert on ordering and
    argument correctness, not just final state."""

    def __init__(self) -> None:
        self._threads: dict[tuple, object] = {}
        self.upsert_calls: list[dict] = []

    async def get_by_gmail_thread_id(self, user_id, gmail_thread_id):
        return self._threads.get((user_id, gmail_thread_id))

    async def upsert(self, *, user_id, gmail_thread_id, subject, snippet, history_id):
        from app.domain.entities.thread import Thread

        self.upsert_calls.append(
            {"user_id": user_id, "gmail_thread_id": gmail_thread_id, "subject": subject}
        )
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
    """Tracks every upsert call's thread_id, so tests can assert each
    stored email is linked to the thread ThreadRepository actually
    returned — not a fabricated or stale one."""

    def __init__(self) -> None:
        self._emails: dict[tuple, object] = {}
        self.upsert_calls: list[dict] = []

    async def get_by_gmail_message_id(self, user_id, gmail_message_id):
        return self._emails.get((user_id, gmail_message_id))

    async def upsert(self, *, thread_id, user_id, parsed):
        from app.domain.entities.email import Email

        self.upsert_calls.append(
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "gmail_message_id": parsed.gmail_message_id,
                "attachment_count": len(parsed.attachments),
            }
        )
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
    thread_repository: FakeThreadRepository | None = None,
    email_repository: FakeEmailRepository | None = None,
) -> tuple[GmailService, FakeThreadRepository, FakeEmailRepository]:
    thread_repository = thread_repository or FakeThreadRepository()
    email_repository = email_repository or FakeEmailRepository()
    service = GmailService(
        user_repository=FakeUserRepository(oauth_token=oauth_token),
        thread_repository=thread_repository,
        email_repository=email_repository,
        settings=_settings(monkeypatch),
    )
    monkeypatch.setattr(
        "app.application.services.gmail_service.GmailClient",
        lambda *, oauth_token, settings: gmail_client,
    )
    return service, thread_repository, email_repository


async def test_sync_persists_through_repositories_only_no_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirms GmailService's only interaction with persistence is via
    ThreadRepository.upsert / EmailRepository.upsert — this is what
    "one sync workflow, correctly layered" actually verifies at the
    unit level: swap in a repository whose only capability is
    recording calls, and the sync must still fully succeed."""
    user = _user()
    messages_by_id = {"m1": _raw_message("m1", "t1")}
    pages = [{"messages": [{"id": "m1", "threadId": "t1"}]}]
    gmail_client = FakeGmailClient(pages=pages, messages_by_id=messages_by_id)
    service, thread_repo, email_repo = _make_service(
        monkeypatch, gmail_client=gmail_client, oauth_token=_oauth_token(user.id)
    )

    summary = await service.sync_mailbox(user)

    assert summary.emails_synced == 1
    assert len(thread_repo.upsert_calls) == 1
    assert len(email_repo.upsert_calls) == 1


async def test_synced_email_links_to_the_upserted_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """The thread_id EmailRepository.upsert receives must be exactly
    the id ThreadRepository.upsert returned for that message's
    gmail_thread_id — not a coincidentally-matching or stale value."""
    user = _user()
    messages_by_id = {"m1": _raw_message("m1", "t1")}
    pages = [{"messages": [{"id": "m1", "threadId": "t1"}]}]
    gmail_client = FakeGmailClient(pages=pages, messages_by_id=messages_by_id)
    service, thread_repo, email_repo = _make_service(
        monkeypatch, gmail_client=gmail_client, oauth_token=_oauth_token(user.id)
    )

    await service.sync_mailbox(user)

    stored_thread = thread_repo._threads[(user.id, "t1")]
    assert email_repo.upsert_calls[0]["thread_id"] == stored_thread.id


async def test_attachment_metadata_reaches_email_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    messages_by_id = {"m1": _raw_message("m1", "t1", with_attachment=True)}
    pages = [{"messages": [{"id": "m1", "threadId": "t1"}]}]
    gmail_client = FakeGmailClient(pages=pages, messages_by_id=messages_by_id)
    service, _, email_repo = _make_service(
        monkeypatch, gmail_client=gmail_client, oauth_token=_oauth_token(user.id)
    )

    summary = await service.sync_mailbox(user)

    assert summary.attachments_found == 1
    assert email_repo.upsert_calls[0]["attachment_count"] == 1


async def test_repeated_sync_calls_upsert_again_but_repository_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GmailService itself does not skip already-synced messages — it
    calls upsert every time, and idempotency is the repository's
    contract to uphold (verified for real at the integration level).
    This test confirms the service side of that division of labor:
    upsert is called again, but the shared fake store still ends up
    with exactly one row, proving upsert's own dedupe logic is what's
    actually doing the work, not some sync-level skip check."""
    user = _user()
    messages_by_id = {"m1": _raw_message("m1", "t1")}
    thread_repo = FakeThreadRepository()
    email_repo = FakeEmailRepository()

    gmail_client_1 = FakeGmailClient(
        pages=[{"messages": [{"id": "m1", "threadId": "t1"}]}], messages_by_id=messages_by_id
    )
    service_1, _, _ = _make_service(
        monkeypatch,
        gmail_client=gmail_client_1,
        oauth_token=_oauth_token(user.id),
        thread_repository=thread_repo,
        email_repository=email_repo,
    )
    await service_1.sync_mailbox(user)

    gmail_client_2 = FakeGmailClient(
        pages=[{"messages": [{"id": "m1", "threadId": "t1"}]}], messages_by_id=messages_by_id
    )
    service_2, _, _ = _make_service(
        monkeypatch,
        gmail_client=gmail_client_2,
        oauth_token=_oauth_token(user.id),
        thread_repository=thread_repo,
        email_repository=email_repo,
    )
    await service_2.sync_mailbox(user)

    assert len(email_repo.upsert_calls) == 2  # called twice
    assert len(email_repo._emails) == 1  # but only one row stored


async def test_sync_never_writes_records_for_a_different_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every upsert call GmailService makes carries the user_id of the
    User it was invoked with — never a different one, and never
    omitted."""
    user_a = _user()
    user_b = _user()
    messages_by_id = {"m1": _raw_message("m1", "t1")}
    thread_repo = FakeThreadRepository()
    email_repo = FakeEmailRepository()

    gmail_client_a = FakeGmailClient(
        pages=[{"messages": [{"id": "m1", "threadId": "t1"}]}], messages_by_id=messages_by_id
    )
    service_a, _, _ = _make_service(
        monkeypatch,
        gmail_client=gmail_client_a,
        oauth_token=_oauth_token(user_a.id),
        thread_repository=thread_repo,
        email_repository=email_repo,
    )
    await service_a.sync_mailbox(user_a)

    gmail_client_b = FakeGmailClient(
        pages=[{"messages": [{"id": "m1", "threadId": "t1"}]}], messages_by_id=messages_by_id
    )
    service_b, _, _ = _make_service(
        monkeypatch,
        gmail_client=gmail_client_b,
        oauth_token=_oauth_token(user_b.id),
        thread_repository=thread_repo,
        email_repository=email_repo,
    )
    await service_b.sync_mailbox(user_b)

    assert all(call["user_id"] == user_a.id for call in email_repo.upsert_calls[:1])
    assert email_repo.upsert_calls[1]["user_id"] == user_b.id
    # Same Gmail message ID, different users -> two distinct stored rows.
    assert len(email_repo._emails) == 2
    assert (user_a.id, "m1") in email_repo._emails
    assert (user_b.id, "m1") in email_repo._emails
