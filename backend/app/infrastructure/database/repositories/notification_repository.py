from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.notification import Notification
from app.infrastructure.database.models.notification import NotificationModel


def _to_entity(model: NotificationModel) -> Notification:
    return Notification(
        id=model.id,
        user_id=model.user_id,
        email_id=model.email_id,
        follow_up_id=model.follow_up_id,
        notification_type=model.notification_type,
        title=model.title,
        message=model.message,
        is_read=model.is_read,
        created_at=model.created_at,
    )


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(
        self,
        *,
        user_id: UUID,
        email_id: UUID,
        notification_type: str,
        title: str,
        message: str,
        follow_up_id: UUID | None = None,
    ) -> tuple[Notification, bool]:
        statement = (
            insert(NotificationModel)
            .values(
                user_id=user_id,
                email_id=email_id,
                notification_type=notification_type,
                title=title,
                follow_up_id=follow_up_id,
                message=message,
            )
            .on_conflict_do_nothing(
                index_elements=(
                    ["user_id", "follow_up_id", "notification_type"]
                    if follow_up_id is not None
                    else ["user_id", "email_id", "notification_type"]
                ),
                index_where=(
                    NotificationModel.follow_up_id.is_not(None)
                    if follow_up_id is not None
                    else NotificationModel.follow_up_id.is_(None)
                ),
            )
            .returning(NotificationModel)
        )
        result = await self._session.execute(statement)
        row = result.first()
        if row is not None:
            model = row[0]
            await self._session.commit()
            return _to_entity(model), True

        if follow_up_id is not None:
            statement = select(NotificationModel).where(
                NotificationModel.user_id == user_id,
                NotificationModel.follow_up_id == follow_up_id,
                NotificationModel.notification_type == notification_type,
            )
        else:
            statement = select(NotificationModel).where(
                NotificationModel.user_id == user_id,
                NotificationModel.email_id == email_id,
                NotificationModel.notification_type == notification_type,
                NotificationModel.follow_up_id.is_(None),
            )

        result = await self._session.execute(statement)
        existing = result.scalar_one_or_none()
        if existing is None:
            raise LookupError("Notification was not found after insert conflict.")
        return _to_entity(existing), False

    async def list_by_user(self, user_id: UUID) -> list[Notification]:
        statement = (
            select(NotificationModel)
            .where(NotificationModel.user_id == user_id)
            .order_by(NotificationModel.created_at.desc())
        )
        result = await self._session.execute(statement)
        return [_to_entity(model) for model in result.scalars().all()]

    async def count_unread_by_user(self, user_id: UUID) -> int:
        statement = select(func.count()).select_from(NotificationModel).where(
            NotificationModel.user_id == user_id,
            NotificationModel.is_read.is_(False),
        )
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def mark_as_read_for_user(self, notification_id: UUID, user_id: UUID) -> Notification | None:
        statement = select(NotificationModel).where(
            NotificationModel.id == notification_id,
            NotificationModel.user_id == user_id,
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        if not model.is_read:
            model.is_read = True
            await self._session.commit()
            await self._session.refresh(model)
        return _to_entity(model)
