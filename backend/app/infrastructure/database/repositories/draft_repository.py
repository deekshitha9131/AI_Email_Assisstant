"""Draft repository — concrete SQLAlchemy implementation.

Implements IDraftRepository. Same simplification note as every other
repository in this project: no Unit of Work yet, so this commits its
own change directly rather than leaving the transaction boundary to a
caller.

Ownership-scoped methods (get_by_id_for_user, list_by_user,
count_by_user) join to EmailModel and filter by EmailModel.user_id
directly in the SQL WHERE clause — never fetch-then-filter in Python —
since a draft has no user_id column of its own; ownership is only
reachable through its parent email.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.draft import Draft
from app.domain.enums.draft_status import DraftStatus
from app.domain.exceptions.draft import DraftNotFoundError
from app.infrastructure.database.models.draft import DraftModel
from app.infrastructure.database.models.email import EmailModel


def _to_entity(model: DraftModel) -> Draft:
    return Draft(
        id=model.id,
        email_id=model.email_id,
        body=model.body,
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class DraftRepository:
    """See IDraftRepository for the contract this class implements."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_model_or_raise(self, draft_id: UUID) -> DraftModel:
        stmt = select(DraftModel).where(DraftModel.id == draft_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise DraftNotFoundError(f"No draft found with id {draft_id}.")
        return model

    async def create(
        self, *, email_id: UUID, body: str, status: DraftStatus = DraftStatus.GENERATED
    ) -> Draft:
        model = DraftModel(email_id=email_id, body=body, status=status)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return _to_entity(model)

    async def get_by_id(self, draft_id: UUID) -> Draft | None:
        stmt = select(DraftModel).where(DraftModel.id == draft_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def get_by_email_id(self, email_id: UUID) -> Draft | None:
        stmt = (
            select(DraftModel)
            .where(DraftModel.email_id == email_id)
            .order_by(DraftModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        model = result.scalars().first()
        return _to_entity(model) if model is not None else None

    async def get_by_id_for_user(self, draft_id: UUID, user_id: UUID) -> Draft | None:
        stmt = (
            select(DraftModel)
            .join(EmailModel, DraftModel.email_id == EmailModel.id)
            .where(DraftModel.id == draft_id, EmailModel.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        page: int = 1,
        page_size: int = 25,
        status: DraftStatus | None = None,
    ) -> list[Draft]:
        if page < 1:
            raise ValueError(f"page must be >= 1, got {page}")
        if page_size < 1:
            raise ValueError(f"page_size must be >= 1, got {page_size}")

        stmt = (
            select(DraftModel)
            .join(EmailModel, DraftModel.email_id == EmailModel.id)
            .where(EmailModel.user_id == user_id)
            .order_by(DraftModel.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        if status is not None:
            stmt = stmt.where(DraftModel.status == status)
        result = await self._session.execute(stmt)
        return [_to_entity(model) for model in result.scalars().all()]

    async def count_by_user(self, user_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(DraftModel)
            .join(EmailModel, DraftModel.email_id == EmailModel.id)
            .where(EmailModel.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def update_status(self, draft_id: UUID, status: DraftStatus) -> Draft:
        model = await self._get_model_or_raise(draft_id)
        model.status = status
        await self._session.commit()
        await self._session.refresh(model)
        return _to_entity(model)

    async def claim_for_approval(self, draft_id: UUID, user_id: UUID) -> Draft | None:
        stmt = (
            select(DraftModel)
            .join(EmailModel, DraftModel.email_id == EmailModel.id)
            .where(
                DraftModel.id == draft_id,
                EmailModel.user_id == user_id,
                DraftModel.status == DraftStatus.GENERATED,
            )
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        model.status = DraftStatus.APPROVED
        await self._session.commit()
        await self._session.refresh(model)
        return _to_entity(model)

    async def update_body(self, draft_id: UUID, body: str) -> Draft:
        model = await self._get_model_or_raise(draft_id)
        model.body = body
        await self._session.commit()
        await self._session.refresh(model)
        return _to_entity(model)