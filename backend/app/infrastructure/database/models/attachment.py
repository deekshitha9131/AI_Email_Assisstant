from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.infrastructure.database.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.infrastructure.database.models.email import EmailModel


class AttachmentModel(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint(
            "email_id", "gmail_attachment_id", name="uq_attachments_email_id_gmail_attachment_id"
        ),
    )

    email_id: Mapped[UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gmail_attachment_id: Mapped[str] = mapped_column(Text(), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    email: Mapped["EmailModel"] = relationship(back_populates="attachments")  # noqa: F821
