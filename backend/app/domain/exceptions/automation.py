from app.domain.exceptions.base import DomainError


class AutomationAPIError(DomainError):
    """Raised when an n8n automation request fails because an upstream
    dependency such as Gmail, AI, or internal automation orchestration is
    unavailable or misbehaving.

    These requests are not invalid user input; they are upstream service
    failures, so the API layer reports them as a 502 Bad Gateway while keeping
    the rest of the app's standard DomainError envelope intact.
    """

    code = "AUTOMATION_API_ERROR"
    http_status = 502
