from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.domain.exceptions.ai import AIAuthenticationError
from app.presentation.api.v1.routers.status import _check_ai_status


BASE_ENV = {
    "APP_ENV": "development",
    "APP_DEBUG": "true",
    "APP_SECRET_KEY": "dev-secret",
    "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
    "REDIS_URL": "redis://h:6379/0",
    "CELERY_BROKER_URL": "redis://h:6379/1",
    "CELERY_RESULT_BACKEND": "redis://h:6379/1",
    "TOKEN_ENCRYPTION_KEY": "test-token-encryption-key-value",
    "CORS_ORIGINS": "http://localhost:5173",
    "LLM_PROVIDER": "groq",
    "GROQ_API_KEY": "test-groq-key",
}


def _settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    for key, value in {**BASE_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_ai_status_reports_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.presentation.api.v1.routers.status as status_router

    status_router._ai_status_cache = None
    provider = type("Provider", (), {"health_check": AsyncMock()})()

    result = await _check_ai_status(_settings(monkeypatch, GROQ_API_KEY=""), provider)

    assert result["status"] == "not_configured"
    provider.health_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_status_reports_configured_without_provider_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.presentation.api.v1.routers.status as status_router

    status_router._ai_status_cache = None
    provider = type("Provider", (), {"health_check": AsyncMock()})()

    result = await _check_ai_status(_settings(monkeypatch), provider)

    assert result["status"] == "available"
    provider.health_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_status_does_not_probe_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.presentation.api.v1.routers.status as status_router

    status_router._ai_status_cache = None
    provider = type("Provider", (), {"health_check": AsyncMock()})()

    result = await _check_ai_status(_settings(monkeypatch), provider)

    assert result["status"] == "available"
    provider.health_check.assert_not_awaited()
