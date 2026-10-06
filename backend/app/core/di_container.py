import secrets
from functools import lru_cache
from typing import Annotated

import httpx
import redis.asyncio as redis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context.draft_context import DraftContextBuilder
from app.ai.preprocessing.email_preprocessor import EmailPreprocessor
from app.ai.providers.llm_provider import LLMProvider
from app.ai.rag.chunker import EmailChunker
from app.ai.rag.context_builder import ContextBuilder as RAGContextBuilder
from app.ai.rag.embedding import EmbeddingService
from app.ai.rag.indexing_service import EmailIndexingService
from app.ai.rag.retrieval import RetrievalService
from app.ai.services.draft_generator import DraftGenerator
from app.ai.services.understanding_service import AIUnderstandingService
from app.application.services.auth_service import AuthService
from app.application.services.compose_draft_service import ComposeDraftService
from app.application.services.draft_service import DraftService
from app.application.services.email_service import EmailService
from app.application.services.follow_up_service import FollowUpService
from app.application.services.gmail_service import GmailService
from app.application.services.notification_service import NotificationService
from app.application.services.thread_service import ThreadService
from app.core.config import Settings, get_settings
from app.core.constants import SESSION_COOKIE_NAME
from app.core.security import TokenCipher
from app.domain.entities.user import User
from app.domain.exceptions.auth import SessionNotFoundError
from app.infrastructure.cache.session_store import SessionStore
from app.infrastructure.database.repositories.compose_draft_repository import ComposeDraftRepository
from app.infrastructure.database.repositories.draft_repository import DraftRepository
from app.infrastructure.database.repositories.email_ai_understanding_repository import (
    EmailAIUnderstandingRepository,
)
from app.infrastructure.database.repositories.email_chunk_repository import EmailChunkRepository
from app.infrastructure.database.repositories.email_repository import EmailRepository
from app.infrastructure.database.repositories.follow_up_repository import FollowUpRepository
from app.infrastructure.database.repositories.notification_repository import NotificationRepository
from app.infrastructure.database.repositories.thread_repository import ThreadRepository
from app.infrastructure.database.repositories.user_repository import UserRepository
from app.infrastructure.database.session import get_db_session
from app.infrastructure.gmail.oauth_client import GoogleOAuthClient


def get_redis(request: Request) -> redis.Redis:
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is not configured.",
        )
    return redis_client  # type: ignore[no-any-return]


def get_http_client(request: Request) -> httpx.AsyncClient:

    return request.app.state.http_client  # type: ignore[no-any-return]


def get_settings_dependency() -> Settings:

    return get_settings()


@lru_cache
def get_token_cipher() -> TokenCipher:
    settings = get_settings()
    if not settings.token_encryption_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token encryption is not configured.",
        )
    return TokenCipher(settings)


def get_user_repository(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    token_cipher: Annotated[TokenCipher, Depends(get_token_cipher)],
) -> UserRepository:
    return UserRepository(db, token_cipher)

def get_draft_repository(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> DraftRepository:
    return DraftRepository(db)


def get_compose_draft_repository(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ComposeDraftRepository:
    return ComposeDraftRepository(db)

def get_oauth_client(
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> GoogleOAuthClient:
    return GoogleOAuthClient(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=settings.google_redirect_uri,
        http_client=http_client,
    )


def get_session_store(
    redis_client: Annotated[redis.Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> SessionStore:
    return SessionStore(redis_client=redis_client, ttl_seconds=settings.session_ttl_seconds)


def get_auth_service(
    oauth_client: Annotated[GoogleOAuthClient, Depends(get_oauth_client)],
    user_repository: Annotated[UserRepository, Depends(get_user_repository)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> AuthService:
    return AuthService(
        oauth_client=oauth_client,
        user_repository=user_repository,
        session_store=session_store,
    )


async def get_current_user(request: Request) -> User:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id is None:
        raise SessionNotFoundError("No active session.")

    session_factory = request.app.state.db_session_factory
    async with session_factory() as db:
        user_repository = get_user_repository(db, get_token_cipher())
        session_store = get_session_store(get_redis(request), get_settings_dependency())
        auth_service = AuthService(
            oauth_client=None,
            user_repository=user_repository,
            session_store=session_store,
        )
        return await auth_service.get_current_user(session_id)


_automation_bearer = HTTPBearer(auto_error=False)


async def get_automation_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_automation_bearer)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    user_repository: Annotated[UserRepository, Depends(get_user_repository)],
) -> User:
    """Authenticate n8n with a dedicated bearer token and configured user."""
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not settings.n8n_automation_token
        or not secrets.compare_digest(credentials.credentials, settings.n8n_automation_token)
        or settings.n8n_automation_user_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid automation credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await user_repository.get_by_id(settings.n8n_automation_user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid automation credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


DbSession = Annotated[AsyncSession, Depends(get_db_session)]
RedisClient = Annotated[redis.Redis, Depends(get_redis)]
AppSettings = Annotated[Settings, Depends(get_settings_dependency)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AutomationUser = Annotated[User, Depends(get_automation_user)]


def get_thread_repository(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ThreadRepository:
    return ThreadRepository(db)


def get_email_repository(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> EmailRepository:
    return EmailRepository(db)


def get_notification_repository(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationRepository:
    return NotificationRepository(db)


def get_follow_up_repository(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> FollowUpRepository:
    return FollowUpRepository(db)


def get_email_service(
    email_repository: Annotated[EmailRepository, Depends(get_email_repository)],
) -> EmailService:
    return EmailService(email_repository=email_repository)


def get_notification_service(
    email_service: Annotated[EmailService, Depends(get_email_service)],
    notification_repository: Annotated[
        NotificationRepository, Depends(get_notification_repository)
    ],
) -> NotificationService:
    return NotificationService(
        email_service=email_service,
        notification_repository=notification_repository,
    )


def get_thread_service(
    thread_repository: Annotated[ThreadRepository, Depends(get_thread_repository)],
) -> ThreadService:
    return ThreadService(thread_repository=thread_repository)


def get_follow_up_service(
    email_service: Annotated[EmailService, Depends(get_email_service)],
    thread_service: Annotated[ThreadService, Depends(get_thread_service)],
    repository: Annotated[FollowUpRepository, Depends(get_follow_up_repository)],
) -> FollowUpService:
    return FollowUpService(
        email_service=email_service,
        thread_service=thread_service,
        repository=repository,
    )


def get_email_preprocessor() -> EmailPreprocessor:
    return EmailPreprocessor()


def get_llm_provider(
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> LLMProvider:
    return LLMProvider(settings)


def get_understanding_service(
    preprocessor: Annotated[EmailPreprocessor, Depends(get_email_preprocessor)],
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> AIUnderstandingService:
    return AIUnderstandingService(preprocessor=preprocessor, llm_provider=llm_provider)


def get_email_ai_understanding_repository(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> EmailAIUnderstandingRepository:
    return EmailAIUnderstandingRepository(db)


def get_email_chunker() -> EmailChunker:
    return EmailChunker()


def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


def get_email_chunk_repository(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> EmailChunkRepository:
    return EmailChunkRepository(db)


def get_email_indexing_service(
    preprocessor: Annotated[EmailPreprocessor, Depends(get_email_preprocessor)],
    chunker: Annotated[EmailChunker, Depends(get_email_chunker)],
    embedding_service: Annotated[EmbeddingService, Depends(get_embedding_service)],
    chunk_repository: Annotated[EmailChunkRepository, Depends(get_email_chunk_repository)],
) -> EmailIndexingService:
    return EmailIndexingService(
        preprocessor=preprocessor,
        chunker=chunker,
        embedding_service=embedding_service,
        chunk_repository=chunk_repository,
    )


def get_gmail_service(
    user_repository: Annotated[UserRepository, Depends(get_user_repository)],
    thread_repository: Annotated[ThreadRepository, Depends(get_thread_repository)],
    email_repository: Annotated[EmailRepository, Depends(get_email_repository)],
    indexing_service: Annotated[EmailIndexingService, Depends(get_email_indexing_service)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> GmailService:
    return GmailService(
        user_repository=user_repository,
        thread_repository=thread_repository,
        email_repository=email_repository,
        indexing_service=indexing_service,
        settings=settings,
    )


def get_retrieval_service(
    embedding_service: Annotated[EmbeddingService, Depends(get_embedding_service)],
    chunk_repository: Annotated[EmailChunkRepository, Depends(get_email_chunk_repository)],
) -> RetrievalService:
    return RetrievalService(embedding_service=embedding_service, chunk_repository=chunk_repository)

def get_draft_generator(
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> DraftGenerator:
    return DraftGenerator(llm_provider=llm_provider, settings=settings)

def get_rag_context_builder() -> RAGContextBuilder:
    return RAGContextBuilder()

def get_draft_context_builder() -> DraftContextBuilder:
    return DraftContextBuilder()

def get_draft_service(
    email_service: Annotated[EmailService, Depends(get_email_service)],
    gmail_service: Annotated[GmailService, Depends(get_gmail_service)],
    thread_service: Annotated[ThreadService, Depends(get_thread_service)],
    understanding_repository: Annotated[
        EmailAIUnderstandingRepository, Depends(get_email_ai_understanding_repository)
    ],
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    rag_context_builder: Annotated[RAGContextBuilder, Depends(get_rag_context_builder)],
    draft_context_builder: Annotated[DraftContextBuilder, Depends(get_draft_context_builder)],
    draft_generator: Annotated[DraftGenerator, Depends(get_draft_generator)],
    draft_repository: Annotated[DraftRepository, Depends(get_draft_repository)],
) -> DraftService:
    return DraftService(
        email_service=email_service,
        gmail_service=gmail_service,
        thread_service=thread_service,
        understanding_repository=understanding_repository,
        retrieval_service=retrieval_service,
        rag_context_builder=rag_context_builder,
        draft_context_builder=draft_context_builder,
        draft_generator=draft_generator,
        draft_repository=draft_repository,
    )


def get_compose_draft_service(
    repository: Annotated[ComposeDraftRepository, Depends(get_compose_draft_repository)],
) -> ComposeDraftService:
    return ComposeDraftService(repository=repository)
