import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.domain.enums.follow_up_source import FollowUpSource
from app.domain.enums.follow_up_status import FollowUpStatus
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.email import EmailModel
from app.infrastructure.database.models.follow_up import FollowUpModel
from app.infrastructure.database.models.notification import NotificationModel
from app.infrastructure.database.models.thread import ThreadModel
from app.infrastructure.database.models.user import UserModel
from app.infrastructure.database.repositories.notification_repository import NotificationRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def prepared_db(db_engine: AsyncEngine):
    async with db_engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[
                UserModel.__table__,
                ThreadModel.__table__,
                EmailModel.__table__,
                FollowUpModel.__table__,
                NotificationModel.__table__,
            ],
        )
    yield db_engine
    async with db_engine.begin() as connection:
        for table_name in ("notifications", "follow_ups", "emails", "threads", "users"):
            await connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
        await connection.execute(text("DROP TYPE IF EXISTS user_status"))
        await connection.execute(text("DROP TYPE IF EXISTS follow_up_source"))
        await connection.execute(text("DROP TYPE IF EXISTS follow_up_status"))


@pytest.fixture
def session_factory(prepared_db: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=prepared_db, expire_on_commit=False)


async def _seed_email(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with session_factory() as session:
        user = UserModel(
            email=f"{uuid.uuid4()}@example.com",
            full_name="Notification Test User",
            google_sub_id=f"sub-{uuid.uuid4()}",
        )
        session.add(user)
        await session.flush()
        thread = ThreadModel(
            user_id=user.id,
            gmail_thread_id=f"thread-{uuid.uuid4()}",
            subject="Urgent contract update",
            snippet="Please review.",
        )
        session.add(thread)
        await session.flush()
        email = EmailModel(
            thread_id=thread.id,
            user_id=user.id,
            gmail_message_id=f"message-{uuid.uuid4()}",
            sender="sender@example.com",
            recipients=[user.email],
            cc=[],
            bcc=[],
            subject="Urgent contract update",
            snippet="Please review.",
            body_text="Please review.",
            received_at=datetime.now(UTC),
            label_ids=["INBOX"],
        )
        session.add(email)
        await session.commit()
        return user.id, email.id, thread.id


async def test_get_or_create_prevents_duplicate_notifications(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, email_id, _thread_id = await _seed_email(session_factory)
    async with session_factory() as session:
        repository = NotificationRepository(session)
        first, first_created = await repository.get_or_create(
            user_id=user_id,
            email_id=email_id,
            notification_type="high_priority_email",
            title="High-priority email: Urgent contract update",
            message="This email was classified as high priority.",
        )
        second, second_created = await repository.get_or_create(
            user_id=user_id,
            email_id=email_id,
            notification_type="high_priority_email",
            title="High-priority email: Urgent contract update",
            message="This email was classified as high priority.",
        )

        assert first_created is True
        assert second_created is False
        assert second.id == first.id
        assert await repository.count_unread_by_user(user_id) == 1


async def test_get_or_create_follow_up_notification_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, email_id, thread_id = await _seed_email(session_factory)
    follow_up_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(
            FollowUpModel(
                id=follow_up_id,
                user_id=user_id,
                email_id=email_id,
                thread_id=thread_id,
                due_at=datetime.now(UTC),
                status=FollowUpStatus.PENDING,
                reason="Test follow-up.",
                source=FollowUpSource.AI,
            )
        )
        await session.commit()
        repository = NotificationRepository(session)
        first, first_created = await repository.get_or_create(
            user_id=user_id,
            email_id=email_id,
            follow_up_id=follow_up_id,
            notification_type="follow_up_due",
            title="Follow-up due: Urgent contract update",
            message="Test follow-up.",
        )
        second, second_created = await repository.get_or_create(
            user_id=user_id,
            email_id=email_id,
            follow_up_id=follow_up_id,
            notification_type="follow_up_due",
            title="Follow-up due: Urgent contract update",
            message="Test follow-up.",
        )

        assert first_created is True
        assert second_created is False
        assert second.id == first.id
