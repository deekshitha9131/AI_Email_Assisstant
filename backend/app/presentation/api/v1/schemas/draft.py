from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums.draft_status import DraftStatus
from app.presentation.api.v1.schemas.email import EmailDetail


class DraftCreateRequest(BaseModel):

    email_id: UUID
    instructions: str | None = Field(default=None, max_length=2000)


class DraftUpdateRequest(BaseModel):
    body: str


class DraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email_id: UUID
    body: str
    status: DraftStatus
    created_at: datetime
    updated_at: datetime


class DraftReviewResponse(DraftResponse):
    email: EmailDetail


class DraftReviewListResponse(BaseModel):
    items: list[DraftReviewResponse]
    page: int
    page_size: int