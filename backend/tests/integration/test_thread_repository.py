import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.infrastructure.database.base import Base
from app.infrastructure.database.models.attachment import AttachmentModel
from app.infrastructure.database.models.email import EmailModel
from app.infrastructure.database.models.thread import ThreadModel
from app.infrastructure.database.models.user import UserModel
from app.infrastructure.database.repositories.thread_repository import ThreadRepository

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
            ],
        )
    yield db_engine
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TYPE IF EXISTS user_status"))


@pytest.fixture
def session_factory(prepared_db: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=prepared_db, expire_on_commit=False)


@pytest_asyncio.fixture
async def repo(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as session:
        try:
            yield ThreadRepository(session)
        finally:
            await session.rollback()
            await session.close()


async def _create_user(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        user = UserModel(
            email=f"{uuid.uuid4()}@example.com",
            full_name="Thread Test User",
            google_sub_id=f"sub-{uuid.uuid4()}",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _create_thread(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    *,
    subject: str = "Test thread",
    updated_at: datetime | None = None,
) -> uuid.UUID:
    """Creates a ThreadModel directly (bypassing upsert) so `updated_at`
    can be pinned to a specific value — needed to make sort-order tests
    deterministic rather than relying on real-time insert ordering."""
    async with session_factory() as session:
        thread = ThreadModel(
            user_id=user_id,
            gmail_thread_id=f"gmail-thread-{uuid.uuid4()}",
            subject=subject,
            snippet="snippet",
        )
        session.add(thread)
        await session.commit()
        await session.refresh(thread)
        if updated_at is not None:
            thread.updated_at = updated_at
            await session.commit()
        return thread.id


async def _create_email(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    gmail_message_id: str,
    received_at: datetime,
) -> None:
    async with session_factory() as session:
        email = EmailModel(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id=gmail_message_id,
            sender="sender@example.com",
            recipients=["recipient@example.com"],
            cc=[],
            bcc=[],
            subject="Subject",
            snippet="snippet",
            body_text="body",
            received_at=received_at,
            label_ids=[],
        )
        session.add(email)
        await session.commit()


@pytest.fixture
async def user_id(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    return await _create_user(session_factory)


# ---------------------------------------------------------------------------
# get_by_id — ownership scoping
# ---------------------------------------------------------------------------


async def test_get_by_id_returns_thread_for_owner(
    repo: ThreadRepository, session_factory, user_id
) -> None:
    thread_id = await _create_thread(session_factory, user_id)

    fetched = await repo.get_by_id(thread_id, user_id)

    assert fetched is not None
    assert fetched.id == thread_id


async def test_get_by_id_returns_none_for_nonexistent_thread(
    repo: ThreadRepository, user_id
) -> None:
    assert await repo.get_by_id(uuid.uuid4(), user_id) is None


async def test_get_by_id_returns_none_for_another_users_thread(
    repo: ThreadRepository, session_factory
) -> None:
    owner_id = await _create_user(session_factory)
    other_user_id = await _create_user(session_factory)
    thread_id = await _create_thread(session_factory, owner_id)

    assert await repo.get_by_id(thread_id, other_user_id) is None
    # But the owner can fetch it fine — proves the None above was
    # specifically the ownership scoping, not a broken query.
    assert await repo.get_by_id(thread_id, owner_id) is not None


# ---------------------------------------------------------------------------
# list_by_user — pagination, sorting, email_count
# ---------------------------------------------------------------------------


async def test_list_by_user_paginates(repo: ThreadRepository, session_factory, user_id) -> None:
    for i in range(5):
        await _create_thread(
            session_factory,
            user_id,
            subject=f"Thread {i}",
            updated_at=_BASE_TIME + timedelta(hours=i),
        )

    page_1 = await repo.list_by_user(user_id, page=1, page_size=2, sort="newest")
    page_2 = await repo.list_by_user(user_id, page=2, page_size=2, sort="newest")

    assert [t.subject for t in page_1] == ["Thread 4", "Thread 3"]
    assert [t.subject for t in page_2] == ["Thread 2", "Thread 1"]


async def test_list_by_user_sorts_oldest_first(
    repo: ThreadRepository, session_factory, user_id
) -> None:
    for i in range(3):
        await _create_thread(
            session_factory,
            user_id,
            subject=f"Thread {i}",
            updated_at=_BASE_TIME + timedelta(hours=i),
        )

    results = await repo.list_by_user(user_id, sort="oldest")

    assert [t.subject for t in results] == ["Thread 0", "Thread 1", "Thread 2"]


async def test_list_by_user_reports_correct_email_count(
    repo: ThreadRepository, session_factory, user_id
) -> None:
    thread_id = await _create_thread(session_factory, user_id, updated_at=_BASE_TIME)
    for i in range(3):
        await _create_email(
            session_factory,
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id=f"m{i}",
            received_at=_BASE_TIME,
        )

    other_thread_id = await _create_thread(session_factory, user_id, updated_at=_BASE_TIME)

    results = await repo.list_by_user(user_id, sort="oldest")
    counts_by_id = {t.id: t.email_count for t in results}

    assert counts_by_id[thread_id] == 3
    assert counts_by_id[other_thread_id] == 0


async def test_list_by_user_rejects_invalid_page(repo: ThreadRepository, user_id) -> None:
    with pytest.raises(ValueError):
        await repo.list_by_user(user_id, page=0)


async def test_list_by_user_only_returns_this_users_threads(
    repo: ThreadRepository, session_factory
) -> None:
    user_a = await _create_user(session_factory)
    user_b = await _create_user(session_factory)
    await _create_thread(session_factory, user_a, subject="A's thread", updated_at=_BASE_TIME)
    await _create_thread(session_factory, user_b, subject="B's thread", updated_at=_BASE_TIME)

    results = await repo.list_by_user(user_a)

    assert [t.subject for t in results] == ["A's thread"]


# ---------------------------------------------------------------------------
# count_by_user
# ---------------------------------------------------------------------------


async def test_count_by_user_reflects_thread_count(
    repo: ThreadRepository, session_factory, user_id
) -> None:
    for _ in range(4):
        await _create_thread(session_factory, user_id, updated_at=_BASE_TIME)

    assert await repo.count_by_user(user_id) == 4


async def test_count_by_user_is_zero_for_user_with_no_threads(
    repo: ThreadRepository, user_id
) -> None:
    assert await repo.count_by_user(user_id) == 0


# ---------------------------------------------------------------------------
# get_thread_emails / count_thread_emails
# ---------------------------------------------------------------------------


async def test_get_thread_emails_returns_chronological_order(
    repo: ThreadRepository, session_factory, user_id
) -> None:
    thread_id = await _create_thread(session_factory, user_id, updated_at=_BASE_TIME)
    await _create_email(
        session_factory,
        thread_id=thread_id,
        user_id=user_id,
        gmail_message_id="newer",
        received_at=_BASE_TIME + timedelta(hours=2),
    )
    await _create_email(
        session_factory,
        thread_id=thread_id,
        user_id=user_id,
        gmail_message_id="older",
        received_at=_BASE_TIME,
    )

    emails = await repo.get_thread_emails(thread_id, user_id)

    assert [e.gmail_message_id for e in emails] == ["older", "newer"]


async def test_get_thread_emails_only_returns_this_threads_emails(
    repo: ThreadRepository, session_factory, user_id
) -> None:
    thread_a = await _create_thread(session_factory, user_id, updated_at=_BASE_TIME)
    thread_b = await _create_thread(session_factory, user_id, updated_at=_BASE_TIME)
    await _create_email(
        session_factory,
        thread_id=thread_a,
        user_id=user_id,
        gmail_message_id="a1",
        received_at=_BASE_TIME,
    )
    await _create_email(
        session_factory,
        thread_id=thread_b,
        user_id=user_id,
        gmail_message_id="b1",
        received_at=_BASE_TIME,
    )

    emails = await repo.get_thread_emails(thread_a, user_id)

    assert [e.gmail_message_id for e in emails] == ["a1"]


async def test_count_thread_emails(repo: ThreadRepository, session_factory, user_id) -> None:
    thread_id = await _create_thread(session_factory, user_id, updated_at=_BASE_TIME)
    for i in range(3):
        await _create_email(
            session_factory,
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id=f"m{i}",
            received_at=_BASE_TIME,
        )

    assert await repo.count_thread_emails(thread_id, user_id) == 3


async def test_get_thread_emails_enforces_user_isolation(
    repo: ThreadRepository, session_factory
) -> None:
    user_a = await _create_user(session_factory)
    user_b = await _create_user(session_factory)
    thread_a = await _create_thread(session_factory, user_a, updated_at=_BASE_TIME)
    await _create_email(
        session_factory,
        thread_id=thread_a,
        user_id=user_a,
        gmail_message_id="a1",
        received_at=_BASE_TIME,
    )

    # A different user querying thread_a's emails with their own user_id
    # gets nothing back, even though the thread_id is real.
    emails = await repo.get_thread_emails(thread_a, user_b)

    assert emails == []
