"""EmailService.

Reads the locally stored inbox — the only Gmail-integration workflow
this service touches is none: it exists specifically so the API layer
never talks to EmailRepository (or SQLAlchemy) directly, and never
calls Gmail for a read that PostgreSQL can already answer. Per the
Phase 4 architecture, this is where "does this email belong to the
caller" is enforced — the repository itself is user-agnostic on
`get_by_id`, so ownership is a service-layer concern, not a data-access
one.

Task 4.3 adds `search_emails` — the query-validation step ("reject
empty/whitespace-only search") belongs here, not in the repository,
since it's a product/business rule about what counts as a meaningful
search request, not a data-access concern.
"""

from uuid import UUID

import structlog

from app.domain.entities.email import Email
from app.domain.entities.user import User
from app.domain.exceptions.email import EmailNotFoundError, InvalidSearchQueryError
from app.infrastructure.database.repositories.email_repository import EmailRepository, SortOrder

logger = structlog.get_logger(__name__)


class EmailService:
    def __init__(self, *, email_repository: EmailRepository) -> None:
        self._email_repository = email_repository

    async def list_emails(
        self,
        user: User,
        *,
        page: int,
        page_size: int,
        sort: SortOrder,
        is_read: bool | None = None,
        is_starred: bool | None = None,
        has_attachments: bool | None = None,
    ) -> tuple[list[Email], int]:
        """Return (page of emails, total matching the same filters) for
        the authenticated user's inbox."""
        items = await self._email_repository.get_by_user_id_for_list(
            user.id,
            page=page,
            page_size=page_size,
            sort=sort,
            is_read=is_read,
            is_starred=is_starred,
            has_attachments=has_attachments,
        )
        total = await self._email_repository.count_by_user_id(
            user.id,
            is_read=is_read,
            is_starred=is_starred,
            has_attachments=has_attachments,
        )
        return items, total

    async def get_email(self, user: User, email_id: UUID) -> Email:
        """Return a single email, enforcing that it belongs to `user`.

        Raises EmailNotFoundError (404) both when the email genuinely
        doesn't exist and when it exists but belongs to someone else —
        deliberately indistinguishable, per Task 4.2's requirement not
        to leak another user's email IDs.
        """
        email = await self._email_repository.get_by_id(email_id)
        if email is None or email.user_id != user.id:
            raise EmailNotFoundError(f"No email found with id {email_id}.")
        return email

    async def search_emails(
        self, user: User, *, query: str, page: int, page_size: int
    ) -> tuple[list[Email], int]:
        """Search the authenticated user's locally stored emails by text.

        Empty or whitespace-only queries are handled by the repository
        and will return the normal inbox list (all emails for the user).
        User_id scoping happens at the query level in the repository.
        """
        normalized_query = query.strip()

        items = await self._email_repository.search_by_user_id(
            user.id, query=normalized_query, page=page, page_size=page_size
        )
        total = await self._email_repository.count_search_by_user_id(
            user.id, query=normalized_query
        )
        return items, total
