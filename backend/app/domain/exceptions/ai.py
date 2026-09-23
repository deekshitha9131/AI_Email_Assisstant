from app.domain.exceptions.base import BusinessValidationError, ConflictError, DomainError


class AIConfigurationError(DomainError):

    code = "AI_CONFIGURATION_ERROR"
    http_status = 503


class AIAuthenticationError(DomainError):
    code = "AI_AUTHENTICATION_ERROR"
    http_status = 502


class AITimeoutError(DomainError):
    code = "AI_TIMEOUT"
    http_status = 504


class AIProviderError(DomainError):
    code = "AI_PROVIDER_ERROR"
    http_status = 502


class InvalidAIResponseError(BusinessValidationError):
    code = "AI_INVALID_RESPONSE"


class PriorityNotClassifiedError(ConflictError):
    code = "PRIORITY_NOT_CLASSIFIED"


class EmbeddingProviderError(DomainError):
    code = "EMBEDDING_PROVIDER_ERROR"
    http_status = 502
