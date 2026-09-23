from typing import Any

import structlog
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.request_context import get_request_id
from app.domain.exceptions import DomainError

logger = structlog.get_logger(__name__)


def _error_envelope(code: str, message: str, request_id: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    request_id = get_request_id()
    logger.warning(
        "domain_error",
        code=exc.code,
        message=exc.message,
        path=request.url.path,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content=_error_envelope(exc.code, exc.message, request_id),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = get_request_id()
    field_errors = [
        {"field": ".".join(str(loc) for loc in err["loc"] if loc != "body"), "issue": err["msg"]}
        for err in exc.errors()
    ]
    logger.info(
        "validation_error",
        path=request.url.path,
        errors=field_errors,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "The request could not be validated.",
                "request_id": request_id,
                "fields": field_errors,
            }
        },
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = get_request_id()
    logger.info(
        "http_exception",
        status_code=exc.status_code,
        detail=exc.detail,
        path=request.url.path,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_envelope("HTTP_ERROR", str(exc.detail), request_id),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = get_request_id()
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        request_id=request_id,
        exc_info=exc,
    )
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_envelope(
            "INTERNAL_SERVER_ERROR",
            "An unexpected error occurred. Please try again.",
            request_id,
        ),
    )
    # ServerErrorMiddleware renders unhandled exceptions outside the regular
    # user middleware stack, so CORSMiddleware cannot add this header itself.
    origin = request.headers.get("origin")
    if origin in get_settings().cors_origins:
        response.headers["access-control-allow-origin"] = origin
        response.headers["access-control-allow-credentials"] = "true"
        response.headers["vary"] = "Origin"
    return response
