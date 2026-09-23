from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums.follow_up_source import FollowUpSource
from app.domain.enums.follow_up_status import FollowUpStatus


@dataclass
class FollowUp:
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