from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.di_container import get_current_user, get_notification_service
from app.domain.entities.notification import Notification
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.notification import NotificationNotFoundError


def _user() -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        email="user@example.com",
        full_name="Test User",
        google_sub_id="test-user",
        status=UserStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


def _notification(user: User) -> Notification:
    return Notification(
        id=uuid4(),
        user_id=user.id,
        email_id=uuid4(),
        notification_type="high_priority_email",
        title="High-priority email: Contract update",
        message="This email was classified as high priority.",
        is_read=False,
        created_at=datetime.now(UTC),
    )


class FakeNotificationService:
    def __init__(self, notification: Notification) -> None:
        self.notification = notification
        self.list_users: list[User] = []
        self.count_users: list[User] = []
        self.read_calls: list[tuple[User, UUID]] = []

    async def list(self, user: User) -> list[Notification]:
        self.list_users.append(user)
        return [self.notification]

    async def unread_count(self, user: User) -> int:
        self.count_users.append(user)
        return 1

    async def mark_as_read(self, user: User, notification_id: UUID) -> Notification:
        self.read_calls.append((user, notification_id))
        if notification_id != self.notification.id:
            raise NotificationNotFoundError("No notification found.")
        self.notification.is_read = True
        return self.notification


@pytest.fixture
def notification_context(app_no_lifespan: FastAPI) -> tuple[User, FakeNotificationService]:
    user = _user()
    service = FakeNotificationService(_notification(user))
    app_no_lifespan.dependency_overrides[get_current_user] = lambda: user
    app_no_lifespan.dependency_overrides[get_notification_service] = lambda: service
    return user, service


def test_notifications_are_listed_only_for_the_authenticated_user(
    unit_client: TestClient, notification_context: tuple[User, FakeNotificationService]
) -> None:
    user, service = notification_context

    response = unit_client.get("/api/v1/notifications")

    assert response.status_code == 200
    assert response.json()[0]["id"] == str(service.notification.id)
    assert "user_id" not in response.json()[0]
    assert service.list_users == [user]


def test_notification_unread_count_uses_the_authenticated_user(
    unit_client: TestClient, notification_context: tuple[User, FakeNotificationService]
) -> None:
    user, service = notification_context

    response = unit_client.get("/api/v1/notifications/unread-count")

    assert response.status_code == 200
    assert response.json() == {"count": 1}
    assert service.count_users == [user]


def test_mark_notification_read_rejects_notification_outside_user_scope(
    unit_client: TestClient, notification_context: tuple[User, FakeNotificationService]
) -> None:
    user, service = notification_context
    other_notification_id = uuid4()

    response = unit_client.post(f"/api/v1/notifications/{other_notification_id}/read")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"
    assert service.read_calls == [(user, other_notification_id)]


def test_mark_notification_as_read_for_the_authenticated_user(
    unit_client: TestClient, notification_context: tuple[User, FakeNotificationService]
) -> None:
    user, service = notification_context

    response = unit_client.post(f"/api/v1/notifications/{service.notification.id}/read")

    assert response.status_code == 200
    assert response.json()["is_read"] is True
    assert service.read_calls == [(user, service.notification.id)]
