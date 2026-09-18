from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class ComposeDraft:
    id: UUID
    user_id: UUID
    recipients: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str
    body_text: str | None
    body_html: str | None
    created_at: datetime
    updated_at: datetime