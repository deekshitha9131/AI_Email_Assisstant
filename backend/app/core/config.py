import os
from functools import lru_cache
from uuid import UUID

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ACTIVE_ENV = os.getenv("APP_ENV", "development")


# Use the shared file as the base and environment-specific values as local
# overrides. Compose injects backend/.env through the process environment, so
# those values still take precedence inside containers.
_ENV_FILES = (".env", f".env.{_ACTIVE_ENV}")


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=False, alias="APP_DEBUG")
    app_secret_key: str = Field(alias="APP_SECRET_KEY")

    # --- Database ---
    database_url: str = Field(alias="DATABASE_URL")
    database_pool_size: int = Field(default=10, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=5, alias="DATABASE_MAX_OVERFLOW")
    database_pool_timeout: int = Field(default=30, alias="DATABASE_POOL_TIMEOUT")
    database_pool_recycle: int = Field(default=1800, alias="DATABASE_POOL_RECYCLE")

    # --- Redis ---
    redis_url: str = Field(alias="REDIS_URL")
    celery_broker_url: str = Field(alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(alias="CELERY_RESULT_BACKEND")
    celery_task_time_limit: int = Field(default=300, alias="CELERY_TASK_TIME_LIMIT")
    celery_task_soft_time_limit: int = Field(default=240, alias="CELERY_TASK_SOFT_TIME_LIMIT")
    celery_max_retries: int = Field(default=3, alias="CELERY_MAX_RETRIES")
    celery_retry_backoff_max: int = Field(default=600, alias="CELERY_RETRY_BACKOFF_MAX")

    # --- Google OAuth ---
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(default="", alias="GOOGLE_REDIRECT_URI")

    # --- Frontend / session ---
    frontend_base_url: str = Field(
        default="http://localhost:5173",
        alias="FRONTEND_BASE_URL",
    )
    cors_origins_raw: str = Field(
        default="http://localhost:5173",
        alias="CORS_ORIGINS",
    )
    session_ttl_seconds: int = Field(
        default=604800,
        alias="SESSION_TTL_SECONDS",
    )  # 7 days

    # --- n8n automation ---
    n8n_automation_token: str = Field(default="", alias="N8N_AUTOMATION_TOKEN")
    n8n_automation_user_id: UUID | None = Field(default=None, alias="N8N_AUTOMATION_USER_ID")

    # --- Token encryption ---
    token_encryption_key: str = Field(alias="TOKEN_ENCRYPTION_KEY")

    # --- LLM provider ---
    llm_provider: str = Field(default="groq", alias="LLM_PROVIDER")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    llm_classification_model: str = Field(
        default="openai/gpt-oss-20b", alias="LLM_CLASSIFICATION_MODEL"
    )
    llm_drafting_model: str = Field(default="openai/gpt-oss-20b", alias="LLM_DRAFTING_MODEL")
    llm_critique_model: str = Field(default="openai/gpt-oss-20b", alias="LLM_CRITIQUE_MODEL")

    # --- Embeddings ---
    # Embeddings use a local sentence-transformers model (all-MiniLM-L6-v2).
    # No external API key is required.

    # --- Rate limiting ---
    rate_limit_per_minute: int = Field(default=60, alias="RATE_LIMIT_PER_MINUTE")

    # ------------------------------------------------------------------
    # Field-level validation
    # ------------------------------------------------------------------

    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, value: str) -> str:
        allowed = {"development", "staging", "production", "test"}
        if value not in allowed:
            raise ValueError(f"APP_ENV must be one of {allowed}, got {value!r}")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql"):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL connection string "
                f"(expected it to start with 'postgresql'), got: {value!r}"
            )
        return value

    @field_validator("redis_url", "celery_broker_url", "celery_result_backend")
    @classmethod
    def validate_redis_scheme(cls, value: str) -> str:
        if not value.startswith("redis://") and not value.startswith("rediss://"):
            raise ValueError(f"Expected a redis:// or rediss:// URL, got: {value!r}")
        return value

    @field_validator(
        "database_pool_size",
        "database_pool_timeout",
        "database_pool_recycle",
        "celery_task_time_limit",
        "celery_task_soft_time_limit",
        "celery_max_retries",
        "celery_retry_backoff_max",
        "session_ttl_seconds",
    )
    @classmethod
    def validate_positive(cls, value: int, info: ValidationInfo) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer, got {value}")
        return value

    @field_validator("database_max_overflow")
    @classmethod
    def validate_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError(f"DATABASE_MAX_OVERFLOW must be >= 0, got {value}")
        return value

    @field_validator("cors_origins_raw")
    @classmethod
    def validate_cors_origins_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CORS_ORIGINS must not be empty — the frontend origin is required.")
        return value

    @model_validator(mode="after")
    def validate_celery_time_limits(self) -> "Settings":
        if self.celery_task_soft_time_limit >= self.celery_task_time_limit:
            raise ValueError(
                "CELERY_TASK_SOFT_TIME_LIMIT must be less than CELERY_TASK_TIME_LIMIT "
                "— the soft limit exists to let a task clean up before the hard limit "
                "kills the worker process outright; if they're equal or inverted, "
                "the soft limit accomplishes nothing."
            )
        return self

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        if self.app_env != "production":
            return self

        if self.app_debug:
            raise ValueError("APP_DEBUG must be false when APP_ENV=production.")

        placeholder_values = {"change-me", ""}
        if self.app_secret_key in placeholder_values:
            raise ValueError("APP_SECRET_KEY must be set to a real secret in production.")
        if self.token_encryption_key in placeholder_values:
            raise ValueError("TOKEN_ENCRYPTION_KEY must be set to a real key in production.")
        if len(self.token_encryption_key) < 16:
            raise ValueError(
                "TOKEN_ENCRYPTION_KEY looks too short to be a real encryption key "
                f"(got {len(self.token_encryption_key)} characters)."
            )
        if not self.google_client_id or not self.google_client_secret:
            raise ValueError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in production "
                "— Google login cannot function without them."
            )
        if not self.n8n_automation_token:
            raise ValueError("N8N_AUTOMATION_TOKEN must be set in production.")
        if self.n8n_automation_user_id is None:
            raise ValueError("N8N_AUTOMATION_USER_ID must be set in production.")

        return self

    @property
    def cors_origins(self) -> list[str]:
        """Parsed CORS origin list, derived from the raw comma-separated env value."""
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
