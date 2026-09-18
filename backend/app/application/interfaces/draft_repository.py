from typing import Protocol
from uuid import UUID

from app.domain.entities.draft import Draft
from app.domain.enums.draft_status import DraftStatus


class IDraftRepository(Protocol):
    async def create(
        self, *, email_id: UUID, body: str, status: DraftStatus = DraftStatus.GENERATED
    ) -> Draft:
        ...

    async def get_by_id(self, draft_id: UUID) -> Draft | None:
        """Look up a draft by database ID, unscoped by user. Exists for
        internal/administrative use; user-facing lookups must use
        get_by_id_for_user instead."""
        ...

    async def get_by_id_for_user(self, draft_id: UUID, user_id: UUID) -> Draft | None:
        """Look up a draft by database ID, scoped to `user_id` via the
        owning email's user_id in the query itself. Returns None both
        for "doesn't exist" and "exists but belongs to someone else" —
        the caller cannot and must not try to tell those apart."""
        ...

    async def list_by_user(
        self, user_id: UUID, *, page: int = 1, page_size: int = 25
    ) -> list[Draft]:
        """List a user's drafts (across all their emails), paginated,
        newest first."""
        ...

    async def count_by_user(self, user_id: UUID) -> int: ...

    async def update_status(self, draft_id: UUID, status: DraftStatus) -> Draft:
        """Update a draft's status. Raises DraftNotFoundError if no such
        draft exists. Does not validate that the transition is legal
        (e.g. approving an already-sent draft) — that is a use-case
        rule for a later task's service layer, not a persistence
        concern."""
        ...

    async def get_by_email_id(self, email_id: UUID) -> Draft | None: ...