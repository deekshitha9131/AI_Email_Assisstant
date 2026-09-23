from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.schemas.ai_understanding import AIUnderstandingResult
from app.application.dto.gmail import GmailIncrementalSyncSummary
from app.core.di_container import (
    get_current_user,
    get_draft_service,
    get_email_ai_understanding_repository,
    get_email_service,
    get_follow_up_service,
    get_gmail_service,
    get_notification_service,
    get_redis,
    get_settings_dependency,
    get_understanding_service,
    get_user_repository,
)
from app.domain.entities.draft import Draft
from app.domain.entities.email import Email
from app.domain.entities.user import User
from app.domain.enums.draft_status import DraftStatus
from app.domain.enums.follow_up_status import FollowUpStatus
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.email import EmailNotFoundError
from app.domain.exceptions.follow_up import FollowUpStatusError
from app.presentation.api.v1.routers.automation import _priority_from_urgency


class FakeUserRepository:
    def __init__(self, user: User) -> None:
        self.user = user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.user if user_id == self.user.id else None

    async def get_oauth_tokens(self, user_id: UUID):
        return None


class FakeGmailService:
    def __init__(self) -> None:
        self.calls: list[User] = []

    async def sync_incremental(self, user: User) -> GmailIncrementalSyncSummary:
        self.calls.append(user)
        return GmailIncrementalSyncSummary(
            success=True,
            emails_synced=2,
            threads_updated=1,
            attachments_found=0,
            emails_skipped=0,
            history_id="42",
        )


class FakeEmailService:
    def __init__(self, emails: dict[UUID, Email]) -> None:
        self.emails = emails
        self.calls: list[tuple[User, UUID]] = []

    async def get_email(self, user: User, email_id: UUID) -> Email:
        self.calls.append((user, email_id))
        return self.emails[email_id]


class FakeAIRepository:
    def __init__(self, email_ids: list[UUID] | None = None, existing=None) -> None:
        self.email_ids = email_ids or []
        self.existing = existing
        self.calls: list[tuple[UUID, int, int]] = []
        self.get_calls: list[UUID] = []
        self.upsert_calls: list[tuple[UUID, AIUnderstandingResult]] = []

    async def list_unprocessed_email_ids(
        self, user_id: UUID, *, limit: int, offset: int
    ) -> list[UUID]:
        self.calls.append((user_id, limit, offset))
        return self.email_ids

    async def get_by_email_id(self, email_id: UUID):
        self.get_calls.append(email_id)
        return self.existing

    async def upsert(self, email_id: UUID, result: AIUnderstandingResult):
        self.upsert_calls.append((email_id, result))


class FakeUnderstandingService:
    def __init__(self, result: AIUnderstandingResult) -> None:
        self.result = result
        self.calls: list[Email] = []

    async def analyze_email(self, email: Email) -> AIUnderstandingResult:
        self.calls.append(email)
        return self.result


class FakeFollowUpService:
    def __init__(self, due_follow_ups=None) -> None:
        self.calls: list[tuple] = []
        self.due_follow_ups = due_follow_ups or []
        self.notify_result = None

    async def create_from_ai(self, user, email_id, *, follow_up_needed, due_at, reason):
        self.calls.append((user, email_id, follow_up_needed, due_at, reason))
        return None

    async def list_due(self, user, *, limit):
        self.calls.append((user, limit))
        return self.due_follow_ups

    async def notify(self, user, follow_up_id, *, notification_service):
        self.calls.append((user, follow_up_id, notification_service))
        if isinstance(self.notify_result, Exception):
            raise self.notify_result
        return self.notify_result


class FakeDraftService:
    def __init__(self, draft: Draft) -> None:
        self.draft = draft
        self.calls: list[tuple[User, UUID]] = []

    async def create_draft(self, user: User, email_id: UUID) -> Draft:
        self.calls.append((user, email_id))
        return self.draft


class FakeNotificationService:
    def __init__(self, *, created: bool) -> None:
        self.created = created
        self.calls: list[tuple[User, UUID]] = []

    async def create_high_priority_for_email(self, user: User, email_id: UUID):
        self.calls.append((user, email_id))
        return object(), self.created


class FakeFollowUpNotificationService:
    async def create_follow_up_due(self, user, follow_up):
        return object(), True


def _fake_user() -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        email="automation@example.com",
        full_name="Automation User",
        google_sub_id="automation-sub",
        status=UserStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


def _fake_email(user_id: UUID) -> Email:
    now = datetime.now(UTC)
    return Email(
        id=uuid4(),
        thread_id=uuid4(),
        user_id=user_id,
        gmail_message_id="gmail-message-1",
        sender="sender@example.com",
        recipients=["automation@example.com"],
        cc=[],
        bcc=[],
        subject="Subject",
        snippet="Snippet",
        body_text="Body",
        body_html=None,
        received_at=now,
        is_read=False,
        is_starred=False,
        has_attachments=False,
        label_ids=["INBOX"],
        created_at=now,
        updated_at=now,
    )


def _fake_ai_result() -> AIUnderstandingResult:
    return AIUnderstandingResult(
        category="work",
        intent="request",
        urgency="medium",
        sentiment="neutral",
        summary="A work email.",
        confidence=0.9,
    )


def _fake_draft(email_id: UUID) -> Draft:
    now = datetime.now(UTC)
    return Draft(
        id=uuid4(),
        email_id=email_id,
        body="Generated reply body.",
        status=DraftStatus.GENERATED,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def automation_context(app_no_lifespan: FastAPI):
    user = _fake_user()
    token = "test-n8n-token"
    app_no_lifespan.dependency_overrides[get_settings_dependency] = lambda: SimpleNamespace(
        n8n_automation_token=token,
        n8n_automation_user_id=user.id,
    )
    app_no_lifespan.dependency_overrides[get_user_repository] = lambda: FakeUserRepository(user)
    app_no_lifespan.state.follow_up_service = FakeFollowUpService()
    app_no_lifespan.dependency_overrides[get_follow_up_service] = (
        lambda: app_no_lifespan.state.follow_up_service
    )
    return app_no_lifespan, user, token


class FakeRedisStatusClient:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload
        self._last_set = None

    async def get(self, key: str):
        if self.payload is None:
            return None
        return self.payload if isinstance(self.payload, str) else None

    async def set(self, key: str, value: str) -> None:
        self._last_set = (key, value)
        self.payload = value


def test_automation_endpoints_require_bearer_token(
    automation_context, unit_client: TestClient
) -> None:
    _app, _user, _token = automation_context

    response = unit_client.post("/api/v1/automation/gmail/sync/incremental")

    assert response.status_code == 401


def test_automation_status_update_persists_snapshot(
    automation_context, unit_client: TestClient
) -> None:
    app, _user, token = automation_context
    redis_client = FakeRedisStatusClient()
    app.dependency_overrides[get_redis] = lambda: redis_client

    response = unit_client.post(
        "/api/v1/automation/status",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "status": "error",
            "last_failure_at": "2026-09-21T10:00:00Z",
            "last_error": "sync failed",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "last_success_at": None,
        "last_failure_at": "2026-09-21T10:00:00Z",
        "last_error": "sync failed",
    }
    assert redis_client._last_set is not None


def test_automation_status_update_rejects_invalid_auth(
    automation_context, unit_client: TestClient
) -> None:
    app, _user, _token = automation_context
    app.dependency_overrides[get_redis] = lambda: FakeRedisStatusClient()

    response = unit_client.post(
        "/api/v1/automation/status",
        headers={"Authorization": "Bearer wrong-token"},
        json={"status": "ok"},
    )

    assert response.status_code == 401


def test_status_endpoint_returns_unknown_when_no_snapshot(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    user = _fake_user()
    token = "test-n8n-token"
    app_no_lifespan.dependency_overrides[get_settings_dependency] = lambda: SimpleNamespace(
        n8n_automation_token=token,
        n8n_automation_user_id=user.id,
    )
    app_no_lifespan.dependency_overrides[get_redis] = lambda: FakeRedisStatusClient()
    app_no_lifespan.dependency_overrides[get_user_repository] = lambda: FakeUserRepository(user)
    app_no_lifespan.dependency_overrides[get_current_user] = lambda: user

    response = unit_client.get(
        "/api/v1/status",
        headers={"Cookie": "session_id=test-session"},
    )

    assert response.status_code == 200
    assert response.json()["automation"] == {
        "status": "unknown",
        "last_success_at": None,
        "last_failure_at": None,
        "last_error": None,
    }


def test_automation_status_success_and_failure_round_trip(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    user = _fake_user()
    token = "test-n8n-token"
    app_no_lifespan.dependency_overrides[get_settings_dependency] = lambda: SimpleNamespace(
        n8n_automation_token=token,
        n8n_automation_user_id=user.id,
    )
    app_no_lifespan.dependency_overrides[get_user_repository] = lambda: FakeUserRepository(user)
    app_no_lifespan.dependency_overrides[get_current_user] = lambda: user

    redis_client = FakeRedisStatusClient(
        '{"status":"ok","last_success_at":"2026-09-21T09:00:00Z","last_failure_at":null,"last_error":null}'
    )
    app_no_lifespan.dependency_overrides[get_redis] = lambda: redis_client

    response = unit_client.get(
        "/api/v1/status",
        headers={"Cookie": "session_id=test-session"},
    )

    assert response.status_code == 200
    assert response.json()["automation"]["status"] == "ok"
    assert response.json()["automation"]["last_success_at"] == "2026-09-21T09:00:00Z"


def test_automation_due_follow_ups_returns_only_service_selected_items(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    due = SimpleNamespace(
        id=uuid4(),
        email_id=uuid4(),
        thread_id=uuid4(),
        due_at=datetime.now(UTC),
        reason="Check the request.",
        status=FollowUpStatus.SNOOZED,
    )
    app.state.follow_up_service.due_follow_ups = [due]

    response = unit_client.get(
        "/api/v1/automation/follow-ups/due?limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "follow_up_id": str(due.id),
            "email_id": str(due.email_id),
            "thread_id": str(due.thread_id),
            "due_at": due.due_at.isoformat().replace("+00:00", "Z"),
            "reason": "Check the request.",
            "status": "snoozed",
        }
    ]
    assert app.state.follow_up_service.calls[-1] == (user, 10)


def test_automation_due_follow_ups_requires_bearer_token(
    automation_context, unit_client: TestClient
) -> None:
    response = unit_client.get("/api/v1/automation/follow-ups/due")

    assert response.status_code == 401


def test_automation_notify_follow_up_marks_notification_created(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    follow_up = SimpleNamespace(id=uuid4())
    app.state.follow_up_service.notify_result = (follow_up, True)
    app.dependency_overrides[get_notification_service] = lambda: FakeFollowUpNotificationService()

    response = unit_client.post(
        f"/api/v1/automation/follow-ups/{follow_up.id}/notify",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"follow_up_id": str(follow_up.id), "status": "created"}
    assert app.state.follow_up_service.calls[-1][0] == user


def test_automation_notify_follow_up_is_idempotent(
    automation_context, unit_client: TestClient
) -> None:
    app, _user, token = automation_context
    follow_up = SimpleNamespace(id=uuid4())
    app.state.follow_up_service.notify_result = (follow_up, False)
    app.dependency_overrides[get_notification_service] = lambda: FakeFollowUpNotificationService()

    response = unit_client.post(
        f"/api/v1/automation/follow-ups/{follow_up.id}/notify",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "already_notified"


def test_automation_notify_follow_up_rejects_terminal_status(
    automation_context, unit_client: TestClient
) -> None:
    app, _user, token = automation_context
    follow_up_id = uuid4()
    app.state.follow_up_service.notify_result = FollowUpStatusError("Cannot modify")
    app.dependency_overrides[get_notification_service] = lambda: FakeFollowUpNotificationService()

    response = unit_client.post(
        f"/api/v1/automation/follow-ups/{follow_up_id}/notify",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


def test_automation_endpoints_reject_invalid_token(
    automation_context, unit_client: TestClient
) -> None:
    _app, _user, _token = automation_context

    response = unit_client.get(
        "/api/v1/automation/emails/unprocessed",
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401


def test_automation_sync_uses_configured_user(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    service = FakeGmailService()
    app.dependency_overrides[get_gmail_service] = lambda: service

    response = unit_client.post(
        "/api/v1/automation/gmail/sync/incremental",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["emails_synced"] == 2
    assert service.calls == [user]


def test_automation_sync_returns_upstream_error_status_on_service_failure(
    automation_context, unit_client: TestClient
) -> None:
    app, _user, token = automation_context
    service = FakeGmailService()
    service.sync_incremental = lambda user: (_ for _ in ()).throw(RuntimeError("upstream outage"))
    app.dependency_overrides[get_gmail_service] = lambda: service

    response = unit_client.post(
        "/api/v1/automation/gmail/sync/incremental",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AUTOMATION_API_ERROR"


def test_automation_notify_follow_up_returns_upstream_error_status_on_service_failure(
    automation_context, unit_client: TestClient
) -> None:
    app, _user, token = automation_context
    follow_up = SimpleNamespace(id=uuid4())
    app.state.follow_up_service.notify_result = RuntimeError("follow-up notification failed")
    app.dependency_overrides[get_notification_service] = lambda: FakeFollowUpNotificationService()

    response = unit_client.post(
        f"/api/v1/automation/follow-ups/{follow_up.id}/notify",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AUTOMATION_API_ERROR"


def test_automation_unprocessed_emails_are_bounded_and_user_scoped(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    email = _fake_email(user.id)
    email_service = FakeEmailService({email.id: email})
    ai_repository = FakeAIRepository([email.id])
    app.dependency_overrides[get_email_service] = lambda: email_service
    app.dependency_overrides[get_email_ai_understanding_repository] = lambda: ai_repository

    response = unit_client.get(
        "/api/v1/automation/emails/unprocessed?limit=10&offset=20",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == str(email.id)
    assert ai_repository.calls == [(user.id, 10, 20)]
    assert email_service.calls == [(user, email.id)]


def test_automation_analyze_email_processes_and_persists_result(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    email = _fake_email(user.id)
    email_service = FakeEmailService({email.id: email})
    ai_repository = FakeAIRepository()
    understanding_service = FakeUnderstandingService(_fake_ai_result())
    app.dependency_overrides[get_email_service] = lambda: email_service
    app.dependency_overrides[get_email_ai_understanding_repository] = lambda: ai_repository
    app.dependency_overrides[get_understanding_service] = lambda: understanding_service

    response = unit_client.post(
        f"/api/v1/automation/emails/{email.id}/analyze",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"email_id": str(email.id), "status": "processed"}
    assert understanding_service.calls == [email]
    assert ai_repository.upsert_calls[0][0] == email.id
    assert app.state.follow_up_service.calls == [
        (user, email.id, False, None, None)
    ]


def test_automation_analyze_email_is_idempotent(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    email = _fake_email(user.id)
    email_service = FakeEmailService({email.id: email})
    ai_repository = FakeAIRepository(
        existing=SimpleNamespace(
            follow_up_needed=False,
            follow_up_date=None,
            follow_up_reason=None,
        )
    )
    understanding_service = FakeUnderstandingService(_fake_ai_result())
    app.dependency_overrides[get_email_service] = lambda: email_service
    app.dependency_overrides[get_email_ai_understanding_repository] = lambda: ai_repository
    app.dependency_overrides[get_understanding_service] = lambda: understanding_service

    response = unit_client.post(
        f"/api/v1/automation/emails/{email.id}/analyze",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"email_id": str(email.id), "status": "already_processed"}
    assert understanding_service.calls == []
    assert ai_repository.upsert_calls == []


def test_automation_priority_maps_critical_urgency_and_returns_reason(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    email = _fake_email(user.id)
    email_service = FakeEmailService({email.id: email})
    ai_repository = FakeAIRepository(
        existing=SimpleNamespace(
            urgency="critical",
            category="finance",
            summary="Payment failure requires immediate attention.",
            confidence=0.95,
        )
    )
    app.dependency_overrides[get_email_service] = lambda: email_service
    app.dependency_overrides[get_email_ai_understanding_repository] = lambda: ai_repository

    response = unit_client.get(
        f"/api/v1/automation/emails/{email.id}/priority",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "email_id": str(email.id),
        "priority": "high",
        "urgency": "critical",
        "category": "finance",
        "reason": "Payment failure requires immediate attention.",
        "confidence": 0.95,
        "status": "classified",
    }
    assert ai_repository.get_calls == [email.id]


@pytest.mark.parametrize(
    ("urgency", "expected_priority"),
    [("critical", "high"), ("high", "high"), ("medium", "normal"), ("low", "low")],
)
def test_priority_mapping_uses_small_fixed_routing_set(
    urgency: str, expected_priority: str
) -> None:
    assert _priority_from_urgency(urgency).value == expected_priority


def test_automation_priority_requires_existing_classification(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    email = _fake_email(user.id)
    app.dependency_overrides[get_email_service] = lambda: FakeEmailService({email.id: email})
    app.dependency_overrides[get_email_ai_understanding_repository] = lambda: FakeAIRepository()

    response = unit_client.get(
        f"/api/v1/automation/emails/{email.id}/priority",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PRIORITY_NOT_CLASSIFIED"


def test_automation_priority_rejects_email_not_owned_by_automation_user(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    email_id = uuid4()

    class RejectingEmailService:
        async def get_email(self, requested_user: User, requested_email_id: UUID) -> Email:
            assert requested_user is user
            assert requested_email_id == email_id
            raise EmailNotFoundError("No email found.")

    ai_repository = FakeAIRepository(
        existing=SimpleNamespace(
            urgency="high", category="work", summary="Reason", confidence=0.8
        )
    )
    app.dependency_overrides[get_email_service] = lambda: RejectingEmailService()
    app.dependency_overrides[get_email_ai_understanding_repository] = lambda: ai_repository

    response = unit_client.get(
        f"/api/v1/automation/emails/{email_id}/priority",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EMAIL_NOT_FOUND"
    assert ai_repository.get_calls == []


def test_automation_priority_requires_bearer_token(
    automation_context, unit_client: TestClient
) -> None:
    _app, _user, _token = automation_context

    response = unit_client.get(f"/api/v1/automation/emails/{uuid4()}/priority")

    assert response.status_code == 401


def test_high_priority_notification_is_authenticated_and_idempotent(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    email_id = uuid4()
    service = FakeNotificationService(created=False)
    app.dependency_overrides[get_notification_service] = lambda: service

    unauthorized = unit_client.post(f"/api/v1/automation/emails/{email_id}/notifications/high-priority")
    existing = unit_client.post(
        f"/api/v1/automation/emails/{email_id}/notifications/high-priority",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert unauthorized.status_code == 401
    assert existing.status_code == 200
    assert existing.json() == {"email_id": str(email_id), "status": "already_exists"}
    assert service.calls == [(user, email_id)]


def test_automation_draft_generates_for_owned_email(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    email = _fake_email(user.id)
    email_service = FakeEmailService({email.id: email})
    draft_service = FakeDraftService(_fake_draft(email.id))
    app.dependency_overrides[get_email_service] = lambda: email_service
    app.dependency_overrides[get_draft_service] = lambda: draft_service

    response = unit_client.post(
        f"/api/v1/automation/emails/{email.id}/draft",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["email_id"] == str(email.id)
    assert response.json()["body"] == "Generated reply body."
    assert email_service.calls == [(user, email.id)]
    assert draft_service.calls == [(user, email.id)]


def test_automation_draft_rejects_email_not_owned_by_automation_user(
    automation_context, unit_client: TestClient
) -> None:
    app, user, token = automation_context
    email_id = uuid4()

    class RejectingEmailService:
        async def get_email(self, requested_user: User, requested_email_id: UUID) -> Email:
            assert requested_user is user
            assert requested_email_id == email_id
            raise EmailNotFoundError("No email found.")

    draft_service = FakeDraftService(_fake_draft(email_id))
    app.dependency_overrides[get_email_service] = lambda: RejectingEmailService()
    app.dependency_overrides[get_draft_service] = lambda: draft_service

    response = unit_client.post(
        f"/api/v1/automation/emails/{email_id}/draft",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EMAIL_NOT_FOUND"
    assert draft_service.calls == []


def test_automation_draft_requires_bearer_token(
    automation_context, unit_client: TestClient
) -> None:
    _app, _user, _token = automation_context

    response = unit_client.post(f"/api/v1/automation/emails/{uuid4()}/draft")

    assert response.status_code == 401
