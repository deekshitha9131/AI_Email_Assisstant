from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class EmailAIUnderstanding:
    id: UUID
    email_id: UUID
    category: str
    intent: str
    urgency: str
    sentiment: str
    entities: list[dict[str, str]]
    summary: str
    confidence: float
    follow_up_needed: bool
    follow_up_date: datetime | None
    follow_up_reason: str | None
    created_at: datetime
    updated_at: datetime
