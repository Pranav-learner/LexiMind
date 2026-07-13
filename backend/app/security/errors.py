"""Security domain errors (transport-agnostic).

Each carries an HTTP ``status_code`` and a short machine-readable ``code``; the API/middleware layer
maps them to HTTP responses.
"""

from __future__ import annotations


class SecurityException(Exception):
    status_code = 400
    code = "security_error"

    def __init__(self, message: str):
        super().__init__(message)


class UnauthorizedError(SecurityException):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(SecurityException):
    status_code = 403
    code = "forbidden"


class ResourceNotFoundError(SecurityException):
    status_code = 404
    code = "resource_not_found"


class TokenExpiredError(UnauthorizedError):
    code = "token_expired"


class TokenInvalidError(UnauthorizedError):
    code = "token_invalid"


class ApiKeyInvalidError(UnauthorizedError):
    code = "api_key_invalid"


class PolicyValidationError(SecurityException):
    status_code = 422
    code = "policy_validation_error"


class SecretEncryptionError(SecurityException):
    status_code = 500
    code = "secret_encryption_error"


class PolicyDenyError(ForbiddenError):
    code = "policy_deny"


class RateLimitExceededError(SecurityException):
    status_code = 429
    code = "rate_limit_exceeded"
