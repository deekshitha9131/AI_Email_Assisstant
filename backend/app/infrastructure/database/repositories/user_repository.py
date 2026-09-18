from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher, TokenCipherError
from app.domain.entities.oauth_token import OAuthToken
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.gmail import GmailAuthenticationError
from app.domain.exceptions.user import UserAlreadyExistsError, UserNotFoundError
from app.infrastructure.database.models.oauth_token import OAuthTokenModel
from app.infrastructure.database.models.user import UserModel


def _to_entity(model: UserModel) -> User:
    return User(
        id=model.id,
        email=model.email,
        full_name=model.full_name,
        google_sub_id=model.google_sub_id,
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
        deleted_at=model.deleted_at,
    )


class UserRepository:

    def __init__(self, session: AsyncSession, token_cipher: TokenCipher) -> None:
        self._session = session
        self._token_cipher = token_cipher

    async def create(self, *, email: str, full_name: str, google_sub_id: str) -> User:
        model = UserModel(email=email, full_name=full_name, google_sub_id=google_sub_id)
        self._session.add(model)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise UserAlreadyExistsError(
                "A user with this email or google_sub_id already exists."
            ) from exc
        await self._session.refresh(model)
        return _to_entity(model)

    async def get_by_id(self, user_id: UUID) -> User | None:
        stmt = select(UserModel).where(UserModel.id == user_id, UserModel.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(UserModel).where(UserModel.email == email, UserModel.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def get_by_google_sub_id(self, google_sub_id: str) -> User | None:
        stmt = select(UserModel).where(
            UserModel.google_sub_id == google_sub_id, UserModel.deleted_at.is_(None)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def list_users(
        self, *, status: UserStatus | None = None, limit: int = 50, offset: int = 0
    ) -> list[User]:
        stmt = select(UserModel).where(UserModel.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(UserModel.status == status)
        stmt = stmt.order_by(UserModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return [_to_entity(model) for model in result.scalars().all()]

    async def _get_model_or_raise(self, user_id: UUID) -> UserModel:
        stmt = select(UserModel).where(UserModel.id == user_id, UserModel.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise UserNotFoundError(f"No user found with id {user_id}.")
        return model

    async def update_full_name(self, user_id: UUID, full_name: str) -> User:
        model = await self._get_model_or_raise(user_id)
        model.full_name = full_name
        await self._session.commit()
        await self._session.refresh(model)
        return _to_entity(model)

    async def set_status(self, user_id: UUID, status: UserStatus) -> User:
        model = await self._get_model_or_raise(user_id)
        model.status = status
        await self._session.commit()
        await self._session.refresh(model)
        return _to_entity(model)

    async def soft_delete(self, user_id: UUID) -> None:
        model = await self._get_model_or_raise(user_id)
        model.deleted_at = datetime.now(UTC)
        await self._session.commit()

    async def save_oauth_tokens(
        self,
        user_id: UUID,
        *,
        access_token: str,
        refresh_token: str | None,
        token_expiry: datetime,
        granted_scopes: list[str],
    ) -> None:

        stmt = select(OAuthTokenModel).where(OAuthTokenModel.user_id == user_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        access_encrypted = self._token_cipher.encrypt(access_token)
        refresh_encrypted = (
            self._token_cipher.encrypt(refresh_token) if refresh_token else None
        )

        if model is None:
            if refresh_encrypted is None:
                raise GmailAuthenticationError(
                    "Google did not provide a refresh token for this Gmail connection. "
                    "Reconnect Gmail with offline access."
                )
            model = OAuthTokenModel(
                user_id=user_id,
                access_token_encrypted=access_encrypted,
                refresh_token_encrypted=refresh_encrypted,
                token_expiry=token_expiry,
                granted_scopes=granted_scopes,
            )
            self._session.add(model)
        else:
            model.access_token_encrypted = access_encrypted
            if refresh_encrypted is not None:
                model.refresh_token_encrypted = refresh_encrypted
            model.token_expiry = token_expiry
            model.granted_scopes = granted_scopes

        await self._session.commit()

    async def get_oauth_tokens(self, user_id: UUID) -> OAuthToken | None:
        stmt = select(OAuthTokenModel).where(OAuthTokenModel.user_id == user_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None

        try:
            access_token = self._token_cipher.decrypt(model.access_token_encrypted)
            refresh_token = self._token_cipher.decrypt(model.refresh_token_encrypted)
        except TokenCipherError as exc:
            raise GmailAuthenticationError(
                "Stored Gmail credentials cannot be decrypted. Reconnect Gmail to issue "
                "new credentials."
            ) from exc

        return OAuthToken(
            user_id=model.user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=model.token_expiry,
            granted_scopes=list(model.granted_scopes),
        )

    async def get_gmail_history_id(self, user_id: UUID) -> str | None:

        model = await self._get_model_or_raise(user_id)
        return str(model.gmail_history_id) if model.gmail_history_id is not None else None

    async def update_gmail_history_id(self, user_id: UUID, history_id: str) -> None:

        model = await self._get_model_or_raise(user_id)
        model.gmail_history_id = int(history_id)
        await self._session.commit()
