from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.services.notification_service import (
    FOLLOW_UP_DUE_NOTIFICATION_TYPE,
    HIGH_PRIORITY_NOTIFICATION_TYPE,
    NotificationService,
)
from app.domain.entities.email import Email
from app.domain.entities.notification import Notification
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.email import EmailNotFoundError


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


def _email(user: User) -> Email:
    now = datetime.now(UTC)
    return Email(
        id=uuid4(),
        thread_id=uuid4(),
        user_id=user.id,
        gmail_message_id="gmail-message",
        sender="sender@example.com",
        recipients=[user.email],
        cc=[],
        bcc=[],
        subject="Urgent contract update",
        snippet="Please review.",
        body_text="Please review.",
        body_html=None,
        received_at=now,
        is_read=False,
        is_starred=False,
        has_attachments=False,
        label_ids=["INBOX"],
        created_at=now,
        updated_at=now,
    )


class FakeEmailService:
    def __init__(self, email: Email | None) -> None:
        self.email = email
        self.calls: list[tuple[User, object]] = []

    async def get_email(self, user: User, email_id: object) -> Email:
        self.calls.append((user, email_id))
        if self.email is None:
            raise EmailNotFoundError("No email found.")
        return self.email


class FakeNotificationRepository:
    def __init__(self, notification: Notification, *, created: bool) -> None:
        self.notification = notification
        self.created = created
        self.create_calls: list[dict[str, object]] = []

    async def get_or_create(self, **fields: object) -> tuple[Notification, bool]:
        self.create_calls.append(fields)
        return self.notification, self.created


@pytest.mark.asyncio
async def test_high_priority_notification_uses_verified_email_owner_and_is_idempotent() -> None:
    user = _user()
    email = _email(user)
    notification = Notification(
        id=uuid4(),
        user_id=user.id,
        email_id=email.id,
        notification_type=HIGH_PRIORITY_NOTIFICATION_TYPE,
        title="High-priority email: Urgent contract update",
        message="This email was classified as high priority.",
        is_read=False,
        created_at=datetime.now(UTC),
    )
    email_service = FakeEmailService(email)
    repository = FakeNotificationRepository(notification, created=False)
    service = NotificationService(
        email_service=email_service,  # type: ignore[arg-type]
        notification_repository=repository,  # type: ignore[arg-type]
    )

    result, created = await service.create_high_priority_for_email(user, email.id)

    assert result is notification
    assert created is False
    assert email_service.calls == [(user, email.id)]
    assert repository.create_calls == [
        {
            "user_id": user.id,
            "email_id": email.id,
            "notification_type": HIGH_PRIORITY_NOTIFICATION_TYPE,
            "title": "High-priority email: Urgent contract update",
            "message": "This email was classified as high priority.",
        }
    ]


@pytest.mark.asyncio
async def test_high_priority_notification_does_not_create_for_an_unowned_email() -> None:
    user = _user()
    notification = Notification(
        id=uuid4(),
        user_id=user.id,
        email_id=uuid4(),
        notification_type=HIGH_PRIORITY_NOTIFICATION_TYPE,
        title="unused",
        message="unused",
        is_read=False,
        created_at=datetime.now(UTC),
    )
    repository = FakeNotificationRepository(notification, created=True)
    service = NotificationService(
        email_service=FakeEmailService(None),  # type: ignore[arg-type]
        notification_repository=repository,  # type: ignore[arg-type]
    )

    with pytest.raises(EmailNotFoundError):
        await service.create_high_priority_for_email(user, uuid4())

    assert repository.create_calls == []


@pytest.mark.asyncio
async def test_follow_up_notification_is_tied_to_specific_follow_up() -> None:
    user = _user()
    email = _email(user)
    follow_up = type(
        "FollowUpStub",
        (),
        {
            "id": uuid4(),
            "user_id": user.id,
            "email_id": email.id,
            "reason": "Check the contract response.",
        },
    )()
    notification = Notification(
        id=uuid4(),
        user_id=user.id,
        email_id=email.id,
        notification_type=FOLLOW_UP_DUE_NOTIFICATION_TYPE,
        title="Follow-up due: Urgent contract update",
        message=follow_up.reason,
        is_read=False,
        created_at=datetime.now(UTC),
        follow_up_id=follow_up.id,
    )
    repository = FakeNotificationRepository(notification, created=True)
    service = NotificationService(
        email_service=FakeEmailService(email),  # type: ignore[arg-type]
        notification_repository=repository,  # type: ignore[arg-type]
    )

    result, created = await service.create_follow_up_due(user, follow_up)  # type: ignore[arg-type]

    assert result is notification
    assert created is True
    assert repository.create_calls[0]["follow_up_id"] == follow_up.id
    assert repository.create_calls[0]["notification_type"] == FOLLOW_UP_DUE_NOTIFICATION_TYPE
