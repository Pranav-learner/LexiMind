"""Data-access for users. The ONLY layer that talks to the ORM session for User rows.

Separating this from the service keeps business rules (hashing, token issuance) free of
SQLAlchemy details and makes the service unit-testable against a fake repository.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: str) -> Optional[User]:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> Optional[User]:
        return self.db.scalar(select(User).where(User.email == email.strip().lower()))

    def create(self, *, email: str, password_hash: str, display_name: str) -> User:
        user = User(email=email.strip().lower(), password_hash=password_hash, display_name=display_name)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user
