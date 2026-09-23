from enum import StrEnum

from pydantic import BaseModel, Field

from app.presentation.api.v1.schemas.email import EmailDetail


class AutomationEmailQueryParams(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class AutomationEmailListResponse(BaseModel):
    items: list[EmailDetail]
    limit: int
    offset: int
    count: int


class AutomationPriority(StrEnum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class AutomationPriorityResponse(BaseModel):
    email_id: str
    priority: AutomationPriority
    urgency: str
    category: str
    reason: str
    confidence: float
    status: str = "classified"
