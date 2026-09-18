import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.infrastructure.database.engine import create_db_engine, dispose_engine
from app.main import create_app


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
