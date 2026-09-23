from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.enums.follow_up_source import FollowUpSource
from app.domain.enums.follow_up_status import FollowUpStatus


class FollowUpResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    email_id: UUID
    thread_id: UUID
    due_at: datetime
    status: FollowUpStatus
    reason: str | None
    source: FollowUpSource
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    dismissed_at: datetime | None


class FollowUpSnoozeRequest(BaseModel):
    due_at: datetime

    @model_validator(mode="after")
    def validate_future_due_at(self) -> "FollowUpSnoozeRequest":
        if self.due_at.tzinfo is None or self.due_at.utcoffset() is None:
            raise ValueError("due_at must be timezone-aware")
        if self.due_at <= datetime.now(UTC):
            raise ValueError("due_at must be in the future")
        return self


class AutomationDueFollowUpResponse(BaseModel):
    follow_up_id: UUID
    email_id: UUID
    thread_id: UUID
    due_at: datetime
    reason: str | None
    status: FollowUpStatus


class AutomationFollowUpNotificationResponse(BaseModel):
    follow_up_id: UUID
    status: Literal["created", "already_notified"]