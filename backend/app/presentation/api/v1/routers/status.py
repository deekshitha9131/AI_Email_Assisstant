"""Status endpoints for checking service connectivity."""

import time
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import OpenAPITags
from app.core.di_container import AppSettings, CurrentUser, get_llm_provider, get_user_repository
from app.ai.providers.llm_provider import LLMProvider
from app.infrastructure.database.repositories.user_repository import UserRepository
from app.infrastructure.database.repositories.draft_repository import DraftRepository
from app.infrastructure.database.session import get_db_session

router = APIRouter(prefix="/status", tags=[OpenAPITags.HEALTH])

_AI_STATUS_CACHE_SECONDS = 30.0
_ai_status_cache: tuple[float, dict[str, str]] | None = None


async def _check_ai_status(settings: Any, llm_provider: LLMProvider) -> dict[str, str]:
    global _ai_status_cache
    now = time.monotonic()
    if _ai_status_cache is not None and now - _ai_status_cache[0] < _AI_STATUS_CACHE_SECONDS:
        return _ai_status_cache[1]

    provider = settings.llm_provider
    if provider.lower() != "groq" or not settings.groq_api_key:
        result = {"status": "not_configured", "provider": provider}
    else:
        # Status checks must not spend tokens or make background provider calls.
        result = {
            "status": "available",
            "provider": provider,
            "model": settings.llm_classification_model,
        }

    _ai_status_cache = (now, result)
    return result


@router.get(
    "",
    summary="Get service status for the current user",
    description="Returns the connectivity status of Gmail, AI, and Draft services.",
)
async def get_service_status(
    current_user: CurrentUser,
    settings: AppSettings,
    db: AsyncSession = Depends(get_db_session),
    user_repository: UserRepository = Depends(get_user_repository),
    llm_provider: LLMProvider = Depends(get_llm_provider),
) -> dict[str, Any]:
    """Check the status of key services."""
    oauth_token = await user_repository.get_oauth_tokens(current_user.id)
    gmail_status = "disconnected" if oauth_token is None else (
        "expired" if oauth_token.is_expired else "connected"
    )
    ai_status = (await _check_ai_status(settings, llm_provider))["status"]

    try:
        await db.execute(text("SELECT 1"))
        DraftRepository(db)
        draft_status = "ready"
    except Exception:
        draft_status = "error"

    return {
        "gmail": gmail_status,
        "ai": ai_status,
        "draft": draft_status,
        "user": {
            "id": str(current_user.id),
            "email": current_user.email,
            "full_name": current_user.full_name,
        } if current_user else None,
    }


@router.get(
    "/gmail",
    summary="Check Gmail connection status",
    description="Verifies Gmail OAuth connection status for the current user.",
)
async def get_gmail_status(
    current_user: CurrentUser,
    user_repository: UserRepository = Depends(get_user_repository),
) -> dict[str, str]:
    """Check if user has valid Gmail OAuth connection."""
    oauth_token = await user_repository.get_oauth_tokens(current_user.id)
    if oauth_token is None:
        return {"status": "disconnected"}
    return {"status": "expired" if oauth_token.is_expired else "connected"}


@router.get(
    "/ai",
    summary="Check AI service status",
    description="Verifies AI/LLM service availability.",
)
async def get_ai_status(
    settings: AppSettings,
    llm_provider: LLMProvider = Depends(get_llm_provider),
) -> dict[str, str]:
    """Check if AI service is configured and available."""
    return await _check_ai_status(settings, llm_provider)


@router.get(
    "/draft",
    summary="Check draft service status",
    description="Verifies draft service operational status.",
)
async def get_draft_status(
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Check if draft service is operational."""
    try:
        await db.execute(text("SELECT 1"))
        DraftRepository(db)
        return {"status": "ready"}
    except Exception:
        return {"status": "error"}