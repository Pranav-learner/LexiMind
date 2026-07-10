"""Unit tests for auth security primitives and the AuthService."""

import pytest

from app.auth import security
from app.auth.errors import EmailAlreadyExists, InvalidCredentials
from app.auth.repository import UserRepository
from app.auth.service import AuthService


# --------------------------------------------------------------------- security
def test_password_hash_roundtrip():
    hashed = security.hash_password("hunter2password")
    assert hashed != "hunter2password"
    assert security.verify_password("hunter2password", hashed)
    assert not security.verify_password("wrong", hashed)


def test_password_hash_is_salted():
    a = security.hash_password("samepassword")
    b = security.hash_password("samepassword")
    assert a != b  # different salts => different encoded hashes


def test_token_roundtrip():
    token = security.create_token("user_123", now=1000, ttl_seconds=100)
    assert security.decode_token(token, now=1050) == "user_123"


def test_token_expired_returns_none():
    token = security.create_token("user_123", now=1000, ttl_seconds=100)
    assert security.decode_token(token, now=2000) is None


def test_token_tampering_detected():
    token = security.create_token("user_123", now=1000, ttl_seconds=100)
    payload, sig = token.split(".")
    forged = payload + "." + ("A" * len(sig))
    assert security.decode_token(forged, now=1050) is None


def test_garbage_token_returns_none():
    assert security.decode_token("not-a-token") is None
    assert security.decode_token("") is None


# ----------------------------------------------------------------------- service
def test_register_and_login(db_session):
    service = AuthService(UserRepository(db_session))
    user = service.register(email="Bob@Example.com", password="password123", display_name="Bob")
    assert user.email == "bob@example.com"  # normalized
    logged_in, token = service.login(email="bob@example.com", password="password123")
    assert logged_in.id == user.id
    assert security.decode_token(token) == user.id


def test_duplicate_email_rejected(db_session):
    service = AuthService(UserRepository(db_session))
    service.register(email="dup@example.com", password="password123")
    with pytest.raises(EmailAlreadyExists):
        service.register(email="dup@example.com", password="password123")


def test_login_wrong_password_rejected(db_session):
    service = AuthService(UserRepository(db_session))
    service.register(email="carol@example.com", password="password123")
    with pytest.raises(InvalidCredentials):
        service.login(email="carol@example.com", password="nope")


def test_login_unknown_user_rejected(db_session):
    service = AuthService(UserRepository(db_session))
    with pytest.raises(InvalidCredentials):
        service.login(email="ghost@example.com", password="whatever12")
