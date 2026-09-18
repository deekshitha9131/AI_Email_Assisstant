from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.ai.context.draft_context import DraftContext
from app.ai.schemas.rag import RAGContext, RetrievedChunk
from app.application.services.draft_service import DraftService
from app.domain.entities.draft import Draft
from app.domain.entities.email import Email
from app.domain.entities.email_ai_understanding import EmailAIUnderstanding
from app.domain.entities.user import User
from app.domain.enums.draft_status import DraftStatus
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.ai import AIProviderError, InvalidAIResponseError
from app.domain.exceptions.draft import DraftUnderstandingMissingError, DraftNotFoundError
from app.domain.exceptions.email import EmailNotFoundError


def _user() -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        full_name="Test User",
        google_sub_id="sub-1",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _email(**overrides) -> Email:
    defaults = dict(
        id=uuid4(),
        thread_id=uuid4(),
        user_id=uuid4(),
        gmail_message_id="m1",
        sender="jane@example.com",
        recipients=["bob@example.com"],
        cc=[],
        bcc=[],
        subject="Flight Cancelled",
        snippet="snippet",
        body_text="Your flight has been cancelled.",
        body_html=None,
        received_at=datetime.now(UTC),
        is_read=True,
        is_starred=False,
        has_attachments=False,
        label_ids=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Email(**defaults)


def _stored_understanding(**overrides) -> EmailAIUnderstanding:
    defaults = dict(
        id=uuid4(),
        email_id=uuid4(),
        category="travel",
        intent="cancellation",
        urgency="high",
        sentiment="negative",
        entities=[{"type": "organization", "value": "Airline"}],
        summary="Flight was cancelled.",
        confidence=0.9,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return EmailAIUnderstanding(**defaults)


def _draft(**overrides) -> Draft:
    defaults = dict(
        id=uuid4(),
        email_id=uuid4(),
        body="Generated draft body.",
        status=DraftStatus.GENERATED,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Draft(**defaults)


class FakeEmailService:
    def __init__(self, *, email: Email | None = None, raise_error: Exception | None = None) -> None:
        self._email = email
        self._raise_error = raise_error
        self.get_email_calls: list[tuple] = []

    async def get_email(self, user, email_id):
        self.get_email_calls.append((user.id, email_id))
        if self._raise_error is not None:
            raise self._raise_error
        return self._email


class FakeUnderstandingRepository:
    def __init__(self, *, understanding: EmailAIUnderstanding | None = None) -> None:
        self._understanding = understanding
        self.get_by_email_id_calls: list = []

    async def get_by_email_id(self, email_id):
        self.get_by_email_id_calls.append(email_id)
        return self._understanding


class FakeRetrievalService:
    def __init__(self, *, chunks: list[RetrievedChunk] | None = None) -> None:
        self._chunks = chunks or []
        self.retrieve_calls: list[dict] = []

    async def retrieve_relevant_chunks(self, user, *, query, top_k=5):
        self.retrieve_calls.append({"user_id": user.id, "query": query})
        return self._chunks


class FakeRAGContextBuilder:
    def __init__(self, *, result: RAGContext | None = None) -> None:
        self._result = result or RAGContext()
        self.build_context_calls: list = []

    def build_context(self, retrieved_chunks):
        self.build_context_calls.append(retrieved_chunks)
        return self._result


class FakeDraftContextBuilder:
    def __init__(self) -> None:
        self.build_context_calls: list[dict] = []

    def build_context(self, *, email, understanding, retrieved_context=None, instructions=None):
        self.build_context_calls.append(
            {
                "email": email,
                "understanding": understanding,
                "retrieved_context": retrieved_context,
                "instructions": instructions,
            }
        )
        return DraftContext(
            email=email,
            understanding=understanding,
            retrieved_context=retrieved_context or RAGContext(),
            instructions=instructions,
        )


class FakeDraftGenerator:
    def __init__(self, *, text: str = "Generated draft body.", raise_error: Exception | None = None) -> None:
        self._text = text
        self._raise_error = raise_error
        self.generate_calls: list = []

    async def generate(self, context):
        self.generate_calls.append(context)
        if self._raise_error is not None:
            raise self._raise_error
        return self._text


class FakeDraftRepository:
    def __init__(self, *, draft: Draft | None = None, owner_user_id: UUID | None = None) -> None:
        self._draft = draft
        self._owner_user_id = owner_user_id
        self.create_calls: list[dict] = []
        self.update_body_calls: list[tuple] = []
        self.update_status_calls: list[tuple] = []
        self.get_by_id_for_user_calls: list[tuple] = []
        self.get_by_id_calls: list = []
        self.get_by_email_id_calls: list[UUID] = []

    async def create(self, *, email_id, body, status=DraftStatus.GENERATED):
        self.create_calls.append({"email_id": email_id, "body": body, "status": status})
        return self._draft or _draft(email_id=email_id, body=body)

    async def update_body(self, draft_id, body):
        self.update_body_calls.append((draft_id, body))
        return self._draft or _draft(body=body)

    async def get_by_email_id(self, email_id: UUID) -> Draft | None:
        self.get_by_email_id_calls.append(email_id)
        if self._draft and self._draft.email_id == email_id:
            return self._draft
        return None

    async def update_status(self, draft_id, status):
        self.update_status_calls.append((draft_id, status))
        return self._draft or _draft(status=status)

    async def get_by_id_for_user(self, draft_id: UUID, user_id: UUID) -> Draft | None:
        self.get_by_id_for_user_calls.append((draft_id, user_id))
        if self._draft and self._draft.id == draft_id and self._owner_user_id == user_id:
            return self._draft
        return None

    async def get_by_id(self, draft_id: UUID) -> Draft | None:
        self.get_by_id_calls.append(draft_id)
        return self._draft if self._draft and self._draft.id == draft_id else None


def _make_service(
    *,
    email_service=None,
    understanding_repository=None,
    retrieval_service=None,
    rag_context_builder=None,
    draft_context_builder=None,
    draft_generator=None,
    draft_repository=None,
) -> DraftService:
    return DraftService(
        email_service=email_service or FakeEmailService(email=_email()),
        understanding_repository=understanding_repository
        or FakeUnderstandingRepository(understanding=_stored_understanding()),
        retrieval_service=retrieval_service or FakeRetrievalService(),
        rag_context_builder=rag_context_builder or FakeRAGContextBuilder(),
        draft_context_builder=draft_context_builder or FakeDraftContextBuilder(),
        draft_generator=draft_generator or FakeDraftGenerator(),
        draft_repository=draft_repository or FakeDraftRepository(),
    )


async def test_create_draft_returns_persisted_draft() -> None:
    user = _user()
    expected_draft = _draft(body="Final generated text.")
    service = _make_service(
        draft_generator=FakeDraftGenerator(text="Final generated text."),
        draft_repository=FakeDraftRepository(draft=expected_draft),
    )

    result = await service.create_draft(user, uuid4())

    assert result is expected_draft


async def test_create_draft_looks_up_the_requested_email() -> None:
    user = _user()
    email_id = uuid4()
    email_service = FakeEmailService(email=_email())
    service = _make_service(email_service=email_service)

    await service.create_draft(user, email_id)

    assert email_service.get_email_calls == [(user.id, email_id)]


async def test_create_draft_passes_the_authenticated_user_to_lookups() -> None:
    user = _user()
    email_service = FakeEmailService(email=_email())
    retrieval_service = FakeRetrievalService()
    service = _make_service(email_service=email_service, retrieval_service=retrieval_service)

    await service.create_draft(user, uuid4())

    assert email_service.get_email_calls[0][0] == user.id
    assert retrieval_service.retrieve_calls[0]["user_id"] == user.id

async def test_create_draft_invokes_rag_context_builder_with_retrieved_chunks() -> None:
    user = _user()
    chunks = [
        RetrievedChunk(
            email_id=uuid4(),
            thread_id=uuid4(),
            chunk_index=0,
            content="relevant",
            received_at=datetime.now(UTC),
            similarity=0.9,
        )
    ]
    retrieval_service = FakeRetrievalService(chunks=chunks)
    rag_context_builder = FakeRAGContextBuilder()
    service = _make_service(retrieval_service=retrieval_service, rag_context_builder=rag_context_builder)

    await service.create_draft(user, uuid4())

    assert rag_context_builder.build_context_calls == [chunks]


async def test_create_draft_invokes_draft_context_builder_with_email_and_understanding() -> None:
    user = _user()
    email = _email(subject="Distinctive Subject")
    understanding = _stored_understanding(summary="Distinctive summary.")
    draft_context_builder = FakeDraftContextBuilder()
    service = _make_service(
        email_service=FakeEmailService(email=email),
        understanding_repository=FakeUnderstandingRepository(understanding=understanding),
        draft_context_builder=draft_context_builder,
    )

    await service.create_draft(user, uuid4())

    call = draft_context_builder.build_context_calls[0]
    assert call["email"] is email
    assert call["understanding"].summary == "Distinctive summary."


async def test_create_draft_passes_instructions_through_to_context_builder() -> None:
    user = _user()
    draft_context_builder = FakeDraftContextBuilder()
    service = _make_service(draft_context_builder=draft_context_builder)

    await service.create_draft(user, uuid4(), instructions="Keep it brief.")

    assert draft_context_builder.build_context_calls[0]["instructions"] == "Keep it brief."

async def test_create_draft_invokes_generator_with_the_built_draft_context() -> None:
    user = _user()
    draft_generator = FakeDraftGenerator()
    service = _make_service(draft_generator=draft_generator)

    await service.create_draft(user, uuid4())

    assert len(draft_generator.generate_calls) == 1
    assert isinstance(draft_generator.generate_calls[0], DraftContext)

async def test_generated_text_is_passed_to_draft_repository() -> None:
    user = _user()
    email = _email()
    draft_generator = FakeDraftGenerator(text="Exact generated text to persist.")
    draft_repository = FakeDraftRepository()
    service = _make_service(
        email_service=FakeEmailService(email=email),
        draft_generator=draft_generator,
        draft_repository=draft_repository,
    )

    await service.create_draft(user, uuid4())

    assert len(draft_repository.create_calls) == 1
    call = draft_repository.create_calls[0]
    assert call["email_id"] == email.id
    assert call["body"] == "Exact generated text to persist."


async def test_returned_draft_is_exactly_what_repository_returned() -> None:
    user = _user()
    expected_draft = _draft()
    service = _make_service(draft_repository=FakeDraftRepository(draft=expected_draft))

    result = await service.create_draft(user, uuid4())

    assert result is expected_draft

async def test_missing_email_raises_email_not_found_error() -> None:
    user = _user()
    email_service = FakeEmailService(raise_error=EmailNotFoundError("No email found."))
    draft_generator = FakeDraftGenerator()
    draft_repository = FakeDraftRepository()
    service = _make_service(
        email_service=email_service, draft_generator=draft_generator, draft_repository=draft_repository
    )

    with pytest.raises(EmailNotFoundError):
        await service.create_draft(user, uuid4())

    # No downstream component was ever reached.
    assert draft_generator.generate_calls == []
    assert draft_repository.create_calls == []


async def test_missing_understanding_raises_and_does_not_persist() -> None:
    user = _user()
    understanding_repository = FakeUnderstandingRepository(understanding=None)
    draft_generator = FakeDraftGenerator()
    draft_repository = FakeDraftRepository()
    service = _make_service(
        understanding_repository=understanding_repository,
        draft_generator=draft_generator,
        draft_repository=draft_repository,
    )

    with pytest.raises(DraftUnderstandingMissingError):
        await service.create_draft(user, uuid4())

    assert draft_generator.generate_calls == []
    assert draft_repository.create_calls == []


async def test_generator_failure_prevents_persistence() -> None:
    user = _user()
    draft_generator = FakeDraftGenerator(raise_error=AIProviderError("LLM call failed."))
    draft_repository = FakeDraftRepository()
    service = _make_service(draft_generator=draft_generator, draft_repository=draft_repository)

    with pytest.raises(AIProviderError):
        await service.create_draft(user, uuid4())

    assert draft_repository.create_calls == []


async def test_generator_invalid_response_prevents_persistence() -> None:
    user = _user()
    draft_generator = FakeDraftGenerator(raise_error=InvalidAIResponseError("empty response"))
    draft_repository = FakeDraftRepository()
    service = _make_service(draft_generator=draft_generator, draft_repository=draft_repository)

    with pytest.raises(InvalidAIResponseError):
        await service.create_draft(user, uuid4())

    assert draft_repository.create_calls == []

async def test_draft_repository_failure_propagates() -> None:
    user = _user()

    class FailingDraftRepository:
        async def get_by_email_id(self, email_id):
            return None

        async def create(self, *, email_id, body, status=DraftStatus.GENERATED):
            raise RuntimeError("database write failed")

    service = _make_service(draft_repository=FailingDraftRepository())

    with pytest.raises(RuntimeError, match="database write failed"):
        await service.create_draft(user, uuid4())

async def test_user_isolation_relies_on_email_service_ownership_check() -> None:
    other_users_email_id = uuid4()
    user = _user()
    email_service = FakeEmailService(raise_error=EmailNotFoundError("No email found."))
    service = _make_service(email_service=email_service)

    with pytest.raises(EmailNotFoundError):
        await service.create_draft(user, other_users_email_id)

    assert email_service.get_email_calls == [(user.id, other_users_email_id)]


async def test_update_draft_calls_repository_and_returns_updated_draft() -> None:
    user = _user()
    draft_id = uuid4()
    updated_draft = _draft(id=draft_id, body="Updated body.")
    service = _make_service(
        draft_repository=FakeDraftRepository(draft=updated_draft, owner_user_id=user.id),
    )

    result = await service.update_draft(user, draft_id, "Updated body.")

    assert result is updated_draft
    assert service._draft_repository.update_body_calls == [(draft_id, "Updated body.")]
    assert service._draft_repository.get_by_id_for_user_calls == [(draft_id, user.id)]


async def test_update_draft_raises_when_draft_not_found() -> None:
    user = _user()
    draft_id = uuid4()
    service = _make_service(
        draft_repository=FakeDraftRepository(draft=None),
    )

    with pytest.raises(DraftNotFoundError):
        await service.update_draft(user, draft_id, "Any body.")

    assert service._draft_repository.update_body_calls == []
    assert service._draft_repository.get_by_id_for_user_calls == [(draft_id, user.id)]


async def test_update_draft_raises_when_unauthorized() -> None:
    user = _user()
    other_user = _user()
    draft_id = uuid4()
    # The draft belongs to other_user
    service = _make_service(
        draft_repository=FakeDraftRepository(draft=_draft(id=draft_id), owner_user_id=other_user.id),
    )

    with pytest.raises(DraftNotFoundError):
        await service.update_draft(user, draft_id, "Any body.")

    assert service._draft_repository.update_body_calls == []
    assert service._draft_repository.get_by_id_for_user_calls == [(draft_id, user.id)]


async def test_approve_draft_calls_repository_and_returns_approved_draft() -> None:
    user = _user()
    draft_id = uuid4()
    approved_draft = _draft(id=draft_id, status=DraftStatus.APPROVED)
    service = _make_service(
        draft_repository=FakeDraftRepository(draft=approved_draft, owner_user_id=user.id),
    )

    result = await service.approve_draft(user, draft_id)

    assert result is approved_draft
    assert service._draft_repository.update_status_calls == [(draft_id, DraftStatus.APPROVED)]
    assert service._draft_repository.get_by_id_for_user_calls == [(draft_id, user.id)]


async def test_approve_draft_raises_when_draft_not_found() -> None:
    user = _user()
    draft_id = uuid4()
    service = _make_service(
        draft_repository=FakeDraftRepository(draft=None),
    )

    with pytest.raises(DraftNotFoundError):
        await service.approve_draft(user, draft_id)

    assert service._draft_repository.update_status_calls == []
    assert service._draft_repository.get_by_id_for_user_calls == [(draft_id, user.id)]


async def test_approve_draft_raises_when_unauthorized() -> None:
    user = _user()
    other_user = _user()
    draft_id = uuid4()
    # The draft belongs to other_user
    service = _make_service(
        draft_repository=FakeDraftRepository(draft=_draft(id=draft_id), owner_user_id=other_user.id),
    )

    with pytest.raises(DraftNotFoundError):
        await service.approve_draft(user, draft_id)

    assert service._draft_repository.update_status_calls == []
    assert service._draft_repository.get_by_id_for_user_calls == [(draft_id, user.id)]