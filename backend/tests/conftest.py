import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.core.constants import EMBEDDING_DIMENSIONS
from app.infrastructure.database.engine import create_db_engine, dispose_engine
from app.main import create_app


class FakeEmbeddingVector(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.calls: list[str | list[str]] = []

    def encode(self, value: str | list[str], normalize_embeddings: bool = True) -> FakeEmbeddingVector | list[FakeEmbeddingVector]:
        self.calls.append(value)

        def vector_for(text: str) -> FakeEmbeddingVector:
            seed = sum((index + 1) * ord(char) for index, char in enumerate(text))
            return FakeEmbeddingVector(
                [((seed + i * 13) % 997) / 997.0 for i in range(EMBEDDING_DIMENSIONS)]
            )

        if isinstance(value, str):
            return vector_for(value)
        return [vector_for(text) for text in value]


@pytest.fixture(autouse=True)
def fake_embedding_model(monkeypatch: pytest.MonkeyPatch) -> FakeEmbeddingModel:
    """Keep all tests deterministic and offline by replacing the real SentenceTransformer loader."""
    model = FakeEmbeddingModel()
    monkeypatch.setattr("app.ai.rag.embedding._load_model", lambda: model)
    return model


@pytest.fixture(autouse=True)
def celery_unit_test_mode(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Prevent unit tests from reaching a live Redis-backed Celery result backend."""
    from app.workers.ai_tasks.indexing_tasks import index_email_task
    from app.workers.classification_tasks.analysis_tasks import analyze_email_task

    monkeypatch.setattr(index_email_task, "delay", lambda *args, **kwargs: None)
    monkeypatch.setattr(analyze_email_task, "delay", lambda *args, **kwargs: None)

    yield


@pytest.fixture(scope="session")
def settings() -> Settings:
    """The application's real settings, sourced the same way the app itself sources them."""
    return get_settings()


@pytest.fixture
def app_no_lifespan() -> FastAPI:
    return create_app()


@pytest.fixture
def unit_client(app_no_lifespan: FastAPI) -> Generator[TestClient, None, None]:
    client = TestClient(app_no_lifespan, raise_server_exceptions=False)
    yield client
    app_no_lifespan.dependency_overrides.clear()


async def _postgres_reachable(settings: Settings) -> bool:
    engine = create_db_engine(settings)
    try:
        async with asyncio.timeout(5):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — reachability probe, any failure means "not reachable"
        return False
    finally:
        await dispose_engine(engine)


async def _redis_reachable(settings: Settings) -> bool:
    client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
    try:
        async with asyncio.timeout(5):
            return bool(await client.ping())
    except Exception:  # noqa: BLE001
        return False
    finally:
        await client.aclose()


@pytest.fixture(scope="session")
def db_available(settings: Settings) -> bool:

    return asyncio.run(_postgres_reachable(settings))


@pytest.fixture(scope="session")
def redis_available(settings: Settings) -> bool:
    """True if a real Redis instance is reachable at settings.redis_url."""
    return asyncio.run(_redis_reachable(settings))


@pytest.fixture
async def db_engine(settings: Settings, db_available: bool) -> AsyncGenerator[AsyncEngine, None]:
    """A real database engine, for integration tests. Skips if unreachable."""
    if not db_available:
        pytest.skip("No live Postgres reachable at DATABASE_URL — skipping integration test.")
    engine = create_db_engine(settings)
    yield engine
    await dispose_engine(engine)


@pytest.fixture
def integration_client(
    app_no_lifespan: FastAPI, db_available: bool, redis_available: bool
) -> Generator[TestClient, None, None]:
    if not db_available:
        pytest.skip("No live Postgres reachable at DATABASE_URL — skipping integration test.")
    if not redis_available:
        pytest.skip("No live Redis reachable at REDIS_URL — skipping integration test.")

    with TestClient(app_no_lifespan) as client:
        yield client
