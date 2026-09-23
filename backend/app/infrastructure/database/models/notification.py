from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.mixins import UUIDPrimaryKeyMixin


class NotificationModel(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "uq_notifications_email_type_without_follow_up",
            "user_id",
            "email_id",
            "notification_type",
            unique=True,
            postgresql_where=text("follow_up_id IS NULL"),
        ),
        Index(
            "uq_notifications_follow_up_type",
            "user_id",
            "follow_up_id",
            "notification_type",
            unique=True,
            postgresql_where=text("follow_up_id IS NOT NULL"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email_id: Mapped[UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False, index=True
    )
    follow_up_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("follow_ups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
