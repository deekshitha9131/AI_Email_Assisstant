from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email_id: UUID
    follow_up_id: UUID | None = None
    notification_type: str
    title: str
    message: str
    is_read: bool
    created_at: datetime


class NotificationUnreadCountResponse(BaseModel):
    count: int


class HighPriorityNotificationResponse(BaseModel):
    email_id: UUID
    status: Literal["created", "already_exists"]
