from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.di_container import get_current_user, get_draft_service
from app.domain.entities.draft import Draft
from app.domain.entities.email import Email
from app.domain.entities.user import User
from app.domain.enums.draft_status import DraftStatus
from app.domain.enums.user_status import UserStatus


def _user() -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        email="user@example.com",
        full_name="Test User",
        google_sub_id="sub-1",
        status=UserStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


def _email(user_id, *, email_id=None) -> Email:
    now = datetime.now(UTC)
    return Email(
        id=email_id or uuid4(),
        thread_id=uuid4(),
        user_id=user_id,
        gmail_message_id="gmail-message-1",
        sender="sender@example.com",
        recipients=["user@example.com"],
        cc=[],
        bcc=[],
        subject="Original subject",
        snippet="Original snippet",
        body_text="Original email body",
        body_html=None,
        received_at=now,
        is_read=False,
        is_starred=False,
        has_attachments=False,
        label_ids=[],
        created_at=now,
        updated_at=now,
        attachments=[],
    )


def _draft(email_id, *, status=DraftStatus.GENERATED) -> Draft:
    now = datetime.now(UTC)
    return Draft(
        id=uuid4(),
        email_id=email_id,
        body="Generated reply",
        status=status,
        created_at=now,
        updated_at=now,
    )


class FakeDraftService:
    def __init__(self, user: User) -> None:
        email = _email(user.id)
        self.draft = _draft(email.id)
        self.email = email
        self.approved = False

    async def list_drafts(self, user: User, *, page: int, page_size: int):
        assert user.id == self.email.user_id
        return [(self.draft, self.email)]

    async def approve_draft(self, user: User, draft_id):
        assert user.id == self.email.user_id
        assert draft_id == self.draft.id
        self.approved = True
        return Draft(
            id=self.draft.id,
            email_id=self.draft.email_id,
            body=self.draft.body,
            status=DraftStatus.SENT,
            created_at=self.draft.created_at,
            updated_at=self.draft.updated_at,
        )


def test_list_ai_drafts_includes_owned_email_context(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    user = _user()
    service = FakeDraftService(user)
    app_no_lifespan.dependency_overrides[get_current_user] = lambda: user
    app_no_lifespan.dependency_overrides[get_draft_service] = lambda: service

    response = unit_client.get("/api/v1/drafts")

    assert response.status_code == 200
    assert response.json()["items"][0]["body"] == "Generated reply"
    assert response.json()["items"][0]["email"]["body_text"] == "Original email body"


def test_approve_ai_draft_uses_service_and_returns_sent_status(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    user = _user()
    service = FakeDraftService(user)
    app_no_lifespan.dependency_overrides[get_current_user] = lambda: user
    app_no_lifespan.dependency_overrides[get_draft_service] = lambda: service

    response = unit_client.post(f"/api/v1/drafts/{service.draft.id}/approve")

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert service.approved is True
