"""Gmail-specific domain exceptions.

Subclasses of the base hierarchy in app/domain/exceptions/base.py, same
pattern as app/domain/exceptions/auth.py and .../user.py — every
exception Gmail integration code can raise carries its own HTTP-status
hint and machine-readable code, so the existing exception handlers
(app/presentation/exception_handlers.py) map it to the standard error
envelope with no new handler required.
"""

from app.domain.exceptions.base import (
    BusinessValidationError,
    ConflictError,
    DomainError,
    ForbiddenError,
    UnauthorizedError,
)


class GmailAuthenticationError(UnauthorizedError):
    """Raised when Gmail rejects a request as unauthenticated/unauthorized —
    the stored OAuth tokens are missing, expired beyond refresh, or have
    been revoked by the user on Google's side."""

    code = "GMAIL_AUTHENTICATION_FAILED"
    http_status = 401


class GmailPermissionError(ForbiddenError):
    """Raised when the token is valid but lacks the required Gmail scope."""

    code = "GMAIL_PERMISSION_DENIED"
    http_status = 403


class GmailAPIError(DomainError):
    """Raised for any other Gmail API failure — rate limiting, a malformed
    request, or Gmail's own service being unavailable. Mapped to 502:
    the failure originates in an upstream dependency, not this
    service's own logic."""

    code = "GMAIL_API_ERROR"
    http_status = 502


class GmailParseError(BusinessValidationError):
    """Raised when a Gmail message payload can't be parsed into a
    ParsedEmail — see app/infrastructure/gmail/parser.py for the full
    rationale. GmailService catches this per-message during sync (a
    single malformed message must not abort an entire sync run) rather
    than letting it propagate to the API layer."""

    code = "GMAIL_PARSE_ERROR"


class GmailNotConnectedError(UnauthorizedError):
    """Raised when a sync/send is attempted for a user who has never
    completed the Gmail OAuth handshake (no row in `oauth_tokens`) —
    distinct from GmailAuthenticationError, which means tokens exist
    but Gmail rejected them."""

    code = "GMAIL_NOT_CONNECTED"
    http_status = 401


class GmailSyncRequiredError(ConflictError):
    """Raised when incremental sync is requested but the user has no
    stored `gmail_history_id` — Gmail's History API requires a starting
    point, and the only source of a valid one is a prior successful
    sync (initial or incremental). Mapped to 409, same reasoning as
    other "the request is well-formed but the current state doesn't
    allow it" cases in this codebase (e.g. approving an already-sent
    draft, per app/domain/exceptions/base.py's ConflictError
    docstring): the fix isn't different input, it's a different prior
    action (call /gmail/sync first)."""

    code = "GMAIL_INITIAL_SYNC_REQUIRED"


class GmailHistoryExpiredError(ConflictError):
    """Raised when Gmail no longer retains the stored incremental cursor."""

    code = "GMAIL_HISTORY_EXPIRED"
