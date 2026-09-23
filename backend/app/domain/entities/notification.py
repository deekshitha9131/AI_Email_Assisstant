from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Notification:
    id: UUID
    user_id: UUID
    email_id: UUID
    notification_type: str
    title: str
    message: str
    is_read: bool
    created_at: datetime
    follow_up_id: UUID | None = None
