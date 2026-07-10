"""Auth business logic: registration and login.

Depends on a `UserRepository` (data) and `security` (crypto). Raises domain errors from
`errors.py`; the API layer translates those to HTTP responses.
"""

from __future__ import annotations

from app.auth import security
from app.auth.errors import EmailAlreadyExists, InvalidCredentials
from app.auth.models import User
from app.auth.repository import UserRepository


class AuthService:
    def __init__(self, repo: UserRepository):
        self.repo = repo

    def register(self, *, email: str, password: str, display_name: str = "") -> User:
        if self.repo.get_by_email(email):
            raise EmailAlreadyExists(email)
        password_hash = security.hash_password(password)
        display = display_name.strip() or email.split("@")[0]
        return self.repo.create(email=email, password_hash=password_hash, display_name=display)

    def login(self, *, email: str, password: str) -> tuple[User, str]:
        user = self.repo.get_by_email(email)
        if not user or not security.verify_password(password, user.password_hash):
            # Same error whether the email is unknown or the password is wrong — do not
            # leak which accounts exist.
            raise InvalidCredentials()
        token = security.create_token(user.id)
        return user, token
