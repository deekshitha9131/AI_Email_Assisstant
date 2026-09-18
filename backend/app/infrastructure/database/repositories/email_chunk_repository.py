from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.email_chunk import EmailChunkRecord
from app.infrastructure.database.models.email_chunk import EmailChunkModel


def _to_entity(model: EmailChunkModel) -> EmailChunkRecord:
    return EmailChunkRecord(
        id=model.id,
        email_id=model.email_id,
        thread_id=model.thread_id,
        user_id=model.user_id,
        chunk_index=model.chunk_index,
        content=model.content,
        embedding=list(model.embedding),
        received_at=model.received_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@dataclass
class ChunkWithEmbedding:
    chunk_index: int
    content: str
    embedding: list[float]


@dataclass
class SimilarChunk:

    email_id: UUID
    thread_id: UUID
    chunk_index: int
    content: str
    received_at: datetime
    distance: float


class EmailChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email_id(self, email_id: UUID) -> list[EmailChunkRecord]:
        """Return every stored chunk for one email, in chunk_index order."""
        stmt = (
            select(EmailChunkModel)
            .where(EmailChunkModel.email_id == email_id)
            .order_by(EmailChunkModel.chunk_index.asc())
        )
        result = await self._session.execute(stmt)
        return [_to_entity(model) for model in result.scalars().all()]

    async def replace_chunks_for_email(
        self,
        *,
        email_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        received_at: datetime,
        chunks: list[ChunkWithEmbedding],
    ) -> list[EmailChunkRecord]:
        await self._session.execute(
            delete(EmailChunkModel).where(EmailChunkModel.email_id == email_id)
        )

        models = [
            EmailChunkModel(
                email_id=email_id,
                thread_id=thread_id,
                user_id=user_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                received_at=received_at,
                embedding=chunk.embedding,
            )
            for chunk in chunks
        ]
        self._session.add_all(models)
        await self._session.commit()

        for model in models:
            await self._session.refresh(model)
        return [_to_entity(model) for model in models]

    async def similarity_search(
        self, *, user_id: UUID, query_embedding: list[float], top_k: int
    ) -> list[SimilarChunk]:
        distance = EmailChunkModel.embedding.cosine_distance(query_embedding)
        stmt = (
            select(
                EmailChunkModel.email_id,
                EmailChunkModel.thread_id,
                EmailChunkModel.chunk_index,
                EmailChunkModel.content,
                EmailChunkModel.received_at,
                distance.label("distance"),
            )
            .where(EmailChunkModel.user_id == user_id)
            .where(EmailChunkModel.embedding.isnot(None))
            .order_by(distance.asc())
            .limit(top_k)
        )
        result = await self._session.execute(stmt)
        return [
            SimilarChunk(
                email_id=row.email_id,
                thread_id=row.thread_id,
                chunk_index=row.chunk_index,
                content=row.content,
                received_at=row.received_at,
                distance=float(row.distance),
            )
            for row in result.all()
        ]
