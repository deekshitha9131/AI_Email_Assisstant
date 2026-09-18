from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import get_settings
from app.core.security import TokenCipher
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.oauth_token import OAuthTokenModel
from app.infrastructure.database.models.user import UserModel
from app.infrastructure.database.repositories.user_repository import UserRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def prepared_db(db_engine: AsyncEngine):
    async with db_engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all, tables=[UserModel.__table__, OAuthTokenModel.__table__]
        )
    yield db_engine
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        from sqlalchemy import text

        await conn.execute(text("DROP TYPE IF EXISTS user_status"))


@pytest_asyncio.fixture
async def repo(prepared_db: AsyncEngine):
    session_factory = async_sessionmaker(bind=prepared_db, expire_on_commit=False)
    session = session_factory()
    try:
        yield UserRepository(session, TokenCipher(get_settings()))
    finally:
        await session.close()


async def test_save_and_get_oauth_tokens_round_trip(repo: UserRepository) -> None:
    user = await repo.create(email="tok@example.com", full_name="Tok User", google_sub_id="sub-tok")
    expiry = datetime.now(UTC) + timedelta(hours=1)

    await repo.save_oauth_tokens(
        user.id,
        access_token="real-access-token-value",
        refresh_token="real-refresh-token-value",
        token_expiry=expiry,
        granted_scopes=["openid", "email", "https://www.googleapis.com/auth/gmail.readonly"],
    )

    tokens = await repo.get_oauth_tokens(user.id)
    assert tokens is not None
    assert tokens.access_token == "real-access-token-value"
    assert tokens.refresh_token == "real-refresh-token-value"
    assert "https://www.googleapis.com/auth/gmail.readonly" in tokens.granted_scopes


async def test_get_oauth_tokens_returns_none_when_never_connected(repo: UserRepository) -> None:
    user = await repo.create(
        email="notok@example.com", full_name="No Tok", google_sub_id="sub-notok"
    )
    assert await repo.get_oauth_tokens(user.id) is None


async def test_save_oauth_tokens_overwrites_previous_tokens(repo: UserRepository) -> None:
    user = await repo.create(
        email="over@example.com", full_name="Over User", google_sub_id="sub-over"
    )
    expiry = datetime.now(UTC) + timedelta(hours=1)

    await repo.save_oauth_tokens(
        user.id,
        access_token="first-access-token",
        refresh_token="first-refresh-token",
        token_expiry=expiry,
        granted_scopes=["openid"],
    )
    await repo.save_oauth_tokens(
        user.id,
        access_token="second-access-token",
        refresh_token="second-refresh-token",
        token_expiry=expiry,
        granted_scopes=["openid", "email"],
    )

    tokens = await repo.get_oauth_tokens(user.id)
    assert tokens is not None
    assert tokens.access_token == "second-access-token"
    assert tokens.refresh_token == "second-refresh-token"


async def test_save_oauth_tokens_preserves_refresh_token_when_omitted(
    repo: UserRepository,
) -> None:
    user = await repo.create(
        email="preserve@example.com", full_name="Preserve User", google_sub_id="sub-preserve"
    )
    expiry = datetime.now(UTC) + timedelta(hours=1)

    await repo.save_oauth_tokens(
        user.id,
        access_token="first-access-token",
        refresh_token="stable-refresh-token",
        token_expiry=expiry,
        granted_scopes=["openid"],
    )
    await repo.save_oauth_tokens(
        user.id,
        access_token="second-access-token",
        refresh_token=None,
        token_expiry=expiry,
        granted_scopes=["openid", "email"],
    )

    tokens = await repo.get_oauth_tokens(user.id)
    assert tokens is not None
    assert tokens.access_token == "second-access-token"
    assert tokens.refresh_token == "stable-refresh-token"


async def test_tokens_are_actually_encrypted_in_the_database(
    repo: UserRepository, prepared_db: AsyncEngine
) -> None:
    """Verifies encryption is really happening, not just that the round
    trip works — reads the raw column value directly and confirms it
    does not contain the plaintext token."""
    user = await repo.create(email="enc@example.com", full_name="Enc User", google_sub_id="sub-enc")
    await repo.save_oauth_tokens(
        user.id,
        access_token="plaintext-marker-value",
        refresh_token="another-plaintext-marker",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
        granted_scopes=["openid"],
    )

    session_factory = async_sessionmaker(bind=prepared_db, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(OAuthTokenModel).where(OAuthTokenModel.user_id == user.id)
        )
        raw_model = result.scalar_one()
        assert b"plaintext-marker-value" not in raw_model.access_token_encrypted
        assert b"another-plaintext-marker" not in raw_model.refresh_token_encrypted
