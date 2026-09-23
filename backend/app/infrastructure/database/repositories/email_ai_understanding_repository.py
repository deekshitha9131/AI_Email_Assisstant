from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas.ai_understanding import AIUnderstandingResult
from app.domain.entities.email_ai_understanding import EmailAIUnderstanding
from app.infrastructure.database.models.email import EmailModel
from app.infrastructure.database.models.email_ai_understanding import EmailAIUnderstandingModel


def _to_entity(model: EmailAIUnderstandingModel) -> EmailAIUnderstanding:
    return EmailAIUnderstanding(
        id=model.id,
        email_id=model.email_id,
        category=model.category,
        intent=model.intent,
        urgency=model.urgency,
        sentiment=model.sentiment,
        entities=list(model.entities),
        summary=model.summary,
        confidence=model.confidence,
        follow_up_needed=model.follow_up_needed,
        follow_up_date=model.follow_up_date,
        follow_up_reason=model.follow_up_reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class EmailAIUnderstandingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email_id(self, email_id: UUID) -> EmailAIUnderstanding | None:
        stmt = select(EmailAIUnderstandingModel).where(
            EmailAIUnderstandingModel.email_id == email_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def list_unprocessed_email_ids(
        self, user_id: UUID, *, limit: int, offset: int
    ) -> list[UUID]:
        stmt = (
            select(EmailModel.id)
            .outerjoin(
                EmailAIUnderstandingModel,
                EmailAIUnderstandingModel.email_id == EmailModel.id,
            )
            .where(
                EmailModel.user_id == user_id,
                EmailAIUnderstandingModel.email_id.is_(None),
            )
            .order_by(EmailModel.received_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(self, email_id: UUID, result: AIUnderstandingResult) -> EmailAIUnderstanding:
        stmt = select(EmailAIUnderstandingModel).where(
            EmailAIUnderstandingModel.email_id == email_id
        )
        query_result = await self._session.execute(stmt)
        model = query_result.scalar_one_or_none()

        entities_payload = [entity.model_dump() for entity in result.entities]

        if model is None:
            model = EmailAIUnderstandingModel(
                email_id=email_id,
                category=result.category.value,
                intent=result.intent.value,
                urgency=result.urgency.value,
                sentiment=result.sentiment.value,
                entities=entities_payload,
                summary=result.summary,
                confidence=result.confidence,
                follow_up_needed=result.follow_up_needed,
                follow_up_date=result.follow_up_date,
                follow_up_reason=result.follow_up_reason,
            )
            self._session.add(model)
        else:
            model.category = result.category.value
            model.intent = result.intent.value
            model.urgency = result.urgency.value
            model.sentiment = result.sentiment.value
            model.entities = entities_payload
            model.summary = result.summary
            model.confidence = result.confidence
            model.follow_up_needed = result.follow_up_needed
            model.follow_up_date = result.follow_up_date
            model.follow_up_reason = result.follow_up_reason

        await self._session.commit()
        await self._session.refresh(model)
        return _to_entity(model)
