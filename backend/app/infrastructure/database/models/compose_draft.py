from uuid import UUID

from sqlalchemy import ARRAY, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ComposeDraftModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "compose_drafts"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipients: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    cc: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    bcc: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)