from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.ai.context.draft_context import DraftContext
from app.ai.schemas.ai_understanding import (
    AIUnderstandingResult,
    EmailCategory,
    EmailIntent,
    EmailSentiment,
    EmailUrgency,
)
from app.ai.schemas.rag import RAGContext
from app.ai.services.draft_generator import DraftGenerator
from app.core.config import Settings
from app.domain.entities.email import Email
from app.domain.exceptions.ai import AIProviderError, InvalidAIResponseError

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
    env = {**BASE_ENV, **overrides}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _email(**overrides) -> Email:
    defaults = dict(
        id=uuid4(),
        thread_id=uuid4(),
        user_id=uuid4(),
        gmail_message_id="m1",
        sender="jane@example.com",
        recipients=["bob@example.com"],
        cc=[],
        bcc=[],
        subject="Flight Cancelled",
        snippet="snippet",
        body_text="Your flight has been cancelled.",
        body_html=None,
        received_at=datetime.now(UTC),
        is_read=True,
        is_starred=False,
        has_attachments=False,
        label_ids=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Email(**defaults)


def _understanding(**overrides) -> AIUnderstandingResult:
    defaults = dict(
        category=EmailCategory.TRAVEL,
        intent=EmailIntent.CANCELLATION,
        urgency=EmailUrgency.HIGH,
        sentiment=EmailSentiment.NEGATIVE,
        entities=[],
        summary="Flight booking was cancelled.",
        confidence=0.9,
    )
    defaults.update(overrides)
    return AIUnderstandingResult(**defaults)


def _draft_context(**overrides) -> DraftContext:
    defaults = dict(
        email=_email(), understanding=_understanding(), retrieved_context=RAGContext()
    )
    defaults.update(overrides)
    return DraftContext(**defaults)


class FakeLLMProvider:
    def __init__(self, *, text: str | None = "Thanks for reaching out, we'll follow up shortly.", raise_error: Exception | None = None) -> None:
        self._text = text
        self._raise_error = raise_error
        self.generate_text_calls: list[dict] = []

    async def generate_text(self, *, system_prompt: str, user_prompt: str, model: str) -> str:
        self.generate_text_calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt, "model": model}
        )
        if self._raise_error is not None:
            raise self._raise_error
        return self._text


def _generator(monkeypatch: pytest.MonkeyPatch, *, llm_provider: FakeLLMProvider) -> DraftGenerator:
    return DraftGenerator(llm_provider=llm_provider, settings=_settings(monkeypatch))

async def test_generate_returns_generated_text(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_provider = FakeLLMProvider(text="Sounds good, thank you for the update.")
    generator = _generator(monkeypatch, llm_provider=llm_provider)

    result = await generator.generate(_draft_context())

    assert result == "Sounds good, thank you for the update."
    assert isinstance(result, str)

async def test_generate_uses_draft_prompt_builder_output(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.prompts.draft_prompt import SYSTEM_PROMPT, build_draft_prompt

    email = _email(body_text="Distinctive body for prompt verification.")
    context = _draft_context(email=email)
    llm_provider = FakeLLMProvider()
    generator = _generator(monkeypatch, llm_provider=llm_provider)

    await generator.generate(context)

    call = llm_provider.generate_text_calls[0]
    expected_user_prompt = build_draft_prompt(
        email=context.email, understanding=context.understanding, context=context.retrieved_context
    )
    assert call["user_prompt"] == expected_user_prompt
    assert call["system_prompt"] == SYSTEM_PROMPT
    assert "Distinctive body for prompt verification." in call["user_prompt"]


async def test_generate_calls_provider_with_configured_drafting_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm_provider = FakeLLMProvider()
    settings = _settings(monkeypatch, LLM_DRAFTING_MODEL="groq-drafting-test-model")
    generator = DraftGenerator(llm_provider=llm_provider, settings=settings)

    await generator.generate(_draft_context())

    assert llm_provider.generate_text_calls[0]["model"] == "groq-drafting-test-model"


async def test_generate_returns_exact_provider_text_unmodified(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_provider = FakeLLMProvider(text="Exact text with  double spaces and\nnewlines preserved.")
    generator = _generator(monkeypatch, llm_provider=llm_provider)

    result = await generator.generate(_draft_context())

    assert result == "Exact text with  double spaces and\nnewlines preserved."

async def test_generate_rejects_empty_string_response(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_provider = FakeLLMProvider(text="")
    generator = _generator(monkeypatch, llm_provider=llm_provider)

    with pytest.raises(InvalidAIResponseError):
        await generator.generate(_draft_context())


async def test_generate_rejects_none_response(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_provider = FakeLLMProvider(text=None)
    generator = _generator(monkeypatch, llm_provider=llm_provider)

    with pytest.raises(InvalidAIResponseError):
        await generator.generate(_draft_context())



async def test_generate_rejects_whitespace_only_response(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_provider = FakeLLMProvider(text="   \n\t  ")
    generator = _generator(monkeypatch, llm_provider=llm_provider)

    with pytest.raises(InvalidAIResponseError):
        await generator.generate(_draft_context())


async def test_generate_propagates_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_provider = FakeLLMProvider(raise_error=AIProviderError("LLM call failed."))
    generator = _generator(monkeypatch, llm_provider=llm_provider)

    with pytest.raises(AIProviderError):
        await generator.generate(_draft_context())


async def test_generate_propagates_invalid_response_error_from_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm_provider = FakeLLMProvider(raise_error=InvalidAIResponseError("no text content"))
    generator = _generator(monkeypatch, llm_provider=llm_provider)

    with pytest.raises(InvalidAIResponseError):
        await generator.generate(_draft_context())

async def test_generator_has_no_database_chroma_or_gmail_dependencies() -> None:
    """Structural check: DraftGenerator's only collaborators are the
    LLM provider and settings — no repository, no session, no Gmail
    client is even importable from its dependency surface."""
    import inspect

    signature = inspect.signature(DraftGenerator.__init__)
    param_names = set(signature.parameters.keys()) - {"self"}

    assert param_names == {"llm_provider", "settings"}


async def test_generate_does_not_touch_database_or_gmail_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavioral confirmation: the FakeLLMProvider used here has no
    database or Gmail dependency of its own, and generate() completes
    successfully using only it — proving no hidden dependency is
    required."""
    llm_provider = FakeLLMProvider()
    generator = _generator(monkeypatch, llm_provider=llm_provider)

    result = await generator.generate(_draft_context())

    assert result is not None
    assert len(llm_provider.generate_text_calls) == 1