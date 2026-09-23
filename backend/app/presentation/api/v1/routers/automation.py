import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.ai.services.understanding_service import AIUnderstandingService
from app.application.services.draft_service import DraftService
from app.application.services.email_service import EmailService
from app.application.services.follow_up_service import FollowUpService
from app.application.services.gmail_service import GmailService
from app.application.services.notification_service import NotificationService
from app.core.di_container import (
    AutomationUser,
    get_draft_service,
    get_email_ai_understanding_repository,
    get_email_service,
    get_follow_up_service,
    get_gmail_service,
    get_notification_service,
    get_redis,
    get_understanding_service,
)
from app.domain.exceptions.ai import PriorityNotClassifiedError
from app.domain.exceptions.automation import AutomationAPIError
from app.domain.exceptions.base import DomainError
from app.infrastructure.database.repositories.email_ai_understanding_repository import (
    EmailAIUnderstandingRepository,
)
from app.presentation.api.v1.schemas.automation import (
    AutomationEmailListResponse,
    AutomationEmailQueryParams,
    AutomationPriority,
    AutomationPriorityResponse,
)
from app.presentation.api.v1.schemas.draft import DraftResponse
from app.presentation.api.v1.schemas.email import EmailDetail
from app.presentation.api.v1.schemas.follow_up import (
    AutomationDueFollowUpResponse,
    AutomationFollowUpNotificationResponse,
)
from app.presentation.api.v1.schemas.gmail import GmailIncrementalSyncResponse
from app.presentation.api.v1.schemas.notification import HighPriorityNotificationResponse

router = APIRouter(prefix="/automation", tags=["Automation"])


class AutomationStatusSnapshot(BaseModel):
    status: Literal["ok", "degraded", "error", "unknown"] = "unknown"
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_error: str | None = None


def _automation_status_key(user_id: UUID) -> str:
    return f"automation:status:{user_id}"


async def _read_automation_status_snapshot(
    redis_client, user_id: UUID
) -> AutomationStatusSnapshot | None:
    if redis_client is None:
        return None
    value = await redis_client.get(_automation_status_key(user_id))
    if value is None:
        return None
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return AutomationStatusSnapshot.model_validate(payload)


async def _run_automation_step(action: str, callback):
    try:
        return await callback()
    except DomainError:
        raise
    except Exception as exc:  # pragma: no cover - exercised via endpoint tests
        raise AutomationAPIError(f"Automation request failed while {action}.") from exc


GmailServiceDep = Annotated[GmailService, Depends(get_gmail_service)]
EmailServiceDep = Annotated[EmailService, Depends(get_email_service)]
AIRepositoryDep = Annotated[
    EmailAIUnderstandingRepository, Depends(get_email_ai_understanding_repository)
]
FollowUpServiceDep = Annotated[FollowUpService, Depends(get_follow_up_service)]
UnderstandingServiceDep = Annotated[
    AIUnderstandingService, Depends(get_understanding_service)
]
DraftServiceDep = Annotated[DraftService, Depends(get_draft_service)]
NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]


@router.get(
    "/follow-ups/due",
    summary="List due follow-ups for n8n",
    response_model=list[AutomationDueFollowUpResponse],
)
async def list_due_follow_ups(
    automation_user: AutomationUser,
    follow_up_service: FollowUpServiceDep,
    limit: int = Query(default=25, ge=1, le=100),
) -> list[AutomationDueFollowUpResponse]:
    due_follow_ups = await _run_automation_step(
        "listing due follow-ups",
        lambda: follow_up_service.list_due(automation_user, limit=limit),
    )
    return [
        AutomationDueFollowUpResponse(
            follow_up_id=follow_up.id,
            email_id=follow_up.email_id,
            thread_id=follow_up.thread_id,
            due_at=follow_up.due_at,
            reason=follow_up.reason,
            status=follow_up.status,
        )
        for follow_up in due_follow_ups
    ]


@router.post(
    "/follow-ups/{follow_up_id}/notify",
    summary="Notify for a due follow-up",
    response_model=AutomationFollowUpNotificationResponse,
)
async def notify_follow_up(
    automation_user: AutomationUser,
    follow_up_id: UUID,
    follow_up_service: FollowUpServiceDep,
    notification_service: NotificationServiceDep,
) -> AutomationFollowUpNotificationResponse:
    follow_up, created = await _run_automation_step(
        "notifying the follow-up",
        lambda: follow_up_service.notify(
            automation_user,
            follow_up_id,
            notification_service=notification_service,
        ),
    )
    return AutomationFollowUpNotificationResponse(
        follow_up_id=follow_up.id,
        status="created" if created else "already_notified",
    )


@router.post(
    "/gmail/sync/incremental",
    summary="Run incremental Gmail sync for n8n",
    response_model=GmailIncrementalSyncResponse,
)
async def sync_incremental(
    automation_user: AutomationUser,
    gmail_service: GmailServiceDep,
) -> GmailIncrementalSyncResponse:
    summary = await _run_automation_step(
        "syncing Gmail incrementally",
        lambda: gmail_service.sync_incremental(automation_user),
    )
    return GmailIncrementalSyncResponse.model_validate(summary)


@router.get(
    "/emails/unprocessed",
    summary="List emails without AI understanding for n8n",
    response_model=AutomationEmailListResponse,
)
async def list_unprocessed_emails(
    automation_user: AutomationUser,
    email_service: EmailServiceDep,
    ai_repository: AIRepositoryDep,
    params: Annotated[AutomationEmailQueryParams, Depends()],
) -> AutomationEmailListResponse:
    email_ids = await _run_automation_step(
        "listing unprocessed emails",
        lambda: ai_repository.list_unprocessed_email_ids(
            automation_user.id,
            limit=params.limit,
            offset=params.offset,
        ),
    )

    async def _fetch_emails() -> list[EmailDetail]:
        emails = []
        for email_id in email_ids:
            emails.append(await email_service.get_email(automation_user, email_id))
        return [EmailDetail.model_validate(email) for email in emails]

    email_details = await _run_automation_step("fetching unprocessed emails", _fetch_emails)
    return AutomationEmailListResponse(
        items=email_details,
        limit=params.limit,
        offset=params.offset,
        count=len(email_details),
    )


@router.post(
    "/emails/{email_id}/analyze",
    summary="Analyze an email with AI for n8n",
    response_model=dict[str, str],
)
async def analyze_email(
    automation_user: AutomationUser,
    email_id: UUID,
    email_service: EmailServiceDep,
    understanding_service: UnderstandingServiceDep,
    ai_repository: AIRepositoryDep,
    follow_up_service: FollowUpServiceDep,
) -> dict[str, str]:
    email = await _run_automation_step(
        "loading the email for analysis",
        lambda: email_service.get_email(automation_user, email_id),
    )
    existing = await _run_automation_step(
        "checking for an existing AI understanding record",
        lambda: ai_repository.get_by_email_id(email.id),
    )
    if existing is not None:
        await _run_automation_step(
            "creating follow-up state from existing AI analysis",
            lambda: follow_up_service.create_from_ai(
                automation_user,
                email.id,
                follow_up_needed=existing.follow_up_needed,
                due_at=existing.follow_up_date,
                reason=existing.follow_up_reason,
            ),
        )
        return {"email_id": str(email.id), "status": "already_processed"}

    result = await _run_automation_step(
        "analyzing the email with AI",
        lambda: understanding_service.analyze_email(email),
    )
    await _run_automation_step(
        "persisting AI analysis",
        lambda: ai_repository.upsert(email.id, result),
    )
    await _run_automation_step(
        "creating follow-up state from the new AI analysis",
        lambda: follow_up_service.create_from_ai(
            automation_user,
            email.id,
            follow_up_needed=result.follow_up_needed,
            due_at=result.follow_up_date,
            reason=result.follow_up_reason,
        ),
    )
    return {"email_id": str(email.id), "status": "processed"}


def _priority_from_urgency(urgency: str) -> AutomationPriority:
    if urgency in {"critical", "high"}:
        return AutomationPriority.HIGH
    if urgency == "low":
        return AutomationPriority.LOW
    return AutomationPriority.NORMAL


@router.post(
    "/status",
    summary="Persist the latest automation run result for this n8n automation user",
    response_model=AutomationStatusSnapshot,
)
async def update_automation_status(
    automation_user: AutomationUser,
    redis_client=Depends(get_redis),
    payload: AutomationStatusSnapshot = None,
) -> AutomationStatusSnapshot:
    if payload is None:
        payload = AutomationStatusSnapshot()
    key = _automation_status_key(automation_user.id)
    await redis_client.set(key, json.dumps(payload.model_dump(mode="json")))
    return payload


@router.get(
    "/emails/{email_id}/priority",
    summary="Get an analyzed email priority for n8n routing",
    response_model=AutomationPriorityResponse,
)
async def get_email_priority(
    automation_user: AutomationUser,
    email_id: UUID,
    email_service: EmailServiceDep,
    ai_repository: AIRepositoryDep,
) -> AutomationPriorityResponse:
    email = await _run_automation_step(
        "loading the email for priority routing",
        lambda: email_service.get_email(automation_user, email_id),
    )
    understanding = await _run_automation_step(
        "loading AI classification for the email",
        lambda: ai_repository.get_by_email_id(email.id),
    )
    if understanding is None:
        raise PriorityNotClassifiedError(
            "Analyze the email before requesting its priority."
        )
    return AutomationPriorityResponse(
        email_id=str(email.id),
        priority=_priority_from_urgency(understanding.urgency),
        urgency=understanding.urgency,
        category=understanding.category,
        reason=understanding.summary,
        confidence=understanding.confidence,
    )


@router.post(
    "/emails/{email_id}/notifications/high-priority",
    summary="Create a high-priority notification for n8n",
    response_model=HighPriorityNotificationResponse,
)
async def create_high_priority_notification(
    automation_user: AutomationUser,
    email_id: UUID,
    notification_service: NotificationServiceDep,
) -> HighPriorityNotificationResponse:
    _notification, created = await _run_automation_step(
        "creating the high-priority notification",
        lambda: notification_service.create_high_priority_for_email(automation_user, email_id),
    )
    return HighPriorityNotificationResponse(
        email_id=email_id,
        status="created" if created else "already_exists",
    )


@router.post(
    "/emails/{email_id}/draft",
    summary="Generate an AI draft reply for n8n",
    response_model=DraftResponse,
    status_code=201,
)
async def create_draft(
    automation_user: AutomationUser,
    email_id: UUID,
    email_service: EmailServiceDep,
    draft_service: DraftServiceDep,
) -> DraftResponse:
    email = await _run_automation_step(
        "loading the email for draft creation",
        lambda: email_service.get_email(automation_user, email_id),
    )
    draft = await _run_automation_step(
        "creating the draft response",
        lambda: draft_service.create_draft(automation_user, email.id),
    )
    return DraftResponse.model_validate(draft)
