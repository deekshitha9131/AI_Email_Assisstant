"""Tests for app/core/config.py's Settings validation.

Each test constructs Settings directly from an explicit dict (via
monkeypatched environment variables) rather than relying on a .env
file, so this suite is self-contained and doesn't depend on what
happens to be in the environment when pytest runs.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE_VALID_ENV = {
    "APP_ENV": "development",
    "APP_DEBUG": "true",
    "APP_SECRET_KEY": "dev-secret",
    "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
    "REDIS_URL": "redis://h:6379/0",
    "CELERY_BROKER_URL": "redis://h:6379/1",
    "CELERY_RESULT_BACKEND": "redis://h:6379/1",
    "TOKEN_ENCRYPTION_KEY": "dev-token-key-value",
    "CORS_ORIGINS": "http://localhost:5173",
    "N8N_AUTOMATION_TOKEN": "test-n8n-token",
    "N8N_AUTOMATION_USER_ID": "11111111-1111-1111-1111-111111111111",
}


def _build_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    env = {**BASE_VALID_ENV, **overrides}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_valid_development_config_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings(monkeypatch)
    assert settings.app_env == "development"
    assert settings.cors_origins == ["http://localhost:5173"]


def test_valid_production_config_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings(
        monkeypatch,
        APP_ENV="production",
        APP_DEBUG="false",
        APP_SECRET_KEY="a-real-production-secret",
        TOKEN_ENCRYPTION_KEY="a-real-production-token-key",
        GOOGLE_CLIENT_ID="a-real-google-client-id",
        GOOGLE_CLIENT_SECRET="a-real-google-client-secret",
        N8N_AUTOMATION_TOKEN="a-real-n8n-token",
        N8N_AUTOMATION_USER_ID="22222222-2222-2222-2222-222222222222",
    )
    assert settings.is_production is True


def test_production_requires_google_oauth_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _build_settings(
            monkeypatch,
            APP_ENV="production",
            APP_DEBUG="false",
            APP_SECRET_KEY="a-real-production-secret",
            TOKEN_ENCRYPTION_KEY="a-real-production-token-key",
            GOOGLE_CLIENT_ID="",
            GOOGLE_CLIENT_SECRET="",
        )


def test_invalid_app_env_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _build_settings(monkeypatch, APP_ENV="not-a-real-environment")


@pytest.mark.parametrize(
    "overrides",
    [
        {"APP_ENV": "production", "APP_DEBUG": "true"},
        {"APP_ENV": "production", "APP_SECRET_KEY": "change-me"},
        {"APP_ENV": "production", "TOKEN_ENCRYPTION_KEY": "change-me"},
        {"APP_ENV": "production", "TOKEN_ENCRYPTION_KEY": "short"},
    ],
)
def test_production_safety_checks_reject_unsafe_config(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str]
) -> None:
    with pytest.raises(ValidationError):
        _build_settings(monkeypatch, **overrides)


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("DATABASE_URL", "mysql://u:p@h/d"),
        ("REDIS_URL", "http://h:6379"),
        ("CELERY_BROKER_URL", "amqp://h:5672"),
    ],
)
def test_bad_url_schemes_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, bad_value: str
) -> None:
    with pytest.raises(ValidationError):
        _build_settings(monkeypatch, **{field: bad_value})


def test_empty_cors_origins_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _build_settings(monkeypatch, CORS_ORIGINS="   ")


@pytest.mark.parametrize(
    "field",
    ["DATABASE_POOL_SIZE", "DATABASE_POOL_TIMEOUT", "DATABASE_POOL_RECYCLE"],
)
def test_non_positive_pool_settings_rejected(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    with pytest.raises(ValidationError):
        _build_settings(monkeypatch, **{field: "0"})


def test_negative_max_overflow_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _build_settings(monkeypatch, DATABASE_MAX_OVERFLOW="-1")


def test_zero_max_overflow_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings(monkeypatch, DATABASE_MAX_OVERFLOW="0")
    assert settings.database_max_overflow == 0


def test_celery_soft_limit_must_be_less_than_hard_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _build_settings(
            monkeypatch,
            CELERY_TASK_TIME_LIMIT="100",
            CELERY_TASK_SOFT_TIME_LIMIT="100",
        )
