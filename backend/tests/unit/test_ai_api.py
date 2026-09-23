from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.schemas.ai_understanding import (
    AIUnderstandingResult,
    EmailCategory,
    EmailIntent,
    EmailSentiment,
    EmailUrgency,
)
from app.core.di_container import (
    get_current_user,
    get_email_ai_understanding_repository,
    get_email_service,
    get_follow_up_service,
    get_understanding_service,
)
from app.domain.entities.email import Email
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.ai import AIProviderError
from app.domain.exceptions.email import EmailNotFoundError


def _fake_current_user() -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        full_name="Test User",
        google_sub_id="sub-1",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _email(*, user_id, email_id=None) -> Email:
    return Email(
        id=email_id or uuid4(),
        thread_id=uuid4(),
        user_id=user_id,
        gmail_message_id="m1",
        sender="sender@example.com",
        recipients=["user@example.com"],
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


def _ai_result(**overrides) -> AIUnderstandingResult:
    defaults = dict(
        category=EmailCategory.TRAVEL,
        intent=EmailIntent.CANCELLATION,
        urgency=EmailUrgency.HIGH,
        sentiment=EmailSentiment.NEGATIVE,
        entities=[{"type": "organization", "value": "Delta Airlines"}],
        summary="Flight booking was cancelled.",
        confidence=0.94,
    )
    defaults.update(overrides)
    return AIUnderstandingResult(**defaults)


class FakeEmailService:
    def __init__(self, *, email: Email | None = None, raise_error: Exception | None = None) -> None:
        self._email = email
        self._raise_error = raise_error
        self.get_email_calls: list[tuple] = []

    async def get_email(self, user, email_id):
        self.get_email_calls.append((user.id, email_id))
        if self._raise_error is not None:
            raise self._raise_error
        return self._email


class FakeUnderstandingService:
    def __init__(
        self, *, result: AIUnderstandingResult | None = None, raise_error: Exception | None = None
    ) -> None:
        self._result = result or _ai_result()
        self._raise_error = raise_error
        self.analyze_email_calls: list[Email] = []

    async def analyze_email(self, email):
        self.analyze_email_calls.append(email)
        if self._raise_error is not None:
            raise self._raise_error
        return self._result


class FakeAIRepository:
    def __init__(self, *, existing=None) -> None:
        self.existing = existing
        self.get_calls: list = []
        self.upsert_calls: list[tuple] = []

    async def get_by_email_id(self, email_id):
        self.get_calls.append(email_id)
        return self.existing

    async def upsert(self, email_id, result):
        self.upsert_calls.append((email_id, result))
        return None


class FakeFollowUpService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def create_from_ai(self, user, email_id, *, follow_up_needed, due_at, reason):
        self.calls.append((user, email_id, follow_up_needed, due_at, reason))
        return None


@pytest.fixture
def user() -> User:
    return _fake_current_user()


def _override(
    app_no_lifespan: FastAPI,
    *,
    email_service,
    understanding_service,
    ai_repository,
    follow_up_service=None,
    current_user=True,
):
    app_no_lifespan.dependency_overrides[get_email_service] = lambda: email_service
    app_no_lifespan.dependency_overrides[get_understanding_service] = lambda: understanding_service
    app_no_lifespan.dependency_overrides[get_email_ai_understanding_repository] = (
        lambda: ai_repository
    )
    app_no_lifespan.dependency_overrides[get_follow_up_service] = (
        lambda: follow_up_service or FakeFollowUpService()
    )
    if current_user is True:
        app_no_lifespan.dependency_overrides[get_current_user] = _fake_current_user
    elif current_user is False:
        app_no_lifespan.dependency_overrides.pop(get_current_user, None)
    elif isinstance(current_user, User):
        app_no_lifespan.dependency_overrides[get_current_user] = lambda: current_user
    else:
        app_no_lifespan.dependency_overrides[get_current_user] = current_user


def test_analyze_email_returns_ai_understanding_for_own_email(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    email = _email(user_id=user.id)
    result = _ai_result(summary="Distinctive summary text.")
    email_service = FakeEmailService(email=email)
    understanding_service = FakeUnderstandingService(result=result)
    ai_repository = FakeAIRepository()
    _override(
        app_no_lifespan,
        email_service=email_service,
        understanding_service=understanding_service,
        ai_repository=ai_repository,
    )

    response = unit_client.post(f"/api/v1/emails/{email.id}/analyze")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "Distinctive summary text."
    assert body["category"] == "travel"
    assert body["confidence"] == 0.94


def test_analyze_email_creates_follow_up_when_ai_requires_one(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    email = _email(user_id=user.id)
    result = _ai_result(
        follow_up_needed=True,
        follow_up_date=datetime(2026, 9, 25, 10, tzinfo=UTC),
        follow_up_reason="Check whether the cancellation was resolved.",
    )
    follow_up_service = FakeFollowUpService()
    _override(
        app_no_lifespan,
        email_service=FakeEmailService(email=email),
        understanding_service=FakeUnderstandingService(result=result),
        ai_repository=FakeAIRepository(),
        follow_up_service=follow_up_service,
        current_user=user,
    )

    response = unit_client.post(f"/api/v1/emails/{email.id}/analyze")

    assert response.status_code == 200
    assert follow_up_service.calls == [
        (
            user,
            email.id,
            True,
            datetime(2026, 9, 25, 10, tzinfo=UTC),
            "Check whether the cancellation was resolved.",
        )
    ]


def test_analyze_email_skips_follow_up_when_ai_does_not_require_one(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    email = _email(user_id=user.id)
    follow_up_service = FakeFollowUpService()
    _override(
        app_no_lifespan,
        email_service=FakeEmailService(email=email),
        understanding_service=FakeUnderstandingService(result=_ai_result()),
        ai_repository=FakeAIRepository(),
        follow_up_service=follow_up_service,
        current_user=user,
    )

    response = unit_client.post(f"/api/v1/emails/{email.id}/analyze")

    assert response.status_code == 200
    assert follow_up_service.calls == [
        (user, email.id, False, None, None)
    ]


def test_analyze_email_skips_follow_up_when_required_date_is_missing(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    email = _email(user_id=user.id)
    follow_up_service = FakeFollowUpService()
    _override(
        app_no_lifespan,
        email_service=FakeEmailService(email=email),
        understanding_service=FakeUnderstandingService(
            result=_ai_result(follow_up_needed=True, follow_up_date=None)
        ),
        ai_repository=FakeAIRepository(),
        follow_up_service=follow_up_service,
        current_user=user,
    )

    response = unit_client.post(f"/api/v1/emails/{email.id}/analyze")

    assert response.status_code == 200
    assert follow_up_service.calls == [(user, email.id, True, None, None)]


def test_repeated_analysis_uses_existing_follow_up_safely(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    email = _email(user_id=user.id)
    stored = SimpleNamespace(
        category="travel",
        intent="cancellation",
        urgency="high",
        sentiment="negative",
        entities=[],
        summary="Flight booking was cancelled.",
        confidence=0.94,
        follow_up_needed=True,
        follow_up_date=datetime(2026, 9, 25, 10, tzinfo=UTC),
        follow_up_reason="Check whether the cancellation was resolved.",
    )
    follow_up_service = FakeFollowUpService()
    _override(
        app_no_lifespan,
        email_service=FakeEmailService(email=email),
        understanding_service=FakeUnderstandingService(),
        ai_repository=FakeAIRepository(existing=stored),
        follow_up_service=follow_up_service,
    )

    response = unit_client.post(f"/api/v1/emails/{email.id}/analyze")

    assert response.status_code == 200
    assert follow_up_service.calls == [
        (
            user,
            email.id,
            True,
            datetime(2026, 9, 25, 10, tzinfo=UTC),
            "Check whether the cancellation was resolved.",
        )
    ]


def test_analyze_email_requires_authentication(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    email_service = FakeEmailService(email=_email(user_id=uuid4()))
    understanding_service = FakeUnderstandingService()
    ai_repository = FakeAIRepository()
    _override(
        app_no_lifespan,
        email_service=email_service,
        understanding_service=understanding_service,
        ai_repository=ai_repository,
        current_user=False,
    )

    response = unit_client.post(f"/api/v1/emails/{uuid4()}/analyze")

    assert response.status_code == 401


def test_analyze_email_returns_404_for_nonexistent_email(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    email_service = FakeEmailService(raise_error=EmailNotFoundError("No email found."))
    understanding_service = FakeUnderstandingService()
    ai_repository = FakeAIRepository()
    _override(
        app_no_lifespan,
        email_service=email_service,
        understanding_service=understanding_service,
        ai_repository=ai_repository,
    )

    response = unit_client.post(f"/api/v1/emails/{uuid4()}/analyze")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EMAIL_NOT_FOUND"
    # AI service must never be reached for an email the user doesn't own.
    assert understanding_service.analyze_email_calls == []


def test_analyze_email_returns_404_for_another_users_email(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    """Same 404 as a genuinely missing email — EmailService.get_email
    already raises the identical EmailNotFoundError for both cases, so
    the router has no way (and no need) to distinguish them."""
    email_service = FakeEmailService(raise_error=EmailNotFoundError("No email found."))
    understanding_service = FakeUnderstandingService()
    ai_repository = FakeAIRepository()
    _override(
        app_no_lifespan,
        email_service=email_service,
        understanding_service=understanding_service,
        ai_repository=ai_repository,
    )

    response = unit_client.post(f"/api/v1/emails/{uuid4()}/analyze")

    assert response.status_code == 404


def test_analyze_email_calls_ai_service_with_the_looked_up_email(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    email = _email(user_id=user.id)
    email_service = FakeEmailService(email=email)
    understanding_service = FakeUnderstandingService()
    ai_repository = FakeAIRepository()
    _override(
        app_no_lifespan,
        email_service=email_service,
        understanding_service=understanding_service,
        ai_repository=ai_repository,
    )

    unit_client.post(f"/api/v1/emails/{email.id}/analyze")

    assert understanding_service.analyze_email_calls == [email]


def test_analyze_email_persists_result_via_repository(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    email = _email(user_id=user.id)
    result = _ai_result()
    email_service = FakeEmailService(email=email)
    understanding_service = FakeUnderstandingService(result=result)
    ai_repository = FakeAIRepository()
    _override(
        app_no_lifespan,
        email_service=email_service,
        understanding_service=understanding_service,
        ai_repository=ai_repository,
    )

    unit_client.post(f"/api/v1/emails/{email.id}/analyze")

    assert ai_repository.upsert_calls == [(email.id, result)]


def test_analyze_email_response_matches_ai_understanding_schema(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    email = _email(user_id=user.id)
    result = _ai_result(
        entities=[
            {"type": "organization", "value": "Delta Airlines"},
            {"type": "date", "value": "August 15"},
        ]
    )
    email_service = FakeEmailService(email=email)
    understanding_service = FakeUnderstandingService(result=result)
    ai_repository = FakeAIRepository()
    _override(
        app_no_lifespan,
        email_service=email_service,
        understanding_service=understanding_service,
        ai_repository=ai_repository,
    )

    response = unit_client.post(f"/api/v1/emails/{email.id}/analyze")

    body = response.json()
    assert set(body.keys()) == {
        "category",
        "intent",
        "urgency",
        "sentiment",
        "entities",
        "summary",
        "confidence",
    }
    assert body["entities"] == [
        {"type": "organization", "value": "Delta Airlines"},
        {"type": "date", "value": "August 15"},
    ]
    # Nothing from the LLM/provider layer ever leaks into the response.
    assert "prompt" not in body
    assert "provider" not in body
    assert "raw_response" not in body


def test_ai_service_failure_returns_upstream_error_status(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    email = _email(user_id=user.id)
    email_service = FakeEmailService(email=email)
    understanding_service = FakeUnderstandingService(
        raise_error=AIProviderError("LLM provider request failed.")
    )
    ai_repository = FakeAIRepository()
    _override(
        app_no_lifespan,
        email_service=email_service,
        understanding_service=understanding_service,
        ai_repository=ai_repository,
    )

    response = unit_client.post(f"/api/v1/emails/{email.id}/analyze")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_PROVIDER_ERROR"
    # A failed analysis must never be persisted.
    assert ai_repository.upsert_calls == []


def test_repeated_analysis_calls_upsert_each_time_without_duplicate_creation(
    app_no_lifespan: FastAPI, unit_client: TestClient, user: User
) -> None:
    email = _email(user_id=user.id)
    email_service = FakeEmailService(email=email)
    understanding_service = FakeUnderstandingService(result=_ai_result())
    ai_repository = FakeAIRepository()
    _override(
        app_no_lifespan,
        email_service=email_service,
        understanding_service=understanding_service,
        ai_repository=ai_repository,
    )

    unit_client.post(f"/api/v1/emails/{email.id}/analyze")
    unit_client.post(f"/api/v1/emails/{email.id}/analyze")

    assert len(ai_repository.upsert_calls) == 2
    assert all(call[0] == email.id for call in ai_repository.upsert_calls)
