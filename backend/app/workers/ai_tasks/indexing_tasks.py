"""Indexing background tasks.

Tasks for generating embeddings and storing chunks for emails, offloaded
from the Gmail sync pipeline to avoid blocking the user-facing sync
operation.
"""

from typing import cast

import structlog

from app.ai.chunker import EmailChunker
from app.ai.preprocessing.email_preprocessor import EmailPreprocessor
from app.ai.rag.embedding import EmbeddingService
from app.core.celery_app import celery_app
from app.workers import worker_state
from app.workers.base import DEFAULT_TASK_RETRY_KWARGS, BaseTask
from app.infrastructure.database.repositories.email_chunk_repository import (
    EmailChunkRepository,
)
from app.infrastructure.database.models.email import EmailModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


logger = structlog.get_logger(__name__)


async def _get_email_by_id(session: AsyncSession, email_id: str) -> EmailModel | None:
    """Fetch an email by its ID, returning the SQLAlchemy model."""
    stmt = select(EmailModel).where(EmailModel.id == email_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _index_email(email_id: str) -> int:
    """Index a single email by ID, returning the number of chunks stored.

    This function is designed to be called via the async bridge in a
    Celery task. It opens a database session, fetches the email, and
    runs the indexing pipeline (preprocessing, chunking, embedding,
    storage).
    """
    async with worker_state.get_session_factory()() as session:
        email = await _get_email_by_id(session, email_id)
        if email is None:
            logger.warning("email_not_found_for_indexing", email_id=email_id)
            return 0

        # Convert SQLAlchemy model to domain entity ( Email ) for the
        # indexing pipeline. We only need the fields used by the pipeline.
        from app.domain.entities.email import Email as DomainEmail

        domain_email = DomainEmail(
            id=email.id,
            thread_id=email.thread_id,
            user_id=email.user_id,
            gmail_message_id=email.gmail_message_id,
            sender=email.sender,
            recipients=list(email.recipients),
            cc=list(email.cc),
            bcc=list(email.bcc),
            subject=email.subject,
            snippet=email.snippet,
            body_text=email.body_text,
            body_html=email.body_html,
            received_at=email.received_at,
            is_read=email.is_read,
            is_starred=email.is_starred,
            has_attachments=email.has_attachments,
            label_ids=list(email.label_ids),
        )

        # Instantiate the indexing service dependencies.
        preprocessor = EmailPreprocessor()
        chunker = EmailChunker()
        embedding_service = EmbeddingService()
        chunk_repository = EmailChunkRepository(session)

        # Note: The EmailIndexingService expects the chunk_repository to be
        # bound to a session. We are passing the same session we opened
        # above, which is fine because the service will not commit or
        # close the session; that is the caller's responsibility.
        from app.ai.rag.indexing_service import EmailIndexingService

        indexing_service = EmailIndexingService(
            preprocessor=preprocessor,
            chunker=chunker,
            embedding_service=embedding_service,
            chunk_repository=chunk_repository,
        )

        return await indexing_service.index_email(domain_email)


# Celery's task decorator is unstubbed, hence the ignore below.
@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.workers.ai_tasks.index_email_task",
    base=BaseTask,
    bind=True,
    **DEFAULT_TASK_RETRY_KWARGS,
)
def index_email_task(self: BaseTask, email_id: str) -> dict[str, int]:
    """Index an email in the background.

    Args:
        email_id: The UUID of the email to index, as a string.

    Returns:
        A dictionary with the key "chunks_stored" indicating how many
        text chunks were generated and stored for the email.
    """
    logger.info("indexing_task_started", email_id=email_id, task_id=self.request.id)

    chunks_stored = self.run_async(_index_email(email_id))

    logger.info(
        "indexing_task_completed",
        email_id=email_id,
        chunks_stored=chunks_stored,
        task_id=self.request.id,
    )
    return {"chunks_stored": chunks_stored}
