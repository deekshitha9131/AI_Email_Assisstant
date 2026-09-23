from uuid import UUID

from app.application.services.email_service import EmailService
from app.domain.entities.follow_up import FollowUp
from app.domain.entities.notification import Notification
from app.domain.entities.user import User
from app.domain.exceptions.notification import NotificationNotFoundError
from app.infrastructure.database.repositories.notification_repository import NotificationRepository

HIGH_PRIORITY_NOTIFICATION_TYPE = "high_priority_email"
FOLLOW_UP_DUE_NOTIFICATION_TYPE = "follow_up_due"


class NotificationService:
    def __init__(
        self,
        *,
        email_service: EmailService,
        notification_repository: NotificationRepository,
    ) -> None:
        self._email_service = email_service
        self._notification_repository = notification_repository

    async def create_high_priority_for_email(
        self, user: User, email_id: UUID
    ) -> tuple[Notification, bool]:
        email = await self._email_service.get_email(user, email_id)
        subject = email.subject or "Untitled email"
        return await self._notification_repository.get_or_create(
            user_id=email.user_id,
            email_id=email.id,
            notification_type=HIGH_PRIORITY_NOTIFICATION_TYPE,
            title=f"High-priority email: {subject}",
            message="This email was classified as high priority.",
        )

    async def create_follow_up_due(
        self, user: User, follow_up: FollowUp
    ) -> tuple[Notification, bool]:
        email = await self._email_service.get_email(user, follow_up.email_id)
        subject = email.subject or "Untitled email"
        return await self._notification_repository.get_or_create(
            user_id=follow_up.user_id,
            email_id=follow_up.email_id,
            follow_up_id=follow_up.id,
            notification_type=FOLLOW_UP_DUE_NOTIFICATION_TYPE,
            title=f"Follow-up due: {subject}",
            message=follow_up.reason or "A follow-up is due for this email.",
        )

    async def list(self, user: User) -> list[Notification]:
        return await self._notification_repository.list_by_user(user.id)

    async def unread_count(self, user: User) -> int:
        return await self._notification_repository.count_unread_by_user(user.id)

    async def mark_as_read(self, user: User, notification_id: UUID) -> Notification:
        notification = await self._notification_repository.mark_as_read_for_user(
            notification_id, user.id
        )
        if notification is None:
            raise NotificationNotFoundError(f"No notification found with id {notification_id}.")
        return notification
