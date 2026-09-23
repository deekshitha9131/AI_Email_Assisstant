import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.constants import EMBEDDING_DIMENSIONS
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.attachment import AttachmentModel
from app.infrastructure.database.models.email import EmailModel
from app.infrastructure.database.models.email_chunk import EmailChunkModel
from app.infrastructure.database.models.thread import ThreadModel
from app.infrastructure.database.models.user import UserModel
from app.infrastructure.database.repositories.email_chunk_repository import (
    ChunkWithEmbedding,
    EmailChunkRepository,
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
                EmailChunkModel.__table__,
            ],
        )
    yield db_engine
    async with db_engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.drop_all,
            tables=[
                EmailChunkModel.__table__,
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
            yield EmailChunkRepository(session)
        finally:
            await session.rollback()
            await session.close()


async def _create_user_thread_email(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with session_factory() as session:
        user = UserModel(
            email=f"{uuid.uuid4()}@example.com",
            full_name="Chunk Test User",
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

        return user.id, thread.id, email.id


def _vector(seed: float) -> list[float]:
    """A deterministic vector where every dimension equals `seed` — two
    vectors built with close seeds are close in cosine distance, and
    vectors with very different seeds are far apart, which is all
    these tests need to prove ordering behaves correctly."""
    return [seed] * EMBEDDING_DIMENSIONS


async def test_replace_chunks_for_email_stores_new_chunks(
    repo: EmailChunkRepository, session_factory
) -> None:
    user_id, thread_id, email_id = await _create_user_thread_email(session_factory)

    stored = await repo.replace_chunks_for_email(
        email_id=email_id,
        thread_id=thread_id,
        user_id=user_id,
        received_at=_BASE_TIME,
        chunks=[
            ChunkWithEmbedding(chunk_index=0, content="first chunk", embedding=_vector(0.1)),
            ChunkWithEmbedding(chunk_index=1, content="second chunk", embedding=_vector(0.2)),
        ],
    )

    assert len(stored) == 2
    fetched = await repo.get_by_email_id(email_id)
    assert [c.chunk_index for c in fetched] == [0, 1]
    assert [c.content for c in fetched] == ["first chunk", "second chunk"]


async def test_replace_chunks_for_email_removes_stale_chunks(
    repo: EmailChunkRepository, session_factory
) -> None:
    user_id, thread_id, email_id = await _create_user_thread_email(session_factory)

    await repo.replace_chunks_for_email(
        email_id=email_id,
        thread_id=thread_id,
        user_id=user_id,
        received_at=_BASE_TIME,
        chunks=[
            ChunkWithEmbedding(chunk_index=0, content="v1 chunk 0", embedding=_vector(0.1)),
            ChunkWithEmbedding(chunk_index=1, content="v1 chunk 1", embedding=_vector(0.2)),
            ChunkWithEmbedding(chunk_index=2, content="v1 chunk 2", embedding=_vector(0.3)),
        ],
    )

    # Re-index with fewer chunks — the trailing old ones must not linger.
    await repo.replace_chunks_for_email(
        email_id=email_id,
        thread_id=thread_id,
        user_id=user_id,
        received_at=_BASE_TIME,
        chunks=[ChunkWithEmbedding(chunk_index=0, content="v2 chunk 0", embedding=_vector(0.9))],
    )

    fetched = await repo.get_by_email_id(email_id)
    assert len(fetched) == 1
    assert fetched[0].content == "v2 chunk 0"


async def test_repeated_indexing_does_not_duplicate_rows(
    repo: EmailChunkRepository, session_factory
) -> None:
    user_id, thread_id, email_id = await _create_user_thread_email(session_factory)

    for _ in range(3):
        await repo.replace_chunks_for_email(
            email_id=email_id,
            thread_id=thread_id,
            user_id=user_id,
            received_at=_BASE_TIME,
            chunks=[
                ChunkWithEmbedding(chunk_index=0, content="chunk", embedding=_vector(0.1)),
            ],
        )

    fetched = await repo.get_by_email_id(email_id)
    assert len(fetched) == 1


# ---------------------------------------------------------------------------
# Similarity search
# ---------------------------------------------------------------------------


async def test_similarity_search_orders_by_closeness(
    repo: EmailChunkRepository, session_factory
) -> None:
    user_id, thread_id, email_id = await _create_user_thread_email(session_factory)

    await repo.replace_chunks_for_email(
        email_id=email_id,
        thread_id=thread_id,
        user_id=user_id,
        received_at=_BASE_TIME,
        chunks=[
            ChunkWithEmbedding(chunk_index=0, content="far", embedding=_vector(-1.0)),
            ChunkWithEmbedding(chunk_index=1, content="near", embedding=_vector(1.0)),
        ],
    )

    results = await repo.similarity_search(user_id=user_id, query_embedding=_vector(1.0), top_k=5)

    assert results[0].content == "near"
    assert results[0].distance < results[1].distance


async def test_similarity_search_respects_top_k(
    repo: EmailChunkRepository, session_factory
) -> None:
    user_id, thread_id, email_id = await _create_user_thread_email(session_factory)

    await repo.replace_chunks_for_email(
        email_id=email_id,
        thread_id=thread_id,
        user_id=user_id,
        received_at=_BASE_TIME,
        chunks=[
            ChunkWithEmbedding(chunk_index=i, content=f"chunk {i}", embedding=_vector(0.1 * i))
            for i in range(10)
        ],
    )

    results = await repo.similarity_search(user_id=user_id, query_embedding=_vector(0.5), top_k=3)

    assert len(results) == 3


async def test_similarity_search_only_returns_the_requesting_users_chunks(
    repo: EmailChunkRepository, session_factory
) -> None:
    user_a, thread_a, email_a = await _create_user_thread_email(session_factory)
    user_b, thread_b, email_b = await _create_user_thread_email(session_factory)

    await repo.replace_chunks_for_email(
        email_id=email_a,
        thread_id=thread_a,
        user_id=user_a,
        received_at=_BASE_TIME,
        chunks=[
            ChunkWithEmbedding(chunk_index=0, content="user A content", embedding=_vector(1.0))
        ],
    )
    await repo.replace_chunks_for_email(
        email_id=email_b,
        thread_id=thread_b,
        user_id=user_b,
        received_at=_BASE_TIME,
        chunks=[
            ChunkWithEmbedding(chunk_index=0, content="user B content", embedding=_vector(1.0))
        ],
    )

    results_for_a = await repo.similarity_search(
        user_id=user_a, query_embedding=_vector(1.0), top_k=10
    )

    assert len(results_for_a) == 1
    assert results_for_a[0].content == "user A content"


async def test_cascade_delete_removes_chunks_when_email_deleted(
    repo: EmailChunkRepository, session_factory
) -> None:
    user_id, thread_id, email_id = await _create_user_thread_email(session_factory)
    await repo.replace_chunks_for_email(
        email_id=email_id,
        thread_id=thread_id,
        user_id=user_id,
        received_at=_BASE_TIME,
        chunks=[ChunkWithEmbedding(chunk_index=0, content="chunk", embedding=_vector(0.1))],
    )

    async with session_factory() as session:
        email = await session.get(EmailModel, email_id)
        await session.delete(email)
        await session.commit()

    fetched = await repo.get_by_email_id(email_id)
    assert fetched == []
