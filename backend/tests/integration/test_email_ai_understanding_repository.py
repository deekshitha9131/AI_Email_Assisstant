import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.ai.schemas.ai_understanding import (
    AIUnderstandingResult,
    EmailCategory,
    EmailIntent,
    EmailSentiment,
    EmailUrgency,
)
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.attachment import AttachmentModel
from app.infrastructure.database.models.email import EmailModel
from app.infrastructure.database.models.email_ai_understanding import EmailAIUnderstandingModel
from app.infrastructure.database.models.thread import ThreadModel
from app.infrastructure.database.models.user import UserModel
from app.infrastructure.database.repositories.email_ai_understanding_repository import (
    EmailAIUnderstandingRepository,
)

pytestmark = pytest.mark.integration

_BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
async def prepared_db(db_engine: AsyncEngine):
    async with db_engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                UserModel.__table__,
                ThreadModel.__table__,
                EmailModel.__table__,
                AttachmentModel.__table__,
                EmailAIUnderstandingModel.__table__,
            ],
        )
    yield db_engine
    async with db_engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.drop_all,
            tables=[
                EmailAIUnderstandingModel.__table__,
                AttachmentModel.__table__,
                EmailModel.__table__,
                ThreadModel.__table__,
                UserModel.__table__,
            ],
        )
        await conn.execute(text("DROP TYPE IF EXISTS user_status"))


@pytest.fixture
def session_factory(prepared_db: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=prepared_db, expire_on_commit=False)


@pytest_asyncio.fixture
async def repo(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as session:
        try:
            yield EmailAIUnderstandingRepository(session)
        finally:
            await session.rollback()
            await session.close()


async def _create_email(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        user = UserModel(
            email=f"{uuid.uuid4()}@example.com",
            full_name="AI Test User",
            google_sub_id=f"sub-{uuid.uuid4()}",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        thread = ThreadModel(
            user_id=user.id, gmail_thread_id=f"thread-{uuid.uuid4()}", subject="s", snippet="sn"
        )
        session.add(thread)
        await session.commit()
        await session.refresh(thread)

        email = EmailModel(
            thread_id=thread.id,
            user_id=user.id,
            gmail_message_id=f"msg-{uuid.uuid4()}",
            sender="sender@example.com",
            recipients=["recipient@example.com"],
            cc=[],
            bcc=[],
            subject="Test subject",
            snippet="snippet",
            body_text="body",
            received_at=_BASE_TIME,
            label_ids=[],
        )
        session.add(email)
        await session.commit()
        await session.refresh(email)
        return email.id


def _ai_result(**overrides) -> AIUnderstandingResult:
    defaults = dict(
        category=EmailCategory.TRAVEL,
        intent=EmailIntent.CANCELLATION,
        urgency=EmailUrgency.HIGH,
        sentiment=EmailSentiment.NEGATIVE,
        entities=[{"type": "organization", "value": "Delta Airlines"}],
        summary="Flight booking was cancelled.",
        confidence=0.94,
    )
    defaults.update(overrides)
    return AIUnderstandingResult(**defaults)


async def test_upsert_inserts_new_ai_understanding(
    repo: EmailAIUnderstandingRepository, session_factory
) -> None:
    email_id = await _create_email(session_factory)

    created = await repo.upsert(email_id, _ai_result())

    assert created.email_id == email_id
    assert created.category == "travel"
    assert created.confidence == 0.94


async def test_get_by_email_id_retrieves_stored_result(
    repo: EmailAIUnderstandingRepository, session_factory
) -> None:
    email_id = await _create_email(session_factory)
    await repo.upsert(email_id, _ai_result(summary="Distinctive summary text."))

    fetched = await repo.get_by_email_id(email_id)

    assert fetched is not None
    assert fetched.summary == "Distinctive summary text."


async def test_get_by_email_id_returns_none_when_no_result_exists(
    repo: EmailAIUnderstandingRepository, session_factory
) -> None:
    email_id = await _create_email(session_factory)

    assert await repo.get_by_email_id(email_id) is None


async def test_upsert_updates_existing_ai_understanding(
    repo: EmailAIUnderstandingRepository, session_factory
) -> None:
    email_id = await _create_email(session_factory)
    first = await repo.upsert(email_id, _ai_result(summary="First analysis."))

    updated = await repo.upsert(
        email_id,
        _ai_result(
            category=EmailCategory.WORK,
            summary="Re-analyzed with updated content.",
            confidence=0.5,
        ),
    )

    assert updated.id == first.id  # same row, not a new one
    assert updated.category == "work"
    assert updated.summary == "Re-analyzed with updated content."
    assert updated.confidence == 0.5


async def test_upsert_does_not_create_duplicate_rows(
    repo: EmailAIUnderstandingRepository, session_factory
) -> None:
    email_id = await _create_email(session_factory)

    await repo.upsert(email_id, _ai_result())
    await repo.upsert(email_id, _ai_result(summary="Second pass."))
    await repo.upsert(email_id, _ai_result(summary="Third pass."))

    async with session_factory() as session:
        from sqlalchemy import func, select

        count = (
            await session.execute(
                select(func.count())
                .select_from(EmailAIUnderstandingModel)
                .where(EmailAIUnderstandingModel.email_id == email_id)
            )
        ).scalar_one()

    assert count == 1


async def test_entities_persist_correctly(
    repo: EmailAIUnderstandingRepository, session_factory
) -> None:
    email_id = await _create_email(session_factory)
    result = _ai_result(
        entities=[
            {"type": "organization", "value": "Delta Airlines"},
            {"type": "date", "value": "August 15"},
            {"type": "location", "value": "Chicago"},
        ]
    )

    stored = await repo.upsert(email_id, result)

    assert stored.entities == [
        {"type": "organization", "value": "Delta Airlines"},
        {"type": "date", "value": "August 15"},
        {"type": "location", "value": "Chicago"},
    ]


async def test_empty_entities_list_persists_as_empty_list(
    repo: EmailAIUnderstandingRepository, session_factory
) -> None:
    email_id = await _create_email(session_factory)

    stored = await repo.upsert(email_id, _ai_result(entities=[]))

    assert stored.entities == []


async def test_confidence_persists_correctly(
    repo: EmailAIUnderstandingRepository, session_factory
) -> None:
    email_id = await _create_email(session_factory)

    await repo.upsert(email_id, _ai_result(confidence=0.123))

    fetched = await repo.get_by_email_id(email_id)
    assert fetched.confidence == pytest.approx(0.123)


async def test_foreign_key_rejects_nonexistent_email_id(
    repo: EmailAIUnderstandingRepository,
) -> None:
    with pytest.raises(IntegrityError):
        await repo.upsert(uuid.uuid4(), _ai_result())


async def test_unique_constraint_prevents_duplicate_rows_at_the_schema_level(
    session_factory,
) -> None:
    email_id = await _create_email(session_factory)

    async with session_factory() as session:
        session.add(
            EmailAIUnderstandingModel(
                email_id=email_id,
                category="travel",
                intent="cancellation",
                urgency="high",
                sentiment="negative",
                entities=[],
                summary="First row.",
                confidence=0.9,
            )
        )
        await session.commit()

    async with session_factory() as session:
        session.add(
            EmailAIUnderstandingModel(
                email_id=email_id,
                category="work",
                intent="request",
                urgency="low",
                sentiment="neutral",
                entities=[],
                summary="Second, colliding row.",
                confidence=0.1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
