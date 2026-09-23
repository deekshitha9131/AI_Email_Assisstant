from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.ai.schemas.ai_understanding import (
    AIUnderstandingResult,
    EmailCategory,
    EmailIntent,
    EmailSentiment,
    EmailUrgency,
)
from app.ai.schemas.preprocessing import PreprocessedEmail
from app.ai.services.understanding_service import AIUnderstandingService
from app.domain.entities.email import Email
from app.domain.exceptions.ai import AIProviderError, InvalidAIResponseError


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


def _preprocessed_email(**overrides) -> PreprocessedEmail:
    defaults = dict(
        sender="jane@example.com",
        recipients=["bob@example.com"],
        subject="Flight Cancelled",
        body="Your flight has been cancelled.",
        truncated=False,
    )
    defaults.update(overrides)
    return PreprocessedEmail(**defaults)


def _ai_result(**overrides) -> AIUnderstandingResult:
    defaults = dict(
        category=EmailCategory.TRAVEL,
        intent=EmailIntent.CANCELLATION,
        urgency=EmailUrgency.HIGH,
        sentiment=EmailSentiment.NEGATIVE,
        entities=[],
        summary="Flight was cancelled.",
        confidence=0.9,
    )
    defaults.update(overrides)
    return AIUnderstandingResult(**defaults)


class FakePreprocessor:
    def __init__(
        self, *, result: PreprocessedEmail | None = None, raise_error: Exception | None = None
    ) -> None:
        self._result = result or _preprocessed_email()
        self._raise_error = raise_error
        self.preprocess_calls: list[Email] = []

    def preprocess(self, email: Email) -> PreprocessedEmail:
        self.preprocess_calls.append(email)
        if self._raise_error is not None:
            raise self._raise_error
        return self._result


class FakeLLMProvider:
    def __init__(
        self, *, result: AIUnderstandingResult | None = None, raise_error: Exception | None = None
    ) -> None:
        self._result = result or _ai_result()
        self._raise_error = raise_error
        self.understand_email_calls: list[PreprocessedEmail] = []

    async def understand_email(self, email: PreprocessedEmail) -> AIUnderstandingResult:
        self.understand_email_calls.append(email)
        if self._raise_error is not None:
            raise self._raise_error
        return self._result


async def test_email_is_passed_to_the_preprocessor() -> None:
    email = _email()
    preprocessor = FakePreprocessor()
    provider = FakeLLMProvider()
    service = AIUnderstandingService(preprocessor=preprocessor, llm_provider=provider)

    await service.analyze_email(email)

    assert preprocessor.preprocess_calls == [email]


async def test_preprocessed_result_is_passed_to_the_provider() -> None:
    email = _email()
    preprocessed = _preprocessed_email(subject="Distinctive Subject")
    preprocessor = FakePreprocessor(result=preprocessed)
    provider = FakeLLMProvider()
    service = AIUnderstandingService(preprocessor=preprocessor, llm_provider=provider)

    await service.analyze_email(email)

    assert provider.understand_email_calls == [preprocessed]


async def test_provider_result_is_returned_unchanged() -> None:
    email = _email()
    expected_result = _ai_result(summary="A very specific summary.")
    preprocessor = FakePreprocessor()
    provider = FakeLLMProvider(result=expected_result)
    service = AIUnderstandingService(preprocessor=preprocessor, llm_provider=provider)

    result = await service.analyze_email(email)

    assert result is expected_result


async def test_preprocessor_error_propagates() -> None:
    email = _email()
    preprocessor = FakePreprocessor(raise_error=ValueError("preprocessing blew up"))
    provider = FakeLLMProvider()
    service = AIUnderstandingService(preprocessor=preprocessor, llm_provider=provider)

    with pytest.raises(ValueError, match="preprocessing blew up"):
        await service.analyze_email(email)

    # The provider must never be reached if preprocessing itself failed.
    assert provider.understand_email_calls == []


async def test_provider_error_propagates() -> None:
    email = _email()
    preprocessor = FakePreprocessor()
    provider = FakeLLMProvider(raise_error=AIProviderError("LLM call failed"))
    service = AIUnderstandingService(preprocessor=preprocessor, llm_provider=provider)

    with pytest.raises(AIProviderError):
        await service.analyze_email(email)


async def test_invalid_ai_response_error_propagates() -> None:
    email = _email()
    preprocessor = FakePreprocessor()
    provider = FakeLLMProvider(raise_error=InvalidAIResponseError("malformed model output"))
    service = AIUnderstandingService(preprocessor=preprocessor, llm_provider=provider)

    with pytest.raises(InvalidAIResponseError):
        await service.analyze_email(email)


async def test_service_performs_no_database_operations() -> None:
    import inspect

    from app.ai.services.understanding_service import AIUnderstandingService as ServiceClass

    signature = inspect.signature(ServiceClass.__init__)
    param_names = set(signature.parameters.keys()) - {"self"}

    assert param_names == {"preprocessor", "llm_provider"}


def test_follow_up_required_with_date_is_valid() -> None:
    result = _ai_result(
        follow_up_needed=True,
        follow_up_date=datetime(2026, 8, 15, 9, tzinfo=UTC),
        follow_up_reason="Contact the airline after the cancellation.",
    )

    assert result.follow_up_needed is True
    assert result.follow_up_date == datetime(2026, 8, 15, 9, tzinfo=UTC)
    assert result.follow_up_reason == "Contact the airline after the cancellation."


def test_follow_up_not_required_defaults_to_no_date() -> None:
    result = _ai_result()

    assert result.follow_up_needed is False
    assert result.follow_up_date is None
    assert result.follow_up_reason is None


def test_follow_up_date_is_rejected_when_follow_up_is_not_needed() -> None:
    with pytest.raises(ValueError, match="follow_up_date must be null"):
        _ai_result(
            follow_up_needed=False,
            follow_up_date=datetime(2026, 8, 15, 9, tzinfo=UTC),
        )


def test_invalid_follow_up_date_is_rejected() -> None:
    with pytest.raises(ValueError):
        AIUnderstandingResult.model_validate(
            {
                "category": "travel",
                "intent": "cancellation",
                "urgency": "high",
                "sentiment": "negative",
                "entities": [],
                "summary": "Flight was cancelled.",
                "confidence": 0.9,
                "follow_up_needed": True,
                "follow_up_date": "not-a-datetime",
            }
        )
