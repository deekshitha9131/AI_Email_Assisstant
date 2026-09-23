from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.application.services.follow_up_service import FollowUpService
from app.core.constants import OpenAPITags
from app.core.di_container import CurrentUser, get_follow_up_service
from app.presentation.api.v1.schemas.follow_up import (
    FollowUpResponse,
    FollowUpSnoozeRequest,
)

router = APIRouter(prefix="/follow-ups", tags=[OpenAPITags.NOTIFICATIONS])
FollowUpServiceDep = Annotated[FollowUpService, Depends(get_follow_up_service)]


@router.get("", response_model=list[FollowUpResponse])
async def list_follow_ups(
    current_user: CurrentUser, service: FollowUpServiceDep
) -> list[FollowUpResponse]:
    return [
        FollowUpResponse.model_validate(follow_up)
        for follow_up in await service.list(current_user)
    ]


@router.get("/{follow_up_id}", response_model=FollowUpResponse)
async def get_follow_up(
    current_user: CurrentUser,
    service: FollowUpServiceDep,
    follow_up_id: UUID,
) -> FollowUpResponse:
    return FollowUpResponse.model_validate(await service.get(current_user, follow_up_id))


@router.post("/{follow_up_id}/complete", response_model=FollowUpResponse)
async def complete_follow_up(
    current_user: CurrentUser,
    service: FollowUpServiceDep,
    follow_up_id: UUID,
) -> FollowUpResponse:
    return FollowUpResponse.model_validate(await service.complete(current_user, follow_up_id))


@router.post("/{follow_up_id}/dismiss", response_model=FollowUpResponse)
async def dismiss_follow_up(
    current_user: CurrentUser,
    service: FollowUpServiceDep,
    follow_up_id: UUID,
) -> FollowUpResponse:
    return FollowUpResponse.model_validate(await service.dismiss(current_user, follow_up_id))


@router.post("/{follow_up_id}/snooze", response_model=FollowUpResponse)
async def snooze_follow_up(
    current_user: CurrentUser,
    service: FollowUpServiceDep,
    follow_up_id: UUID,
    payload: FollowUpSnoozeRequest,
) -> FollowUpResponse:
    return FollowUpResponse.model_validate(
        await service.snooze(current_user, follow_up_id, due_at=payload.due_at)
    )