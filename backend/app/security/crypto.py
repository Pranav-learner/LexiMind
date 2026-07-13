"""Symmetric encryption and decryption utilities for secret storage.

Derives a Fernet key from the system's configured ``secret_key``, ensuring
that secrets are encrypted in transit and at rest in the database.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import settings
from app.security.errors import SecretEncryptionError


def _get_key() -> bytes:
    """Derive a 32-byte urlsafe base64 key from the system's secret key."""
    if not settings.secret_key:
        raise SecretEncryptionError("System secret_key is not configured.")
    # Standard SHA256 digest is exactly 32 bytes, which Fernet accepts when base64-encoded.
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_value(value: str) -> tuple[str, str]:
    """Encrypt a string value.

    Returns:
        (encrypted_str, iv_str) where iv_str is a placeholder, as Fernet embeds the IV.
    """
    try:
        f = Fernet(_get_key())
        encrypted = f.encrypt(value.encode("utf-8"))
        return encrypted.decode("utf-8"), "fernet_autogen"
    except Exception as e:
        raise SecretEncryptionError(f"Encryption failed: {e}")


def decrypt_value(encrypted_value: str, iv: str | None = None) -> str:
    """Decrypt an encrypted string value."""
    try:
        f = Fernet(_get_key())
        decrypted = f.decrypt(encrypted_value.encode("utf-8"))
        return decrypted.decode("utf-8")
    except Exception as e:
        raise SecretEncryptionError(f"Decryption failed: {e}")
