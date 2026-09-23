from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.infrastructure.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.infrastructure.database.models.email import EmailModel


class EmailAIUnderstandingModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "email_ai_understanding"

    email_id: Mapped[UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    urgency: Mapped[str] = mapped_column(String(32), nullable=False)
    sentiment: Mapped[str] = mapped_column(String(32), nullable=False)
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    follow_up_needed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    follow_up_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    follow_up_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    email: Mapped["EmailModel"] = relationship(back_populates="ai_understanding")  # noqa: F821
