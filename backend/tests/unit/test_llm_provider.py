from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APIConnectionError
from openai import APIStatusError
from httpx import Request, Response

from app.ai.providers.llm_provider import LLMProvider
from app.ai.schemas.ai_understanding import AIUnderstandingResult
from app.ai.schemas.preprocessing import PreprocessedEmail
from app.core.config import Settings
from app.domain.exceptions.ai import (
    AIConfigurationError,
    AIProviderError,
    InvalidAIResponseError,
)

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


def _email() -> PreprocessedEmail:
    return PreprocessedEmail(
        sender="jane@example.com",
        recipients=["bob@example.com"],
        subject="Flight Cancelled",
        body="Your flight booking has been cancelled.",
        truncated=False,
    )


def _completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@patch("app.ai.providers.llm_provider.AsyncOpenAI")
async def test_understand_email_uses_groq_json_and_validates_result(
    mock_client_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_completion(
            '{"category":"travel","intent":"cancellation","urgency":"high",'
            '"sentiment":"negative","entities":[],"summary":"Flight cancelled.",'
            '"confidence":0.94}'
        )
    )
    mock_client_cls.return_value = mock_client

    result = await LLMProvider(_settings(monkeypatch)).understand_email(_email())

    assert isinstance(result, AIUnderstandingResult)
    assert result.category.value == "travel"
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "openai/gpt-oss-20b"
    assert kwargs["max_tokens"] == 2048
    assert kwargs["response_format"] == {"type": "json_object"}
    assert mock_client.chat.completions.create.await_count == 1


async def test_missing_groq_key_raises_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LLMProvider(_settings(monkeypatch, GROQ_API_KEY=""))
    with pytest.raises(AIConfigurationError, match="GROQ_API_KEY"):
        await provider.understand_email(_email())


@patch("app.ai.providers.llm_provider.AsyncOpenAI")
async def test_generate_text_is_one_request(
    mock_client_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_completion("Draft reply"))
    mock_client_cls.return_value = mock_client

    result = await LLMProvider(_settings(monkeypatch)).generate_text(
        system_prompt="system", user_prompt="user", model="openai/gpt-oss-20b"
    )

    assert result == "Draft reply"
    assert mock_client.chat.completions.create.await_count == 1


@patch("app.ai.providers.llm_provider.AsyncOpenAI")
async def test_invalid_json_raises_invalid_response_error(
    mock_client_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_completion("not json"))
    mock_client_cls.return_value = mock_client

    with pytest.raises(InvalidAIResponseError):
        await LLMProvider(_settings(monkeypatch)).understand_email(_email())


@patch("app.ai.providers.llm_provider.AsyncOpenAI")
async def test_connection_failure_is_not_retried(
    mock_client_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=APIConnectionError(request=MagicMock())
    )
    mock_client_cls.return_value = mock_client

    with pytest.raises(AIProviderError):
        await LLMProvider(_settings(monkeypatch)).generate_text(
            system_prompt="system", user_prompt="user", model="openai/gpt-oss-20b"
        )
    assert mock_client.chat.completions.create.await_count == 1


@patch("app.ai.providers.llm_provider.AsyncOpenAI")
async def test_groq_json_validation_failure_is_an_invalid_response(
    mock_client_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=APIStatusError(
            "invalid JSON",
            response=Response(400, request=Request("POST", "https://api.groq.com")),
            body={"error": {"code": "json_validate_failed"}},
        )
    )
    mock_client_cls.return_value = mock_client

    with pytest.raises(InvalidAIResponseError, match="valid structured output"):
        await LLMProvider(_settings(monkeypatch)).understand_email(_email())
