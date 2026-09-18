from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ComposeDraftPayload(BaseModel):
    recipients: list[EmailStr] = Field(default_factory=list)
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)
    subject: str = Field(default="", max_length=998)
    body_text: str | None = None
    body_html: str | None = None

    @field_validator("recipients", "cc", "bcc", mode="before")
    @classmethod
    def normalize_recipients(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [item.strip() if isinstance(item, str) else item for item in value]


class ComposeDraftResponse(ComposeDraftPayload):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


class ComposeDraftListResponse(BaseModel):
    items: list[ComposeDraftResponse]
    page: int
    page_size: int
