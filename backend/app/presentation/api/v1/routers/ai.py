from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.ai.providers.llm_provider import LLMProvider
from app.ai.schemas.ai_understanding import AIUnderstandingResult, Entity
from app.ai.services.understanding_service import AIUnderstandingService
from app.application.services.email_service import EmailService
from app.application.services.follow_up_service import FollowUpService
from app.core.config import Settings
from app.core.constants import OpenAPITags
from app.core.di_container import (
    CurrentUser,
    get_email_ai_understanding_repository,
    get_email_service,
    get_follow_up_service,
    get_llm_provider,
    get_settings_dependency,
    get_understanding_service,
)
from app.infrastructure.database.repositories.email_ai_understanding_repository import (
    EmailAIUnderstandingRepository,
)

router = APIRouter(prefix="/emails", tags=[OpenAPITags.AI_UNDERSTANDING])

EmailServiceDep = Annotated[EmailService, Depends(get_email_service)]
UnderstandingServiceDep = Annotated[AIUnderstandingService, Depends(get_understanding_service)]
AIRepositoryDep = Annotated[
    EmailAIUnderstandingRepository, Depends(get_email_ai_understanding_repository)
]
FollowUpServiceDep = Annotated[FollowUpService, Depends(get_follow_up_service)]
SettingsDep = Annotated[Settings, Depends(get_settings_dependency)]
LLMProviderDep = Annotated[LLMProvider, Depends(get_llm_provider)]


@router.post(
    "/{email_id}/analyze",
    summary="Analyze an email with AI",
    response_model=AIUnderstandingResult,
)
async def analyze_email(
    current_user: CurrentUser,
    email_id: UUID,
    email_service: EmailServiceDep,
    understanding_service: UnderstandingServiceDep,
    ai_repository: AIRepositoryDep,
    follow_up_service: FollowUpServiceDep,
) -> AIUnderstandingResult:
    email = await email_service.get_email(current_user, email_id)
    # Check if analysis already exists
    existing = await ai_repository.get_by_email_id(email.id)
    if existing is not None:
        result = AIUnderstandingResult(
            category=existing.category,
            intent=existing.intent,
            urgency=existing.urgency,
            sentiment=existing.sentiment,
            entities=[Entity(type=e['type'], value=e['value']) for e in existing.entities],
            summary=existing.summary,
            confidence=existing.confidence,
            follow_up_needed=existing.follow_up_needed,
            follow_up_date=existing.follow_up_date,
            follow_up_reason=existing.follow_up_reason,
        )
        await follow_up_service.create_from_ai(
            current_user,
            email.id,
            follow_up_needed=result.follow_up_needed,
            due_at=result.follow_up_date,
            reason=result.follow_up_reason,
        )
        return result
    result = await understanding_service.analyze_email(email)
    await ai_repository.upsert(email.id, result)
    await follow_up_service.create_from_ai(
        current_user,
        email.id,
        follow_up_needed=result.follow_up_needed,
        due_at=result.follow_up_date,
        reason=result.follow_up_reason,
    )
    return result


@router.post(
    "/generate",
    summary="Generate email content from prompt",
)
async def generate_email_content(
    current_user: CurrentUser,
    settings: SettingsDep,
    llm_provider: LLMProviderDep,
    to: str = "",
    subject: str = "",
    body: str = "",
    instructions: str = "",
) -> dict[str, str]:
    generated_text = await llm_provider.generate_text(
        system_prompt="You are a professional email writing assistant",
        user_prompt=(
            f"Generate a professional email. To: {to}. Subject: {subject}. "
            f"Body: {body}. Instructions: {instructions}"
        ),
        model=settings.llm_drafting_model,
    )
    lines = generated_text.strip().splitlines()
    return {
        "subject": lines[0].strip() if lines else "",
        "body": "\n".join(lines[1:]).strip() if len(lines) > 1 else "",
    }
