import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.domain.enums.follow_up_source import FollowUpSource
from app.domain.enums.follow_up_status import FollowUpStatus
from app.domain.exceptions.follow_up import ActiveFollowUpExistsError
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.email import EmailModel
from app.infrastructure.database.models.follow_up import FollowUpModel
from app.infrastructure.database.models.thread import ThreadModel
from app.infrastructure.database.models.user import UserModel
from app.infrastructure.database.repositories.follow_up_repository import FollowUpRepository

pytestmark = pytest.mark.integration

_DUE_AT = datetime(2026, 9, 20, 14, 30, tzinfo=UTC)


@pytest.fixture
async def prepared_db(db_engine: AsyncEngine):
    async with db_engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[UserModel.__table__, ThreadModel.__table__, EmailModel.__table__, FollowUpModel.__table__],
        )
    yield db_engine
    async with db_engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.drop_all,
            tables=[FollowUpModel.__table__, EmailModel.__table__, ThreadModel.__table__, UserModel.__table__],
        )
        await connection.execute(text("DROP TYPE IF EXISTS follow_up_source"))
        await connection.execute(text("DROP TYPE IF EXISTS follow_up_status"))
        await connection.execute(text("DROP TYPE IF EXISTS user_status"))


@pytest.fixture
def session_factory(prepared_db: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=prepared_db, expire_on_commit=False)


async def _create_user_and_email(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with session_factory() as session:
        user = UserModel(
            email=f"{uuid.uuid4()}@example.com",
            full_name="Follow-up Test User",
            google_sub_id=f"sub-{uuid.uuid4()}",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        thread = ThreadModel(
            user_id=user.id,
            gmail_thread_id=f"thread-{uuid.uuid4()}",
            subject="Follow up",
            snippet="Please follow up",
        )
        session.add(thread)
        await session.commit()
        await session.refresh(thread)

        email = EmailModel(
            thread_id=thread.id,
            user_id=user.id,
            gmail_message_id=f"message-{uuid.uuid4()}",
            sender="sender@example.com",
            recipients=["recipient@example.com"],
            cc=[],
            bcc=[],
            subject="Follow up",
            snippet="Please follow up",
            body_text="Please follow up next week.",
            received_at=_DUE_AT,
            label_ids=[],
        )
        session.add(email)
        await session.commit()
        await session.refresh(email)
        return user.id, email.id, thread.id


async def _create_follow_up(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    email_id: uuid.UUID,
    thread_id: uuid.UUID,
    *,
    status: FollowUpStatus = FollowUpStatus.PENDING,
):
    async with session_factory() as session:
        return await FollowUpRepository(session).create(
            user_id=user_id,
            email_id=email_id,
            thread_id=thread_id,
            due_at=_DUE_AT,
            reason="Check whether the request was completed.",
            source=FollowUpSource.USER,
            status=status,
        )


async def test_create_and_retrieve_follow_up_preserves_timezone_aware_due_at(session_factory) -> None:
    user_id, email_id, thread_id = await _create_user_and_email(session_factory)

    created = await _create_follow_up(session_factory, user_id, email_id, thread_id)

    async with session_factory() as session:
        fetched = await FollowUpRepository(session).get_by_id_for_user(created.id, user_id)

    assert fetched is not None
    assert fetched.email_id == email_id
    assert fetched.thread_id == thread_id
    assert fetched.status == FollowUpStatus.PENDING
    assert fetched.source == FollowUpSource.USER
    assert fetched.due_at == _DUE_AT
    assert fetched.due_at.tzinfo is not None
    assert fetched.due_at.utcoffset() is not None


async def test_follow_up_is_scoped_to_its_user(session_factory) -> None:
    user_id, email_id, thread_id = await _create_user_and_email(session_factory)
    created = await _create_follow_up(session_factory, user_id, email_id, thread_id)

    async with session_factory() as session:
        fetched = await FollowUpRepository(session).get_by_id_for_user(created.id, uuid.uuid4())

    assert fetched is None


async def test_duplicate_active_follow_up_is_rejected(session_factory) -> None:
    user_id, email_id, thread_id = await _create_user_and_email(session_factory)
    await _create_follow_up(session_factory, user_id, email_id, thread_id)

    with pytest.raises(ActiveFollowUpExistsError):
        await _create_follow_up(session_factory, user_id, email_id, thread_id)


async def test_completed_and_dismissed_follow_ups_do_not_block_new_active_record(
    session_factory,
) -> None:
    user_id, email_id, thread_id = await _create_user_and_email(session_factory)
    completed = await _create_follow_up(session_factory, user_id, email_id, thread_id)

    async with session_factory() as session:
        await FollowUpRepository(session).update_status_for_user(
            completed.id,
            user_id,
            status=FollowUpStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )

    dismissed = await _create_follow_up(session_factory, user_id, email_id, thread_id)
    async with session_factory() as session:
        await FollowUpRepository(session).update_status_for_user(
            dismissed.id,
            user_id,
            status=FollowUpStatus.DISMISSED,
            dismissed_at=datetime.now(UTC),
        )

    replacement = await _create_follow_up(session_factory, user_id, email_id, thread_id)

    assert replacement.status == FollowUpStatus.PENDING