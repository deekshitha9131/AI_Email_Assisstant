from uuid import UUID

from app.domain.entities.compose_draft import ComposeDraft
from app.domain.entities.user import User
from app.domain.exceptions.draft import DraftNotFoundError
from app.infrastructure.database.repositories.compose_draft_repository import ComposeDraftRepository


class ComposeDraftService:
    def __init__(self, *, repository: ComposeDraftRepository) -> None:
        self._repository = repository

    async def create(self, user: User, **fields: object) -> ComposeDraft:
        return await self._repository.create(user_id=user.id, **fields)  # type: ignore[arg-type]

    async def list(self, user: User, *, page: int = 1, page_size: int = 25) -> list[ComposeDraft]:
        return await self._repository.list_by_user(user.id, page=page, page_size=page_size)

    async def get(self, user: User, draft_id: UUID) -> ComposeDraft:
        draft = await self._repository.get_by_id_for_user(draft_id, user.id)
        if draft is None:
            raise DraftNotFoundError(f"No compose draft found with id {draft_id}.")
        return draft

    async def update(self, user: User, draft_id: UUID, **fields: object) -> ComposeDraft:
        draft = await self._repository.update_for_user(
            draft_id, user.id, **fields  # type: ignore[arg-type]
        )
        if draft is None:
            raise DraftNotFoundError(f"No compose draft found with id {draft_id}.")
        return draft

    async def delete(self, user: User, draft_id: UUID) -> None:
        deleted = await self._repository.delete_for_user(draft_id, user.id)
        if not deleted:
            raise DraftNotFoundError(f"No compose draft found with id {draft_id}.")