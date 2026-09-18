from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.application.services.compose_draft_service import ComposeDraftService
from app.core.constants import OpenAPITags
from app.core.di_container import CurrentUser, get_compose_draft_service
from app.presentation.api.v1.schemas.compose_draft import (
    ComposeDraftListResponse,
    ComposeDraftPayload,
    ComposeDraftResponse,
)

router = APIRouter(prefix="/compose-drafts", tags=[OpenAPITags.DRAFTS])
ComposeDraftServiceDep = Annotated[ComposeDraftService, Depends(get_compose_draft_service)]


@router.post("", response_model=ComposeDraftResponse, status_code=status.HTTP_201_CREATED)
async def create_compose_draft(
    current_user: CurrentUser,
    service: ComposeDraftServiceDep,
    payload: ComposeDraftPayload,
) -> ComposeDraftResponse:
    return ComposeDraftResponse.model_validate(
        await service.create(current_user, **payload.model_dump())
    )


@router.get("", response_model=ComposeDraftListResponse)
async def list_compose_drafts(
    current_user: CurrentUser,
    service: ComposeDraftServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> ComposeDraftListResponse:
    drafts = await service.list(current_user, page=page, page_size=page_size)
    return ComposeDraftListResponse(
        items=[ComposeDraftResponse.model_validate(draft) for draft in drafts],
        page=page,
        page_size=page_size,
    )


@router.get("/{draft_id}", response_model=ComposeDraftResponse)
async def get_compose_draft(
    current_user: CurrentUser,
    service: ComposeDraftServiceDep,
    draft_id: UUID,
) -> ComposeDraftResponse:
    return ComposeDraftResponse.model_validate(await service.get(current_user, draft_id))


@router.put("/{draft_id}", response_model=ComposeDraftResponse)
async def update_compose_draft(
    current_user: CurrentUser,
    service: ComposeDraftServiceDep,
    draft_id: UUID,
    payload: ComposeDraftPayload,
) -> ComposeDraftResponse:
    return ComposeDraftResponse.model_validate(
        await service.update(current_user, draft_id, **payload.model_dump())
    )


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_compose_draft(
    current_user: CurrentUser,
    service: ComposeDraftServiceDep,
    draft_id: UUID,
) -> Response:
    await service.delete(current_user, draft_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)