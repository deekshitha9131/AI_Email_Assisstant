from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from app.application.dto.gmail import ParsedEmail
from app.domain.entities.email import Email

SortOrder = Literal["newest", "oldest"]


class IEmailRepository(Protocol):
    async def get_by_id(self, email_id: UUID) -> Email | None:
        """Look up a single email by its database primary key."""
        ...

    async def get_by_gmail_message_id(
        self, user_id: UUID, gmail_message_id: str
    ) -> Email | None: ...

    async def get_by_gmail_thread_id(self, user_id: UUID, gmail_thread_id: str) -> list[Email]:
        ...

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
        """List a user's emails, paginated, sorted, and optionally filtered."""
        ...

    async def count_by_user_id(
        self,
        user_id: UUID,
        *,
        is_read: bool | None = None,
        is_starred: bool | None = None,
        has_attachments: bool | None = None,
    ) -> int:
        """Count a user's emails under the same tri-state filters
        `get_by_user_id` accepts."""
        ...

    async def search_by_user_id(
        self, user_id: UUID, *, query: str, page: int = 1, page_size: int = 25
    ) -> list[Email]:
        """Case-insensitive text search across sender/subject/snippet/
        body_text, scoped to `user_id` at the SQL level, sorted newest
        first. `query` is matched as a substring (ILIKE '%query%')
        against each field independently, OR'd together — a match in
        any one field is enough."""
        ...

    async def count_search_by_user_id(self, user_id: UUID, *, query: str) -> int:
        """Count how many of a user's emails match `search_by_user_id`'s
        same query — used to compute an accurate paginated `total` for
        search results."""
        ...

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

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
        """Create a new email row. Raises EmailAlreadyExistsError if
        (user_id, gmail_message_id) already exists."""
        ...

    async def update(
        self, email_id: UUID, *, is_read: bool | None = None, is_starred: bool | None = None
    ) -> Email:
        """Update the user-mutable flags on an email. Raises
        EmailNotFoundError if no such email exists."""
        ...

    async def delete(self, email_id: UUID) -> None:
        """Permanently delete an email. Raises EmailNotFoundError if no
        such email exists."""
        ...

    async def upsert(
        self, *, thread_id: UUID, user_id: UUID, parsed: ParsedEmail
    ) -> tuple[Email, bool]:
        """Create the email if it doesn't exist for this user, or
        replace its fields if it does. Returns (entity, was_created)."""
        ...

    # ------------------------------------------------------------------
    # Counts
    # ------------------------------------------------------------------

    async def count_total(self, user_id: UUID) -> int: ...

    async def count_unread(self, user_id: UUID) -> int: ...

    async def count_starred(self, user_id: UUID) -> int: ...
