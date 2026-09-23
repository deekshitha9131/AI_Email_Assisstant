import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import get_settings
from app.core.security import TokenCipher
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.user import UserAlreadyExistsError, UserNotFoundError
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.user import UserModel
from app.infrastructure.database.repositories.user_repository import UserRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def prepared_db(db_engine: AsyncEngine):
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[UserModel.__table__])
    yield db_engine
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        from sqlalchemy import text

        await conn.execute(text("DROP TYPE IF EXISTS user_status"))


@pytest_asyncio.fixture
async def repo(prepared_db: AsyncEngine):
    session_factory = async_sessionmaker(bind=prepared_db, expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield UserRepository(session, TokenCipher(get_settings()))
        finally:
            await session.rollback()


async def test_create_and_get_by_id(repo: UserRepository) -> None:
    created = await repo.create(email="a@example.com", full_name="A User", google_sub_id="sub-a")

    assert created.id is not None
    assert created.status == UserStatus.ACTIVE
    assert created.created_at is not None
    assert created.updated_at is not None

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.email == "a@example.com"


async def test_get_by_email(repo: UserRepository) -> None:
    await repo.create(email="b@example.com", full_name="B User", google_sub_id="sub-b")

    fetched = await repo.get_by_email("b@example.com")
    assert fetched is not None
    assert fetched.full_name == "B User"

    assert await repo.get_by_email("nonexistent@example.com") is None


async def test_get_by_google_sub_id(repo: UserRepository) -> None:
    await repo.create(email="c@example.com", full_name="C User", google_sub_id="sub-c")

    fetched = await repo.get_by_google_sub_id("sub-c")
    assert fetched is not None
    assert fetched.email == "c@example.com"


async def test_duplicate_email_raises_user_already_exists(repo: UserRepository) -> None:
    await repo.create(email="dup@example.com", full_name="First", google_sub_id="sub-1")

    with pytest.raises(UserAlreadyExistsError):
        await repo.create(email="dup@example.com", full_name="Second", google_sub_id="sub-2")


async def test_duplicate_google_sub_id_raises_user_already_exists(repo: UserRepository) -> None:
    await repo.create(email="e1@example.com", full_name="First", google_sub_id="dup-sub")

    with pytest.raises(UserAlreadyExistsError):
        await repo.create(email="e2@example.com", full_name="Second", google_sub_id="dup-sub")


async def test_update_full_name(repo: UserRepository) -> None:
    created = await repo.create(email="f@example.com", full_name="Old Name", google_sub_id="sub-f")

    updated = await repo.update_full_name(created.id, "New Name")
    assert updated.full_name == "New Name"
    assert updated.updated_at >= created.updated_at


async def test_update_full_name_raises_for_missing_user(repo: UserRepository) -> None:
    with pytest.raises(UserNotFoundError):
        await repo.update_full_name(uuid.uuid4(), "New Name")


async def test_set_status(repo: UserRepository) -> None:
    created = await repo.create(email="g@example.com", full_name="G User", google_sub_id="sub-g")
    assert created.status == UserStatus.ACTIVE

    updated = await repo.set_status(created.id, UserStatus.INACTIVE)
    assert updated.status == UserStatus.INACTIVE


async def test_soft_delete_excludes_user_from_lookups(repo: UserRepository) -> None:
    created = await repo.create(email="h@example.com", full_name="H User", google_sub_id="sub-h")

    await repo.soft_delete(created.id)

    assert await repo.get_by_id(created.id) is None
    assert await repo.get_by_email("h@example.com") is None
    assert await repo.get_by_google_sub_id("sub-h") is None


async def test_soft_delete_raises_for_missing_user(repo: UserRepository) -> None:
    with pytest.raises(UserNotFoundError):
        await repo.soft_delete(uuid.uuid4())


async def test_list_users_filters_by_status_and_excludes_deleted(repo: UserRepository) -> None:
    active_user = await repo.create(
        email="i1@example.com", full_name="Active", google_sub_id="sub-i1"
    )
    inactive_user = await repo.create(
        email="i2@example.com", full_name="Inactive", google_sub_id="sub-i2"
    )
    await repo.set_status(inactive_user.id, UserStatus.INACTIVE)

    deleted_user = await repo.create(
        email="i3@example.com", full_name="Deleted", google_sub_id="sub-i3"
    )
    await repo.soft_delete(deleted_user.id)

    all_users = await repo.list_users()
    all_ids = {u.id for u in all_users}
    assert active_user.id in all_ids
    assert inactive_user.id in all_ids
    assert deleted_user.id not in all_ids

    only_active = await repo.list_users(status=UserStatus.ACTIVE)
    only_active_ids = {u.id for u in only_active}
    assert active_user.id in only_active_ids
    assert inactive_user.id not in only_active_ids
