import json
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
)
from pydantic import ValidationError

from app.ai.prompts.understanding_prompt import SYSTEM_PROMPT, build_user_prompt
from app.ai.schemas.ai_understanding import AIUnderstandingResult
from app.ai.schemas.preprocessing import PreprocessedEmail
from app.core.config import Settings
from app.domain.exceptions.ai import (
    AIAuthenticationError,
    AIConfigurationError,
    AIProviderError,
    AITimeoutError,
    InvalidAIResponseError,
)

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_MAX_RESPONSE_TOKENS = 2048
_MAX_DRAFT_RESPONSE_TOKENS = 768


class LLMProvider:
    """Provider boundary for user-triggered text and email understanding calls."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._settings.llm_provider.lower() != "groq":
            raise AIConfigurationError(
                f"Unsupported LLM_PROVIDER {self._settings.llm_provider!r}. Set LLM_PROVIDER=groq."
            )
        if not self._settings.groq_api_key:
            raise AIConfigurationError(
                "GROQ_API_KEY is not configured. Set it in the backend environment."
            )
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._settings.groq_api_key,
                base_url=_GROQ_BASE_URL,
            )
        return self._client

    async def _create_completion(self, **kwargs: Any) -> Any:
        try:
            return await self._get_client().chat.completions.create(**kwargs)
        except AuthenticationError as exc:
            raise AIAuthenticationError("The configured Groq API key was rejected.") from exc
        except APITimeoutError as exc:
            raise AITimeoutError("The Groq request timed out.") from exc
        except (APIConnectionError, APIStatusError) as exc:
            if isinstance(exc, APIStatusError):
                upstream_status = exc.status_code
                if upstream_status == 429:
                    raise AIProviderError(
                        "The Groq API rate limit has been exceeded. Please wait a moment and try again."
                    ) from exc
                if upstream_status == 400:
                    body = exc.body if isinstance(exc.body, dict) else {}
                    error_body = body.get("error") if isinstance(body, dict) else None
                    if isinstance(error_body, dict) and error_body.get("code") == "json_validate_failed":
                        raise InvalidAIResponseError(
                            "The AI provider could not produce valid structured output for this email."
                        ) from exc
                    raise AIProviderError(
                        "The Groq API rejected the request (400). The configured model "
                        "may not support the requested parameters."
                    ) from exc
                if upstream_status >= 500:
                    raise AIProviderError(
                        f"The Groq API returned a server error ({upstream_status}). "
                        "The service may be temporarily unavailable."
                    ) from exc
                raise AIProviderError(
                    f"The Groq API request failed with status {upstream_status}."
                ) from exc
            raise AIProviderError(
                "Could not connect to the Groq API. The service may be down or unreachable."
            ) from exc

    async def health_check(self) -> None:
        await self._create_completion(
            model=self._settings.llm_classification_model,
            max_tokens=8,
            messages=[
                {"role": "system", "content": "Reply with the single word READY."},
                {"role": "user", "content": "READY"},
            ],
        )

    async def understand_email(self, email: PreprocessedEmail) -> AIUnderstandingResult:
        response = await self._create_completion(
            model=self._settings.llm_classification_model,
            max_tokens=_MAX_RESPONSE_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(email)},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise InvalidAIResponseError("Model response did not include a JSON object.")
        try:
            return AIUnderstandingResult.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise InvalidAIResponseError("Model output failed JSON schema validation.") from exc

    async def generate_text(self, *, system_prompt: str, user_prompt: str, model: str) -> str:
        response = await self._create_completion(
            model=model,
            max_tokens=_MAX_DRAFT_RESPONSE_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if not content or not content.strip():
            raise InvalidAIResponseError("Model response did not include any text content.")
        return content
