from uuid import UUID

from app.ai.context.draft_context import DraftContextBuilder
from app.ai.rag.context_builder import ContextBuilder as RAGContextBuilder
from app.ai.rag.retrieval import RetrievalService
from app.ai.schemas.ai_understanding import AIUnderstandingResult, Entity
from app.ai.services.draft_generator import DraftGenerator
from app.application.services.email_service import EmailService
from app.domain.entities.draft import Draft
from app.domain.entities.email_ai_understanding import EmailAIUnderstanding
from app.domain.entities.user import User
from app.domain.enums.draft_status import DraftStatus
from app.domain.exceptions.draft import (
    DraftNotFoundError,
    DraftStatusError,
    DraftUnderstandingMissingError,
)
from app.infrastructure.database.repositories.draft_repository import DraftRepository
from app.infrastructure.database.repositories.email_ai_understanding_repository import (
    EmailAIUnderstandingRepository,
)


def _to_ai_understanding_result(stored: EmailAIUnderstanding) -> AIUnderstandingResult:
    return AIUnderstandingResult(
        category=stored.category,
        intent=stored.intent,
        urgency=stored.urgency,
        sentiment=stored.sentiment,
        entities=[Entity(type=e["type"], value=e["value"]) for e in stored.entities],
        summary=stored.summary,
        confidence=stored.confidence,
    )


class DraftService:
    def __init__(
        self,
        *,
        email_service: EmailService,
        understanding_repository: EmailAIUnderstandingRepository,
        retrieval_service: RetrievalService,
        rag_context_builder: RAGContextBuilder,
        draft_context_builder: DraftContextBuilder,
        draft_generator: DraftGenerator,
        draft_repository: DraftRepository,
    ) -> None:
        self._email_service = email_service
        self._understanding_repository = understanding_repository
        self._retrieval_service = retrieval_service
        self._rag_context_builder = rag_context_builder
        self._draft_context_builder = draft_context_builder
        self._draft_generator = draft_generator
        self._draft_repository = draft_repository

    async def create_draft(
        self, user: User, email_id: UUID, *, instructions: str | None = None
    ) -> Draft:
        """Generate and persist a draft reply for `email_id`, enforcing
        that the email belongs to `user`. See Task 7.6 for the full
        rationale of each step; unchanged here.
        """
        email = await self._email_service.get_email(user, email_id)

        stored_understanding = await self._understanding_repository.get_by_email_id(email.id)
        if stored_understanding is None:
            raise DraftUnderstandingMissingError(
                f"Email {email_id} has not been AI-analyzed yet. "
                "Run AI analysis (POST /emails/{email_id}/analyze) before generating a draft."
            )
        understanding = _to_ai_understanding_result(stored_understanding)

        retrieval_query = email.subject or email.snippet or ""
        retrieved_chunks = await self._retrieval_service.retrieve_relevant_chunks(
            user, query=retrieval_query
        )
        rag_context = self._rag_context_builder.build_context(retrieved_chunks)

        draft_context = self._draft_context_builder.build_context(
            email=email,
            understanding=understanding,
            retrieved_context=rag_context,
            instructions=instructions,
        )

        generated_text = await self._draft_generator.generate(draft_context)

        existing_draft = await self._draft_repository.get_by_email_id(email.id)
        if existing_draft is not None:
            return await self._draft_repository.update_body(existing_draft.id, generated_text)
        return await self._draft_repository.create(email_id=email.id, body=generated_text)

    async def get_draft(self, user: User, draft_id: UUID) -> Draft:
        draft = await self._draft_repository.get_by_id_for_user(draft_id, user.id)
        if draft is None:
            raise DraftNotFoundError(f"No draft found with id {draft_id}.")
        return draft

    async def update_draft(self, user: User, draft_id: UUID, body: str) -> Draft:
        """Update the body of a draft, ensuring it belongs to the user."""
        # First, verify ownership and existence via get_draft
        await self.get_draft(user, draft_id)
        # Then update the body
        return await self._draft_repository.update_body(draft_id, body)

    async def approve_draft(self, user: User, draft_id: UUID) -> Draft:
        """Approve a draft, setting its status to APPROVED, ensuring it belongs to the user."""
        # First, verify ownership and existence via get_draft
        await self.get_draft(user, draft_id)
        # Then update the status to APPROVED
        return await self._draft_repository.update_status(draft_id, DraftStatus.APPROVED)