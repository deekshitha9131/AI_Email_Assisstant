"""Analysis background tasks.

Tasks for generating AI understanding (classification, intent, urgency, etc.)
for emails, offloaded from the Gmail sync pipeline to avoid blocking the
user-facing sync operation.
"""

from typing import cast

import structlog

from app.ai.preprocessing.email_preprocessor import EmailPreprocessor
from app.ai.services.understanding_service import AIUnderstandingService
from app.ai.providers.llm_provider import LLMProvider
from app.core.celery_app import celery_app
from app.workers import worker_state
from app.workers.base import DEFAULT_TASK_RETRY_KWARGS, BaseTask
from app.infrastructure.database.repositories.email_ai_understanding_repository import (
    EmailAIUnderstandingRepository,
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


async def _analyze_email(email_id: str) -> None:
    """Analyze a single email by ID, persisting the result.

    This function is designed to be called via the async bridge in a
    Celery task. It opens a database session, fetches the email, runs the
    understanding pipeline (preprocessing, LLM understanding), and
    persists the result.
    """
    async with worker_state.get_session_factory()() as session:
        email = await _get_email_by_id(session, email_id)
        if email is None:
            logger.warning("email_not_found_for_analysis", email_id=email_id)
            return

        # Convert SQLAlchemy model to domain entity ( Email ) for the
        # understanding pipeline. We only need the fields used by the pipeline.
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

        # Instantiate the understanding service dependencies.
        preprocessor = EmailPreprocessor()
        llm_provider = LLMProvider()
        understanding_service = AIUnderstandingService(
            preprocessor=preprocessor,
            llm_provider=llm_provider,
        )
        understanding_repository = EmailAIUnderstandingRepository(session)

        # Check if analysis already exists (idempotency)
        existing = await understanding_repository.get_by_email_id(domain_email.id)
        if existing is not None:
            logger.info(
                "analysis_already_exists", email_id=email_id, understanding_id=existing.id
            )
            return

        # Run the analysis
        result = await understanding_service.analyze_email(domain_email)

        # Persist the result
        await understanding_repository.upsert(domain_email.id, result)

        logger.info(
            "analysis_completed_and_persisted",
            email_id=email_id,
            understanding_id=result.id if hasattr(result, 'id') else None,
        )


# Celery's task decorator is unstubbed, hence the ignore below.
@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.workers.classification_tasks.analyze_email_task",
    base=BaseTask,
    bind=True,
    **DEFAULT_TASK_RETRY_KWARGS,
)
def analyze_email_task(self: BaseTask, email_id: str) -> dict[str, str]:
    """Analyze an email in the background.

    Args:
        email_id: The UUID of the email to analyze, as a string.

    Returns:
        A dictionary with the status (e.g., "skipped" or "completed").
    """
    logger.info("analysis_task_started", email_id=email_id, task_id=self.request.id)

    # Run the async function and wait for it
    self.run_async(_analyze_email(email_id))

    logger.info(
        "analysis_task_completed",
        email_id=email_id,
        task_id=self.request.id,
    )
    return {"status": "completed"}
