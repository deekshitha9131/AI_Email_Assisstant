from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.application.services.notification_service import NotificationService
from app.core.constants import OpenAPITags
from app.core.di_container import CurrentUser, get_notification_service
from app.presentation.api.v1.schemas.notification import (
    NotificationResponse,
    NotificationUnreadCountResponse,
)

router = APIRouter(prefix="/notifications", tags=[OpenAPITags.NOTIFICATIONS])
NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    current_user: CurrentUser, service: NotificationServiceDep
) -> list[NotificationResponse]:
    return [NotificationResponse.model_validate(notification) for notification in await service.list(current_user)]


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
async def unread_notification_count(
    current_user: CurrentUser, service: NotificationServiceDep
) -> NotificationUnreadCountResponse:
    return NotificationUnreadCountResponse(count=await service.unread_count(current_user))


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_as_read(
    current_user: CurrentUser, service: NotificationServiceDep, notification_id: UUID
) -> NotificationResponse:
    return NotificationResponse.model_validate(await service.mark_as_read(current_user, notification_id))
