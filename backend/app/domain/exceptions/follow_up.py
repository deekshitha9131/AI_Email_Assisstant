from app.domain.exceptions.base import BusinessValidationError, ConflictError, NotFoundError


class FollowUpNotFoundError(NotFoundError):
    code = "FOLLOW_UP_NOT_FOUND"


class ActiveFollowUpExistsError(ConflictError):
    code = "ACTIVE_FOLLOW_UP_EXISTS"


class FollowUpStatusError(BusinessValidationError):
    code = "FOLLOW_UP_STATUS_ERROR"