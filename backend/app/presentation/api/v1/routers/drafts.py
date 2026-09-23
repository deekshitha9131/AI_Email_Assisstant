from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.application.services.draft_service import DraftService
from app.core.constants import OpenAPITags
from app.core.di_container import CurrentUser, get_draft_service
from app.presentation.api.v1.schemas.draft import (
    DraftCreateRequest,
    DraftResponse,
    DraftReviewListResponse,
    DraftReviewResponse,
    DraftUpdateRequest,
)
from app.presentation.api.v1.schemas.email import EmailDetail

router = APIRouter(prefix="/drafts", tags=[OpenAPITags.DRAFTS])

DraftServiceDep = Annotated[DraftService, Depends(get_draft_service)]


@router.get("", response_model=DraftReviewListResponse)
async def list_drafts(
    current_user: CurrentUser,
    draft_service: DraftServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> DraftReviewListResponse:
    reviews = await draft_service.list_drafts(current_user, page=page, page_size=page_size)
    return DraftReviewListResponse(
        items=[
            DraftReviewResponse(
                **DraftResponse.model_validate(draft).model_dump(),
                email=EmailDetail.model_validate(email),
            )
            for draft, email in reviews
        ],
        page=page,
        page_size=page_size,
    )

@router.post(
    "",
    summary="Generate a draft reply",
    description="Generates and persists an AI draft reply for one of the "
    "authenticated user's emails. Returns 404 if the email does not exist "
    "or belongs to another user, and 409 if the email has not been "
    "AI-analyzed yet (POST /emails/{email_id}/analyze first).",
    response_model=DraftResponse,
    status_code=201,
)
async def create_draft(
    current_user: CurrentUser,
    draft_service: DraftServiceDep,
    payload: DraftCreateRequest,
) -> DraftResponse:
    draft = await draft_service.create_draft(
        current_user, payload.email_id, instructions=payload.instructions
    )
    return DraftResponse.model_validate(draft)


@router.get(
    "/{draft_id}",
    summary="Get a draft",
    description="Returns a draft owned by the authenticated user. Returns "
    "404 if the draft does not exist or belongs to another user — the "
    "two cases are indistinguishable in the response, by design.",
    response_model=DraftResponse,
)
async def get_draft(
    current_user: CurrentUser,
    draft_service: DraftServiceDep,
    draft_id: UUID,
) -> DraftResponse:
    draft = await draft_service.get_draft(current_user, draft_id)
    return DraftResponse.model_validate(draft)


@router.patch(
    "/{draft_id}",
    summary="Update a draft",
    description="Updates the body of a draft owned by the authenticated user. "
    "Returns 404 if the draft does not exist or belongs to another user.",
    response_model=DraftResponse,
)
async def update_draft(
    current_user: CurrentUser,
    draft_service: DraftServiceDep,
    draft_id: UUID,
    payload: DraftUpdateRequest,
) -> DraftResponse:
    draft = await draft_service.update_draft(current_user, draft_id, payload.body)
    return DraftResponse.model_validate(draft)


@router.post(
    "/{draft_id}/approve",
    summary="Approve a draft",
    description="Approves a draft owned by the authenticated user, changing its status to 'approved'. "
    "Returns 404 if the draft does not exist or belongs to another user, and 409 if the draft is not in a generatable state.",
    response_model=DraftResponse,
)
async def approve_draft(
    current_user: CurrentUser,
    draft_service: DraftServiceDep,
    draft_id: UUID,
) -> DraftResponse:
    draft = await draft_service.approve_draft(current_user, draft_id)
    return DraftResponse.model_validate(draft)