from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums.follow_up_source import FollowUpSource
from app.domain.enums.follow_up_status import FollowUpStatus
from app.infrastructure.database.base import Base
from app.infrastructure.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class FollowUpModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "follow_ups"
    __table_args__ = (
        Index(
            "uq_follow_ups_active_email",
            "email_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'notified', 'snoozed')"),
        ),
        Index(
            "uq_follow_ups_active_thread",
            "thread_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'notified', 'snoozed')"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email_id: Mapped[UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False, index=True
    )
    thread_id: Mapped[UUID] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[FollowUpStatus] = mapped_column(
        SQLEnum(
            FollowUpStatus,
            name="follow_up_status",
            native_enum=True,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=FollowUpStatus.PENDING,
        server_default=FollowUpStatus.PENDING.value,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[FollowUpSource] = mapped_column(
        SQLEnum(
            FollowUpSource,
            name="follow_up_source",
            native_enum=True,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)