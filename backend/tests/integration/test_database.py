"""Integration tests for the PostgreSQL database and pgvector support."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import Settings
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import create_db_engine, dispose_engine
from app.infrastructure.database.session import create_session_factory
from app.infrastructure.vector.types import embedding_column

pytestmark = pytest.mark.integration


class _IntegrationCheckModel(Base):
    """Temporary model used only by the database integration tests."""

    __tablename__ = "integration_check"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    embedding: Mapped[list[float] | None] = embedding_column(
        nullable=True,
    )


@pytest.fixture(autouse=True)
async def integration_table(db_engine):
    """Create and remove the temporary integration-test table."""

    async with db_engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[_IntegrationCheckModel.__table__],
        )

    yield

    async with db_engine.begin() as connection:
        await connection.run_sync(
            _IntegrationCheckModel.__table__.drop,
        )


@pytest.mark.asyncio
async def test_database_connection(db_engine):
    """Verify that PostgreSQL accepts a basic query."""

    async with db_engine.connect() as connection:
        result = await connection.execute(text("SELECT 1"))

        assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_pgvector_extension_is_available(db_engine):
    """Verify that the PostgreSQL pgvector extension is installed."""

    async with db_engine.connect() as connection:
        result = await connection.execute(text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_extension
                    WHERE extname = 'vector'
                )
                """))

        assert result.scalar_one() is True


@pytest.mark.asyncio
async def test_create_and_read_vector_record(session_factory):
    """Verify that a pgvector column can store and retrieve an embedding."""

    embedding = [0.1] * 384

    async with session_factory() as session:
        record = _IntegrationCheckModel(
            name="integration-test",
            embedding=embedding,
        )

        session.add(record)
        await session.commit()

        record_id = record.id

    async with session_factory() as session:
        stored = await session.get(
            _IntegrationCheckModel,
            record_id,
        )

        assert stored is not None
        assert stored.name == "integration-test"
        assert stored.embedding is not None
        assert len(stored.embedding) == 384


@pytest.mark.asyncio
async def test_nullable_embedding_is_supported(session_factory):
    """Verify that a record can exist before its embedding is generated."""

    async with session_factory() as session:
        record = _IntegrationCheckModel(
            name="without-embedding",
            embedding=None,
        )

        session.add(record)
        await session.commit()

        record_id = record.id

    async with session_factory() as session:
        stored = await session.get(
            _IntegrationCheckModel,
            record_id,
        )

        assert stored is not None
        assert stored.name == "without-embedding"
        assert stored.embedding is None
