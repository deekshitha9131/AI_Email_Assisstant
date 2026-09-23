from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.dto.gmail import ParsedEmail
from app.domain.entities.email import Attachment, Email
from app.domain.exceptions.email import EmailAlreadyExistsError, EmailNotFoundError
from app.infrastructure.database.models.attachment import AttachmentModel
from app.infrastructure.database.models.email import EmailModel
from app.infrastructure.database.models.thread import ThreadModel

_UNREAD_LABEL = "UNREAD"
_STARRED_LABEL = "STARRED"

SortOrder = Literal["newest", "oldest"]


def _to_entity(model: EmailModel) -> Email:
    return Email(
        id=model.id,
        thread_id=model.thread_id,
        user_id=model.user_id,
        gmail_message_id=model.gmail_message_id,
        sender=model.sender,
        recipients=list(model.recipients),
        cc=list(model.cc),
        bcc=list(model.bcc),
        subject=model.subject,
        snippet=model.snippet,
        body_text=model.body_text,
        body_html=model.body_html,
        received_at=model.received_at,
        is_read=model.is_read,
        is_starred=model.is_starred,
        has_attachments=model.has_attachments,
        label_ids=list(model.label_ids),
        created_at=model.created_at,
        updated_at=model.updated_at,
        attachments=[
            Attachment(
                id=attachment.id,
                email_id=attachment.email_id,
                gmail_attachment_id=attachment.gmail_attachment_id,
                filename=attachment.filename,
                mime_type=attachment.mime_type,
                size=attachment.size,
            )
            for attachment in model.attachments
        ],
    )


def _apply_filters(
    stmt: Any,
    *,
    user_id: UUID,
    is_read: bool | None,
    is_starred: bool | None,
    has_attachments: bool | None,
) -> Any:

    stmt = stmt.where(EmailModel.user_id == user_id)
    if is_read is not None:
        stmt = stmt.where(EmailModel.is_read == is_read)
    if is_starred is not None:
        stmt = stmt.where(EmailModel.is_starred == is_starred)
    if has_attachments is not None:
        stmt = stmt.where(EmailModel.has_attachments == has_attachments)
    return stmt


def _apply_search(stmt: Any, *, user_id: UUID, query: str) -> Any:

    pattern = f"%{query}%"
    return stmt.where(
        EmailModel.user_id == user_id,
        or_(
            EmailModel.sender.ilike(pattern),
            EmailModel.subject.ilike(pattern),
            EmailModel.snippet.ilike(pattern),
            EmailModel.body_text.ilike(pattern),
        ),
    )


class EmailRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_model_or_raise(self, email_id: UUID) -> EmailModel:
        stmt = select(EmailModel).where(EmailModel.id == email_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise EmailNotFoundError(f"No email found with id {email_id}.")
        return model

    async def get_by_id(self, email_id: UUID) -> Email | None:
        stmt = (
            select(EmailModel)
            .options(selectinload(EmailModel.attachments))
            .where(EmailModel.id == email_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def get_by_gmail_message_id(self, user_id: UUID, gmail_message_id: str) -> Email | None:
        stmt = (
            select(EmailModel)
            .options(selectinload(EmailModel.attachments))
            .where(EmailModel.user_id == user_id, EmailModel.gmail_message_id == gmail_message_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def get_by_gmail_thread_id(self, user_id: UUID, gmail_thread_id: str) -> list[Email]:
        stmt = (
            select(EmailModel)
            .options(selectinload(EmailModel.attachments))
            .join(ThreadModel, EmailModel.thread_id == ThreadModel.id)
            .where(EmailModel.user_id == user_id, ThreadModel.gmail_thread_id == gmail_thread_id)
            .order_by(EmailModel.received_at.asc())
        )
        result = await self._session.execute(stmt)
        return [_to_entity(model) for model in result.scalars().all()]

    async def get_by_user_id(
        self,
        user_id: UUID,
        *,
        page: int = 1,
        page_size: int = 25,
        sort: SortOrder = "newest",
        is_read: bool | None = None,
        is_starred: bool | None = None,
        has_attachments: bool | None = None,
    ) -> list[Email]:
        if page < 1:
            raise ValueError(f"page must be >= 1, got {page}")
        if page_size < 1:
            raise ValueError(f"page_size must be >= 1, got {page_size}")

        stmt = _apply_filters(
            select(EmailModel).options(selectinload(EmailModel.attachments)),
            user_id=user_id,
            is_read=is_read,
            is_starred=is_starred,
            has_attachments=has_attachments,
        )

        order_column = (
            EmailModel.received_at.desc() if sort == "newest" else EmailModel.received_at.asc()
        )
        stmt = stmt.order_by(order_column).limit(page_size).offset((page - 1) * page_size)

        result = await self._session.execute(stmt)
        return [_to_entity(model) for model in result.scalars().all()]

    async def get_by_user_id_for_list(
        self,
        user_id: UUID,
        *,
        page: int = 1,
        page_size: int = 25,
        sort: SortOrder = "newest",
        is_read: bool | None = None,
        is_starred: bool | None = None,
        has_attachments: bool | None = None,
    ) -> list[Email]:
        if page < 1:
            raise ValueError(f"page must be >= 1, got {page}")
        if page_size < 1:
            raise ValueError(f"page_size must be >= 1, got {page_size}")

        stmt = _apply_filters(
            select(EmailModel).options(selectinload(EmailModel.attachments)),
            user_id=user_id,
            is_read=is_read,
            is_starred=is_starred,
            has_attachments=has_attachments,
        )
        order_column = (
            EmailModel.received_at.desc() if sort == "newest" else EmailModel.received_at.asc()
        )
        stmt = stmt.order_by(order_column).limit(page_size).offset((page - 1) * page_size)

        result = await self._session.execute(stmt)
        return [_to_entity(model) for model in result.scalars().all()]

    async def count_by_user_id(
        self,
        user_id: UUID,
        *,
        is_read: bool | None = None,
        is_starred: bool | None = None,
        has_attachments: bool | None = None,
    ) -> int:
        stmt = _apply_filters(
            select(func.count()).select_from(EmailModel),
            user_id=user_id,
            is_read=is_read,
            is_starred=is_starred,
            has_attachments=has_attachments,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def search_by_user_id(
        self, user_id: UUID, *, query: str, page: int = 1, page_size: int = 25
    ) -> list[Email]:

        if page < 1:
            raise ValueError(f"page must be >= 1, got {page}")
        if page_size < 1:
            raise ValueError(f"page_size must be >= 1, got {page_size}")

        stmt = _apply_search(
            select(EmailModel).options(selectinload(EmailModel.attachments)),
            user_id=user_id,
            query=query,
        )
        stmt = (
            stmt.order_by(EmailModel.received_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )

        result = await self._session.execute(stmt)
        return [_to_entity(model) for model in result.scalars().all()]

    async def count_search_by_user_id(self, user_id: UUID, *, query: str) -> int:
        stmt = _apply_search(
            select(func.count()).select_from(EmailModel), user_id=user_id, query=query
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def create(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        gmail_message_id: str,
        sender: str,
        recipients: list[str],
        received_at: datetime,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        subject: str | None = None,
        snippet: str = "",
        body_text: str | None = None,
        body_html: str | None = None,
        is_read: bool = True,
        is_starred: bool = False,
        has_attachments: bool = False,
        label_ids: list[str] | None = None,
    ) -> Email:
        model = EmailModel(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id=gmail_message_id,
            sender=sender,
            recipients=recipients,
            cc=cc or [],
            bcc=bcc or [],
            subject=subject,
            snippet=snippet,
            body_text=body_text,
            body_html=body_html,
            received_at=received_at,
            is_read=is_read,
            is_starred=is_starred,
            has_attachments=has_attachments,
            label_ids=label_ids or [],
        )
        self._session.add(model)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise EmailAlreadyExistsError(
                f"An email with gmail_message_id {gmail_message_id!r} already "
                "exists for this user."
            ) from exc
        stmt = (
            select(EmailModel)
            .options(selectinload(EmailModel.attachments))
            .where(EmailModel.id == model.id)
        )
        result = await self._session.execute(stmt)
        saved_model = result.scalar_one()
        return _to_entity(saved_model)

    async def update(
        self, email_id: UUID, *, is_read: bool | None = None, is_starred: bool | None = None
    ) -> Email:
        model = await self._get_model_or_raise(email_id)
        if is_read is not None:
            model.is_read = is_read
        if is_starred is not None:
            model.is_starred = is_starred
        await self._session.commit()
        await self._session.refresh(model)
        stmt = (
            select(EmailModel)
            .options(selectinload(EmailModel.attachments))
            .where(EmailModel.id == model.id)
        )
        result = await self._session.execute(stmt)
        refreshed_model = result.scalar_one()
        return _to_entity(refreshed_model)

    async def delete(self, email_id: UUID) -> None:
        model = await self._get_model_or_raise(email_id)
        await self._session.delete(model)
        await self._session.commit()

    async def upsert(
        self, *, thread_id: UUID, user_id: UUID, parsed: ParsedEmail
    ) -> tuple[Email, bool]:
        stmt = select(EmailModel).where(
            EmailModel.user_id == user_id, EmailModel.gmail_message_id == parsed.gmail_message_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        was_created = model is None

        is_read = _UNREAD_LABEL not in parsed.label_ids
        is_starred = _STARRED_LABEL in parsed.label_ids

        if model is None:
            model = EmailModel(
                thread_id=thread_id,
                user_id=user_id,
                gmail_message_id=parsed.gmail_message_id,
                sender=parsed.sender,
                recipients=parsed.recipients,
                cc=parsed.cc,
                bcc=parsed.bcc,
                subject=parsed.subject,
                snippet=parsed.snippet,
                body_text=parsed.body_text,
                body_html=parsed.body_html,
                received_at=parsed.internal_date,
                is_read=is_read,
                is_starred=is_starred,
                has_attachments=parsed.has_attachments,
                label_ids=parsed.label_ids,
            )
            self._session.add(model)
        else:
            model.sender = parsed.sender
            model.recipients = parsed.recipients
            model.cc = parsed.cc
            model.bcc = parsed.bcc
            model.subject = parsed.subject
            model.snippet = parsed.snippet
            model.body_text = parsed.body_text
            model.body_html = parsed.body_html
            model.is_read = is_read
            model.is_starred = is_starred
            model.has_attachments = parsed.has_attachments
            model.label_ids = parsed.label_ids
            model.attachments.clear()

        for attachment in parsed.attachments:
            model.attachments.append(
                AttachmentModel(
                    gmail_attachment_id=attachment.attachment_id,
                    filename=attachment.filename,
                    mime_type=attachment.mime_type,
                    size=attachment.size,
                )
            )

        await self._session.commit()
        stmt = (
            select(EmailModel)
            .options(selectinload(EmailModel.attachments))
            .where(EmailModel.id == model.id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one()
        return _to_entity(model), was_created

    async def count_total(self, user_id: UUID) -> int:
        stmt = select(func.count()).select_from(EmailModel).where(EmailModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def count_unread(self, user_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(EmailModel)
            .where(EmailModel.user_id == user_id, EmailModel.is_read.is_(False))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def count_starred(self, user_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(EmailModel)
            .where(EmailModel.user_id == user_id, EmailModel.is_starred.is_(True))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()
