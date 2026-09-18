from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.compose_draft import ComposeDraft
from app.infrastructure.database.models.compose_draft import ComposeDraftModel


def _to_entity(model: ComposeDraftModel) -> ComposeDraft:
    return ComposeDraft(
        id=model.id,
        user_id=model.user_id,
        recipients=list(model.recipients),
        cc=list(model.cc),
        bcc=list(model.bcc),
        subject=model.subject,
        body_text=model.body_text,
        body_html=model.body_html,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class ComposeDraftRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: UUID,
        recipients: list[str],
        cc: list[str],
        bcc: list[str],
        subject: str,
        body_text: str | None,
        body_html: str | None,
    ) -> ComposeDraft:
        model = ComposeDraftModel(
            user_id=user_id,
            recipients=recipients,
            cc=cc,
            bcc=bcc,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return _to_entity(model)

    async def get_by_id_for_user(self, draft_id: UUID, user_id: UUID) -> ComposeDraft | None:
        stmt = select(ComposeDraftModel).where(
            ComposeDraftModel.id == draft_id,
            ComposeDraftModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def list_by_user(self, user_id: UUID, *, page: int = 1, page_size: int = 25) -> list[ComposeDraft]:
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be positive")
        stmt = (
            select(ComposeDraftModel)
            .where(ComposeDraftModel.user_id == user_id)
            .order_by(ComposeDraftModel.updated_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        result = await self._session.execute(stmt)
        return [_to_entity(model) for model in result.scalars().all()]

    async def update_for_user(
        self,
        draft_id: UUID,
        user_id: UUID,
        *,
        recipients: list[str],
        cc: list[str],
        bcc: list[str],
        subject: str,
        body_text: str | None,
        body_html: str | None,
    ) -> ComposeDraft | None:
        stmt = select(ComposeDraftModel).where(
            ComposeDraftModel.id == draft_id,
            ComposeDraftModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        model.recipients = recipients
        model.cc = cc
        model.bcc = bcc
        model.subject = subject
        model.body_text = body_text
        model.body_html = body_html
        await self._session.commit()
        await self._session.refresh(model)
        return _to_entity(model)

    async def delete_for_user(self, draft_id: UUID, user_id: UUID) -> bool:
        stmt = select(ComposeDraftModel).where(
            ComposeDraftModel.id == draft_id,
            ComposeDraftModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return False
        await self._session.delete(model)
        await self._session.commit()
        return True