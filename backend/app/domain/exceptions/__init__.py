"""Domain exceptions — re-exported here so callers can write
`from app.domain.exceptions import NotFoundError` rather than reaching
into the `base` submodule directly.
"""

from app.domain.exceptions.automation import AutomationAPIError
from app.domain.exceptions.base import (
    BusinessValidationError,
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)

__all__ = [
    "DomainError",
    "NotFoundError",
    "ConflictError",
    "BusinessValidationError",
    "UnauthorizedError",
    "ForbiddenError",
    "AutomationAPIError",
]
