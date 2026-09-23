from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.follow_up import FollowUp
from app.domain.enums.follow_up_source import FollowUpSource
from app.domain.enums.follow_up_status import FollowUpStatus
from app.domain.exceptions.follow_up import ActiveFollowUpExistsError
from app.infrastructure.database.models.follow_up import FollowUpModel


def _to_entity(model: FollowUpModel) -> FollowUp:
    return FollowUp(
        id=model.id,
        user_id=model.user_id,
        email_id=model.email_id,
        thread_id=model.thread_id,
        due_at=model.due_at,
        status=model.status,
        reason=model.reason,
        source=model.source,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
        dismissed_at=model.dismissed_at,
    )


class FollowUpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: UUID,
        email_id: UUID,
        thread_id: UUID,
        due_at: datetime,
        reason: str | None,
        source: FollowUpSource,
        status: FollowUpStatus = FollowUpStatus.PENDING,
    ) -> FollowUp:
        model = FollowUpModel(
            user_id=user_id,
            email_id=email_id,
            thread_id=thread_id,
            due_at=due_at,
            status=status,
            reason=reason,
            source=source,
        )
        self._session.add(model)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ActiveFollowUpExistsError(
                f"An active follow-up already exists for email {email_id} or thread {thread_id}."
            ) from exc
        await self._session.refresh(model)
        return _to_entity(model)

    async def get_by_id_for_user(self, follow_up_id: UUID, user_id: UUID) -> FollowUp | None:
        statement = select(FollowUpModel).where(
            FollowUpModel.id == follow_up_id,
            FollowUpModel.user_id == user_id,
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def list_by_user(self, user_id: UUID) -> list[FollowUp]:
        statement = (
            select(FollowUpModel)
            .where(FollowUpModel.user_id == user_id)
            .order_by(FollowUpModel.due_at.asc())
        )
        result = await self._session.execute(statement)
        return [_to_entity(model) for model in result.scalars().all()]

    async def list_due_for_user(
        self, user_id: UUID, *, due_at: datetime, limit: int
    ) -> list[FollowUp]:
        statement = (
            select(FollowUpModel)
            .where(
                FollowUpModel.user_id == user_id,
                FollowUpModel.due_at <= due_at,
                FollowUpModel.status.in_((FollowUpStatus.PENDING, FollowUpStatus.SNOOZED)),
            )
            .order_by(FollowUpModel.due_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [_to_entity(model) for model in result.scalars().all()]

    async def update_status_for_user(
        self,
        follow_up_id: UUID,
        user_id: UUID,
        *,
        status: FollowUpStatus,
        due_at: datetime | None = None,
        completed_at: datetime | None = None,
        dismissed_at: datetime | None = None,
    ) -> FollowUp | None:
        statement = select(FollowUpModel).where(
            FollowUpModel.id == follow_up_id,
            FollowUpModel.user_id == user_id,
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        model.status = status
        if due_at is not None:
            model.due_at = due_at
        model.completed_at = completed_at
        model.dismissed_at = dismissed_at
        await self._session.commit()
        await self._session.refresh(model)
        return _to_entity(model)

    async def mark_notified_for_user(
        self, follow_up_id: UUID, user_id: UUID
    ) -> FollowUp | None:
        statement = (
            update(FollowUpModel)
            .where(
                FollowUpModel.id == follow_up_id,
                FollowUpModel.user_id == user_id,
                FollowUpModel.status.in_((FollowUpStatus.PENDING, FollowUpStatus.SNOOZED)),
            )
            .values(status=FollowUpStatus.NOTIFIED)
            .returning(FollowUpModel)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        await self._session.commit()
        return _to_entity(model) if model is not None else None