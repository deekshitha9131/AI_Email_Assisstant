import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.domain.enums.draft_status import DraftStatus
from app.domain.exceptions.draft import DraftNotFoundError
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.attachment import AttachmentModel
from app.infrastructure.database.models.draft import DraftModel
from app.infrastructure.database.models.email import EmailModel
from app.infrastructure.database.models.thread import ThreadModel
from app.infrastructure.database.models.user import UserModel
from app.infrastructure.database.repositories.draft_repository import DraftRepository

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
                DraftModel.__table__,
            ],
        )
    yield db_engine
    async with db_engine.begin() as conn:
        for table_name in (
            "compose_drafts",
            "drafts",
            "attachments",
            "email_ai_understanding",
            "email_chunks",
            "emails",
            "oauth_tokens",
            "threads",
            "users",
        ):
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
        await conn.execute(text("DROP TYPE IF EXISTS user_status"))
        await conn.execute(text("DROP TYPE IF EXISTS draft_status"))


@pytest.fixture
def session_factory(prepared_db: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=prepared_db, expire_on_commit=False)


@pytest.fixture
async def repo(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as session:
        try:
            yield DraftRepository(session)
        finally:
            await session.rollback()
            await session.close()

async def _create_user_and_email(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    async with session_factory() as session:
        user = UserModel(
            email=f"{uuid.uuid4()}@example.com",
            full_name="Draft Test User",
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

        return user.id, email.id


@pytest.fixture
async def user_and_email(session_factory: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID]:
    return await _create_user_and_email(session_factory)

async def test_create_and_get_by_id(repo: DraftRepository, user_and_email) -> None:
    _, email_id = user_and_email

    created = await repo.create(email_id=email_id, body="Draft reply body.")

    assert created.email_id == email_id
    assert created.body == "Draft reply body."
    assert created.status == DraftStatus.GENERATED

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.body == "Draft reply body."


async def test_create_accepts_explicit_status(repo: DraftRepository, user_and_email) -> None:
    _, email_id = user_and_email

    created = await repo.create(email_id=email_id, body="Body.", status=DraftStatus.APPROVED)

    assert created.status == DraftStatus.APPROVED


async def test_get_by_id_returns_none_for_missing_draft(repo: DraftRepository) -> None:
    assert await repo.get_by_id(uuid.uuid4()) is None


async def test_one_email_can_have_multiple_drafts(repo: DraftRepository, user_and_email) -> None:
    _, email_id = user_and_email

    first = await repo.create(email_id=email_id, body="First attempt.")
    second = await repo.create(email_id=email_id, body="Second attempt.")

    assert first.id != second.id
    assert first.email_id == second.email_id == email_id

async def test_get_by_id_for_user_returns_draft_for_owner(
    repo: DraftRepository, user_and_email
) -> None:
    user_id, email_id = user_and_email
    created = await repo.create(email_id=email_id, body="Body.")

    fetched = await repo.get_by_id_for_user(created.id, user_id)

    assert fetched is not None
    assert fetched.id == created.id


async def test_get_by_id_for_user_returns_none_for_another_users_draft(
    repo: DraftRepository, session_factory
) -> None:
    owner_id, email_id = await _create_user_and_email(session_factory)
    other_user_id, _ = await _create_user_and_email(session_factory)
    created = await repo.create(email_id=email_id, body="Body.")

    assert await repo.get_by_id_for_user(created.id, other_user_id) is None
    # But the owner can fetch it fine — proves the None above was
    # specifically the ownership scoping, not a broken query.
    assert await repo.get_by_id_for_user(created.id, owner_id) is not None


async def test_get_by_id_for_user_returns_none_for_nonexistent_draft(
    repo: DraftRepository, user_and_email
) -> None:
    user_id, _ = user_and_email
    assert await repo.get_by_id_for_user(uuid.uuid4(), user_id) is None

async def test_list_by_user_returns_only_that_users_drafts(
    repo: DraftRepository, session_factory
) -> None:
    user_a, email_a = await _create_user_and_email(session_factory)
    user_b, email_b = await _create_user_and_email(session_factory)

    await repo.create(email_id=email_a, body="A's draft.")
    await repo.create(email_id=email_b, body="B's draft.")

    results_a = await repo.list_by_user(user_a)

    assert len(results_a) == 1
    assert results_a[0].body == "A's draft."


async def test_list_by_user_paginates(repo: DraftRepository, session_factory) -> None:
    user_id, email_id = await _create_user_and_email(session_factory)
    for i in range(5):
        await repo.create(email_id=email_id, body=f"Draft {i}.")

    page_1 = await repo.list_by_user(user_id, page=1, page_size=2)
    page_2 = await repo.list_by_user(user_id, page=2, page_size=2)

    assert len(page_1) == 2
    assert len(page_2) == 2
    assert {d.id for d in page_1}.isdisjoint({d.id for d in page_2})


async def test_list_by_user_rejects_invalid_page(repo: DraftRepository, user_and_email) -> None:
    user_id, _ = user_and_email
    with pytest.raises(ValueError):
        await repo.list_by_user(user_id, page=0)


async def test_count_by_user_reflects_draft_count(repo: DraftRepository, user_and_email) -> None:
    user_id, email_id = user_and_email
    for i in range(3):
        await repo.create(email_id=email_id, body=f"Draft {i}.")

    assert await repo.count_by_user(user_id) == 3


async def test_count_by_user_is_zero_for_user_with_no_drafts(
    repo: DraftRepository, user_and_email
) -> None:
    user_id, _ = user_and_email
    assert await repo.count_by_user(user_id) == 0


async def test_count_by_user_is_scoped_per_user(repo: DraftRepository, session_factory) -> None:
    user_a, email_a = await _create_user_and_email(session_factory)
    user_b, email_b = await _create_user_and_email(session_factory)

    await repo.create(email_id=email_a, body="A's draft.")
    await repo.create(email_id=email_b, body="B's draft 1.")
    await repo.create(email_id=email_b, body="B's draft 2.")

    assert await repo.count_by_user(user_a) == 1
    assert await repo.count_by_user(user_b) == 2


async def test_update_status_changes_status(repo: DraftRepository, user_and_email) -> None:
    _, email_id = user_and_email
    created = await repo.create(email_id=email_id, body="Body.")

    updated = await repo.update_status(created.id, DraftStatus.APPROVED)

    assert updated.id == created.id
    assert updated.status == DraftStatus.APPROVED


async def test_update_status_raises_for_missing_draft(repo: DraftRepository) -> None:
    with pytest.raises(DraftNotFoundError):
        await repo.update_status(uuid.uuid4(), DraftStatus.APPROVED)

async def test_drafts_are_deleted_when_parent_email_is_deleted(
    repo: DraftRepository, session_factory, user_and_email
) -> None:
    _, email_id = user_and_email
    created = await repo.create(email_id=email_id, body="Body.")

    async with session_factory() as session:
        email = await session.get(EmailModel, email_id)
        await session.delete(email)
        await session.commit()

    assert await repo.get_by_id(created.id) is None