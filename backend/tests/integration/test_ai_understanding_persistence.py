import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
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


async def _create_user_and_email(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    async with session_factory() as session:
        user = UserModel(
            email=f"{uuid.uuid4()}@example.com",
            full_name="Persistence Test User",
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
            subject="Flight Cancelled",
            snippet="Your flight has been cancelled",
            body_text="Your flight booking has been cancelled. Please contact us immediately.",
            received_at=_BASE_TIME,
            label_ids=[],
        )
        session.add(email)
        await session.commit()
        await session.refresh(email)
        return email.id


def _full_ai_result() -> AIUnderstandingResult:
    return AIUnderstandingResult(
        category=EmailCategory.TRAVEL,
        intent=EmailIntent.CANCELLATION,
        urgency=EmailUrgency.CRITICAL,
        sentiment=EmailSentiment.NEGATIVE,
        entities=[
            {"type": "organization", "value": "Delta Airlines"},
            {"type": "date", "value": "August 15"},
            {"type": "confirmation_number", "value": "ABC123"},
        ],
        summary="Flight booking was cancelled; the sender is asked to contact support immediately.",
        confidence=0.94,
    )


async def test_full_round_trip_preserves_every_field(session_factory) -> None:
    email_id = await _create_user_and_email(session_factory)
    original = _full_ai_result()

    async with session_factory() as session:
        repo = EmailAIUnderstandingRepository(session)
        await repo.upsert(email_id, original)

        fetched = await repo.get_by_email_id(email_id)

    assert fetched is not None
    assert fetched.category == original.category.value
    assert fetched.intent == original.intent.value
    assert fetched.urgency == original.urgency.value
    assert fetched.sentiment == original.sentiment.value
    assert fetched.summary == original.summary
    assert fetched.confidence == pytest.approx(original.confidence)
    assert fetched.entities == [entity.model_dump() for entity in original.entities]
    assert fetched.follow_up_needed is False
    assert fetched.follow_up_date is None
    assert fetched.follow_up_reason is None
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_reprocessing_updates_in_place_and_bumps_updated_at(session_factory) -> None:
    email_id = await _create_user_and_email(session_factory)

    async with session_factory() as session:
        repo = EmailAIUnderstandingRepository(session)
        first = await repo.upsert(email_id, _full_ai_result())

        second_result = AIUnderstandingResult(
            category=EmailCategory.OTHER,
            intent=EmailIntent.INFORMATION,
            urgency=EmailUrgency.LOW,
            sentiment=EmailSentiment.NEUTRAL,
            entities=[],
            summary="Re-processed: content has changed.",
            confidence=0.4,
        )
        second = await repo.upsert(email_id, second_result)

    assert second.id == first.id
    assert second.category == "other"
    assert second.entities == []
    assert second.updated_at >= first.updated_at


async def test_follow_up_fields_round_trip(session_factory) -> None:
    email_id = await _create_user_and_email(session_factory)
    result = _full_ai_result().model_copy(
        update={
            "follow_up_needed": True,
            "follow_up_date": datetime(2026, 8, 15, 9, tzinfo=UTC),
            "follow_up_reason": "Contact the airline after the cancellation.",
        }
    )

    async with session_factory() as session:
        repo = EmailAIUnderstandingRepository(session)
        await repo.upsert(email_id, result)
        fetched = await repo.get_by_email_id(email_id)

    assert fetched is not None
    assert fetched.follow_up_needed is True
    assert fetched.follow_up_date == result.follow_up_date
    assert fetched.follow_up_reason == result.follow_up_reason


async def test_ai_understanding_is_deleted_when_parent_email_is_deleted(
    session_factory,
) -> None:

    email_id = await _create_user_and_email(session_factory)

    async with session_factory() as session:
        repo = EmailAIUnderstandingRepository(session)
        await repo.upsert(email_id, _full_ai_result())

    async with session_factory() as session:
        email = await session.get(EmailModel, email_id)
        await session.delete(email)
        await session.commit()

    async with session_factory() as session:
        remaining = (
            await session.execute(
                select(EmailAIUnderstandingModel).where(
                    EmailAIUnderstandingModel.email_id == email_id
                )
            )
        ).scalar_one_or_none()

    assert remaining is None


async def test_multiple_emails_have_independent_ai_understanding_rows(
    session_factory,
) -> None:
    email_id_a = await _create_user_and_email(session_factory)
    email_id_b = await _create_user_and_email(session_factory)

    async with session_factory() as session:
        repo = EmailAIUnderstandingRepository(session)
        await repo.upsert(email_id_a, _full_ai_result())
        await repo.upsert(
            email_id_b,
            AIUnderstandingResult(
                category=EmailCategory.FINANCE,
                intent=EmailIntent.CONFIRMATION,
                urgency=EmailUrgency.MEDIUM,
                sentiment=EmailSentiment.POSITIVE,
                entities=[],
                summary="Payment confirmation.",
                confidence=0.8,
            ),
        )

        result_a = await repo.get_by_email_id(email_id_a)
        result_b = await repo.get_by_email_id(email_id_b)

    assert result_a.category == "travel"
    assert result_b.category == "finance"
    assert result_a.id != result_b.id
