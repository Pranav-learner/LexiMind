"""Auth DTOs (request/response contracts) — Pydantic models.

Keeping DTOs separate from the ORM model means the wire format can evolve independently of
the storage schema, and we never leak the password hash to a client.

Note: we validate email with a light inline regex rather than Pydantic's `EmailStr` on
purpose — `EmailStr` requires the external `email-validator` package, and Phase 3 keeps the
dependency footprint to just SQLAlchemy. A stricter validator can be swapped in later.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str) -> str:
    value = (value or "").strip().lower()
    if not _EMAIL_RE.match(value):
        raise ValueError("A valid email address is required.")
    return value


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
