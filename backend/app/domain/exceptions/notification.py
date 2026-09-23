from app.domain.exceptions.base import NotFoundError


class NotificationNotFoundError(NotFoundError):
    code = "NOTIFICATION_NOT_FOUND"
