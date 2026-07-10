"""Domain errors for authentication.

These are transport-agnostic (no FastAPI here). The API layer maps them to HTTP status
codes, keeping business rules independent of the web framework.
"""

from __future__ import annotations


class AuthError(Exception):
    """Base class for all auth domain errors."""

    status_code = 400
    code = "auth_error"


class EmailAlreadyExists(AuthError):
    status_code = 409
    code = "email_exists"

    def __init__(self, email: str):
        super().__init__(f"An account with email '{email}' already exists.")


class InvalidCredentials(AuthError):
    status_code = 401
    code = "invalid_credentials"

    def __init__(self) -> None:
        super().__init__("Incorrect email or password.")


class NotAuthenticated(AuthError):
    status_code = 401
    code = "not_authenticated"

    def __init__(self, detail: str = "Authentication required.") -> None:
        super().__init__(detail)


class InvalidRegistration(AuthError):
    status_code = 422
    code = "invalid_registration"
