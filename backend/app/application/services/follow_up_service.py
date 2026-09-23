from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.application.services.email_service import EmailService
from app.application.services.notification_service import NotificationService
from app.application.services.thread_service import ThreadService
from app.domain.entities.follow_up import FollowUp
from app.domain.entities.user import User
from app.domain.enums.follow_up_source import FollowUpSource
from app.domain.enums.follow_up_status import FollowUpStatus
from app.domain.exceptions.follow_up import (
    ActiveFollowUpExistsError,
    FollowUpNotFoundError,
    FollowUpStatusError,
)
from app.infrastructure.database.repositories.follow_up_repository import FollowUpRepository


class FollowUpService:
    def __init__(
        self,
        *,
        email_service: EmailService,
        thread_service: ThreadService,
        repository: FollowUpRepository,
    ) -> None:
        self._email_service = email_service
        self._thread_service = thread_service
        self._repository = repository

    async def create(
        self,
        user: User,
        email_id: UUID,
        *,
        due_at: datetime,
        reason: str | None,
        source: FollowUpSource,
    ) -> FollowUp:
        email = await self._email_service.get_email(user, email_id)
        await self._thread_service.get_thread(user, email.thread_id)
        return await self._repository.create(
            user_id=user.id,
            email_id=email.id,
            thread_id=email.thread_id,
            due_at=due_at,
            reason=reason,
            source=source,
        )

    async def create_from_ai(
        self,
        user: User,
        email_id: UUID,
        *,
        follow_up_needed: bool,
        due_at: datetime | None,
        reason: str | None,
    ) -> FollowUp | None:
        if (
            not follow_up_needed
            or due_at is None
            or due_at.tzinfo is None
            or due_at.utcoffset() is None
        ):
            return None

        try:
            return await self.create(
                user,
                email_id,
                due_at=due_at,
                reason=reason,
                source=FollowUpSource.AI,
            )
        except ActiveFollowUpExistsError:
            # Repeated analysis leaves the existing active follow-up unchanged.
            return None

    async def get(self, user: User, follow_up_id: UUID) -> FollowUp:
        follow_up = await self._repository.get_by_id_for_user(follow_up_id, user.id)
        if follow_up is None:
            raise FollowUpNotFoundError(f"No follow-up found with id {follow_up_id}.")
        return follow_up

    async def list(self, user: User) -> list[FollowUp]:
        return await self._repository.list_by_user(user.id)

    async def list_due(self, user: User, *, limit: int) -> list[FollowUp]:
        return await self._repository.list_due_for_user(
            user.id, due_at=datetime.now(UTC), limit=limit
        )

    async def notify(
        self,
        user: User,
        follow_up_id: UUID,
        *,
        notification_service: NotificationService,
    ) -> tuple[FollowUp, bool]:
        follow_up = await self.get(user, follow_up_id)
        if follow_up.status == FollowUpStatus.NOTIFIED:
            return follow_up, False
        self._ensure_actionable(follow_up)

        # Notification creation is idempotent. The follow-up is marked only
        # after that operation succeeds, so failures leave it actionable.
        await notification_service.create_follow_up_due(user, follow_up)
        notified = await self._repository.mark_notified_for_user(follow_up.id, user.id)
        if notified is not None:
            return notified, True

        current = await self.get(user, follow_up.id)
        if current.status == FollowUpStatus.NOTIFIED:
            return current, False
        self._ensure_actionable(current)
        raise FollowUpStatusError(f"Follow-up {follow_up.id} could not be marked notified.")

    async def complete(self, user: User, follow_up_id: UUID) -> FollowUp:
        return await self._update_status(user, follow_up_id, FollowUpStatus.COMPLETED)

    async def dismiss(self, user: User, follow_up_id: UUID) -> FollowUp:
        return await self._update_status(user, follow_up_id, FollowUpStatus.DISMISSED)

    async def snooze(self, user: User, follow_up_id: UUID, *, due_at: datetime) -> FollowUp:
        follow_up = await self.get(user, follow_up_id)
        self._ensure_actionable(follow_up)
        if due_at.tzinfo is None or due_at.utcoffset() is None or due_at <= datetime.now(UTC):
            raise FollowUpStatusError("Snooze due_at must be a timezone-aware future datetime.")
        updated = await self._repository.update_status_for_user(
            follow_up_id,
            user.id,
            status=FollowUpStatus.SNOOZED,
            due_at=due_at,
            completed_at=None,
            dismissed_at=None,
        )
        if updated is None:
            raise FollowUpNotFoundError(f"No follow-up found with id {follow_up_id}.")
        return updated

    async def _update_status(
        self, user: User, follow_up_id: UUID, status: FollowUpStatus
    ) -> FollowUp:
        follow_up = await self.get(user, follow_up_id)
        self._ensure_actionable(follow_up)
        now = datetime.now(UTC)
        updated = await self._repository.update_status_for_user(
            follow_up_id,
            user.id,
            status=status,
            completed_at=now if status == FollowUpStatus.COMPLETED else None,
            dismissed_at=now if status == FollowUpStatus.DISMISSED else None,
        )
        if updated is None:
            raise FollowUpNotFoundError(f"No follow-up found with id {follow_up_id}.")
        return updated

    @staticmethod
    def _ensure_actionable(follow_up: FollowUp) -> None:
        if follow_up.status not in {
            FollowUpStatus.PENDING,
            FollowUpStatus.NOTIFIED,
            FollowUpStatus.SNOOZED,
        }:
            raise FollowUpStatusError(
                f"Follow-up {follow_up.id} cannot be modified from status {follow_up.status}."
            )