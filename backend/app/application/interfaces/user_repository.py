"""User repository interface.

Defined as a `Protocol` (structural typing) rather than an ABC — either
works for this purpose, but a Protocol means the concrete
implementation in infrastructure/ doesn't need to explicitly inherit
from this class, just match its shape. Application-layer code (services,
once they exist) depends on this interface, never on
`app.infrastructure.database.repositories.user_repository.UserRepository`
directly — that's what makes the concrete implementation swappable.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities.oauth_token import OAuthToken
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus


class IUserRepository(Protocol):
    async def create(self, *, email: str, full_name: str, google_sub_id: str) -> User:
        """Create a new user. Raises UserAlreadyExistsError on a duplicate
        email or google_sub_id."""
        ...

    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_google_sub_id(self, google_sub_id: str) -> User | None: ...

    async def list_users(
        self, *, status: UserStatus | None = None, limit: int = 50, offset: int = 0
    ) -> list[User]:
        """List users, optionally filtered by status. Soft-deleted users are
        never included, regardless of the status filter."""
        ...

    async def update_full_name(self, user_id: UUID, full_name: str) -> User:
        """Raises UserNotFoundError if no such user exists (or is soft-deleted)."""
        ...

    async def set_status(self, user_id: UUID, status: UserStatus) -> User:
        """Raises UserNotFoundError if no such user exists (or is soft-deleted)."""
        ...

    async def soft_delete(self, user_id: UUID) -> None:
        """Raises UserNotFoundError if no such user exists or is already deleted."""
        ...

    async def save_oauth_tokens(
        self,
        user_id: UUID,
        *,
        access_token: str,
        refresh_token: str | None,
        token_expiry: datetime,
        granted_scopes: list[str],
    ) -> None:
        """Create or replace the stored (encrypted) token set for a user."""
        ...

    async def get_oauth_tokens(self, user_id: UUID) -> OAuthToken | None:
        """Return a user's decrypted tokens, or None if they've never
        connected Gmail."""
        ...

    async def get_gmail_history_id(self, user_id: UUID) -> str | None:
        """Return the user's last-synced Gmail history ID, or None if no
        Gmail sync (initial or incremental) has ever completed."""
        ...

    async def update_gmail_history_id(self, user_id: UUID, history_id: str) -> None:
        """Persist the newest Gmail history ID after a successful sync."""
        ...
