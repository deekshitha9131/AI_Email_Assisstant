"""Tests for app/presentation/api/v1/routers/gmail.py.

Overrides get_gmail_service and get_current_user with fakes, the same
dependency_overrides pattern established by test_auth_router.py — no
live database, Redis, or Gmail involved.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.dto.gmail import GmailSentMessage, GmailSentMessages, GmailSyncSummary
from app.core.di_container import get_current_user, get_gmail_service
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.gmail import GmailNotConnectedError


class FakeGmailService:
    def __init__(self) -> None:
        self.sync_calls: list[str | None] = []
        self.summary_to_return = GmailSyncSummary(
            success=True,
            threads_synced=3,
            emails_synced=5,
            attachments_found=2,
            emails_skipped=0,
            next_page_token=None,
        )
        self.raise_on_sync: Exception | None = None
        self.sent_calls: list[tuple[User, str | None, int]] = []
        self.sent_result = GmailSentMessages(items=[])

    async def list_sent_messages(
        self, user: User, *, page_token: str | None = None, max_results: int = 25
    ) -> GmailSentMessages:
        self.sent_calls.append((user, page_token, max_results))
        return self.sent_result

    async def sync_mailbox(self, user: User, *, page_token: str | None = None) -> GmailSyncSummary:
        self.sync_calls.append(page_token)
        if self.raise_on_sync is not None:
            raise self.raise_on_sync
        return self.summary_to_return


def _fake_current_user() -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        full_name="Test User",
        google_sub_id="sub-1",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def fake_gmail_service(app_no_lifespan: FastAPI) -> FakeGmailService:
    service = FakeGmailService()
    app_no_lifespan.dependency_overrides[get_gmail_service] = lambda: service
    app_no_lifespan.dependency_overrides[get_current_user] = _fake_current_user
    return service


def test_sync_endpoint_returns_summary(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    response = unit_client.post("/api/v1/gmail/sync", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["threads_synced"] == 3
    assert body["emails_synced"] == 5
    assert body["attachments_found"] == 2
    assert body["emails_skipped"] == 0
    assert body["next_page_token"] is None
    assert fake_gmail_service.sync_calls == [None]


def test_sync_endpoint_passes_page_token_through(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    response = unit_client.post("/api/v1/gmail/sync", json={"page_token": "resume-token"})

    assert response.status_code == 200
    assert fake_gmail_service.sync_calls == ["resume-token"]


def test_sync_endpoint_requires_authentication(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    # No get_current_user override — falls through to the real
    # dependency, which raises SessionNotFoundError (401) with no
    # session cookie present, same as every other protected endpoint.
    service = FakeGmailService()
    app_no_lifespan.dependency_overrides[get_gmail_service] = lambda: service

    response = unit_client.post("/api/v1/gmail/sync", json={})

    assert response.status_code == 401


def test_sync_endpoint_returns_401_when_gmail_not_connected(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    fake_gmail_service.raise_on_sync = GmailNotConnectedError("Gmail is not connected.")

    response = unit_client.post("/api/v1/gmail/sync", json={})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "GMAIL_NOT_CONNECTED"


def test_sent_endpoint_passes_authenticated_user_and_pagination(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    response = unit_client.get("/api/v1/gmail/sent?page_token=next&page_size=10")

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_page_token": None}
    assert len(fake_gmail_service.sent_calls) == 1
    user, page_token, page_size = fake_gmail_service.sent_calls[0]
    assert user.email == "user@example.com"
    assert page_token == "next"
    assert page_size == 10


def test_sent_endpoint_returns_message_content_and_identifiers(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    fake_gmail_service.sent_result = GmailSentMessages(
        items=[
            GmailSentMessage(
                gmail_message_id="message-1",
                gmail_thread_id="thread-1",
                sender="me@example.com",
                recipients=["recipient@example.com"],
                cc=[],
                bcc=[],
                subject="Sent subject",
                snippet="Sent preview",
                body_text="Sent body",
                body_html=None,
                sent_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ],
        next_page_token="next-token",
    )

    response = unit_client.get("/api/v1/gmail/sent")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "gmail_message_id": "message-1",
                "gmail_thread_id": "thread-1",
                "sender": "me@example.com",
                "recipients": ["recipient@example.com"],
                "cc": [],
                "bcc": [],
                "subject": "Sent subject",
                "snippet": "Sent preview",
                "body_text": "Sent body",
                "body_html": None,
                "sent_at": "2026-01-01T00:00:00Z",
            }
        ],
        "next_page_token": "next-token",
    }


def test_sent_endpoint_requires_authentication(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    app_no_lifespan.dependency_overrides[get_gmail_service] = lambda: FakeGmailService()

    response = unit_client.get("/api/v1/gmail/sent")

    assert response.status_code == 401
