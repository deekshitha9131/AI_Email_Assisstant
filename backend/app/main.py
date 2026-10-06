from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.constants import (
    API_V1_PREFIX,
    HEALTH_STATUS_OK,
    OPENAPI_TAGS_METADATA,
    PROJECT_DESCRIPTION,
    PROJECT_NAME,
    PROJECT_VERSION,
    OpenAPITags,
)
from app.core.logging_config import configure_logging
from app.domain.exceptions import DomainError
from app.infrastructure.cache.redis_client import close_redis_client, create_redis_client
from app.infrastructure.database.engine import create_db_engine, dispose_engine
from app.infrastructure.database.session import create_session_factory
from app.presentation.api.v1.router import api_router
from app.presentation.exception_handlers import (
    domain_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_error_handler,
)
from app.presentation.middleware.logging import RequestLoggingMiddleware
from app.presentation.middleware.request_id import RequestIDMiddleware

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging()

    logger.info("startup_begin", app_env=settings.app_env)
    engine = create_db_engine(settings)
    app.state.db_engine = engine
    app.state.db_session_factory = create_session_factory(engine)

    redis_client = create_redis_client(settings) if settings.redis_url else None
    app.state.redis_client = redis_client

    http_client = httpx.AsyncClient(timeout=10.0)
    app.state.http_client = http_client

    logger.info("startup_complete", app_env=settings.app_env)

    yield
    logger.info("shutdown_begin")

    await http_client.aclose()
    if redis_client is not None:
        await close_redis_client(redis_client)
    await dispose_engine(engine)

    logger.info("shutdown_complete")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title=PROJECT_NAME,
        description=PROJECT_DESCRIPTION,
        version=PROJECT_VERSION,
        openapi_tags=OPENAPI_TAGS_METADATA,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    # CORSMiddleware must be added LAST so that Starlette's insert-at-0
    # ordering places it as the outermost user middleware.  This guarantees
    # every response — including error responses produced by inner middleware
    # or exception handlers — carries the Access-Control-Allow-Origin header.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # --- Routers ---
    app.include_router(api_router, prefix=API_V1_PREFIX)

    @app.get("/health", tags=[OpenAPITags.HEALTH], summary="Liveness check")
    async def liveness_check() -> dict[str, Any]:
        return {"status": HEALTH_STATUS_OK}

    return app


app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.app_debug,
    )
