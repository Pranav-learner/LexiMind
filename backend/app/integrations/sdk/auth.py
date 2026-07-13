"""Authentication manager for connector credentials.

Handles OAuth2 flows, API key storage, token refresh, and encrypted credential
persistence using the existing ``app.security.crypto`` Fernet utilities.
Never stores plaintext credentials; always delegates to EncryptedSecret.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.integrations.errors import AuthenticationFailed
from app.integrations.models import ConnectorAuth
from app.security.crypto import decrypt_value, encrypt_value


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuthManager:
    """Manages encrypted credential lifecycle for connectors."""

    def __init__(self, db: Session):
        self.db = db

    def store_credentials(
        self,
        connector_id: str,
        auth_type: str,
        credentials: Dict[str, Any],
        scopes: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> ConnectorAuth:
        """Encrypt and store/update credentials for a connector."""
        cred_json = json.dumps(credentials, default=str)
        encrypted, iv = encrypt_value(cred_json)

        # Upsert: update existing or create new
        existing = self.db.query(ConnectorAuth).filter(
            ConnectorAuth.connector_id == connector_id
        ).first()

        if existing:
            existing.auth_type = auth_type
            existing.encrypted_credentials = encrypted
            existing.iv = iv
            existing.scopes = scopes or []
            existing.expires_at = expires_at
            existing.is_valid = True
            existing.updated_at = _now()
            self.db.commit()
            self.db.refresh(existing)
            return existing

        auth = ConnectorAuth(
            connector_id=connector_id,
            auth_type=auth_type,
            encrypted_credentials=encrypted,
            iv=iv,
            scopes=scopes or [],
            expires_at=expires_at,
            is_valid=True,
        )
        self.db.add(auth)
        self.db.commit()
        self.db.refresh(auth)
        return auth

    def get_credentials(self, connector_id: str) -> Dict[str, Any] | None:
        """Retrieve and decrypt credentials for a connector."""
        auth = self.db.query(ConnectorAuth).filter(
            ConnectorAuth.connector_id == connector_id,
            ConnectorAuth.is_valid.is_(True),
        ).first()

        if not auth:
            return None

        # Check expiry
        if auth.expires_at and auth.expires_at < _now():
            auth.is_valid = False
            self.db.commit()
            return None

        try:
            decrypted = decrypt_value(auth.encrypted_credentials, auth.iv)
            return json.loads(decrypted)
        except Exception as e:
            raise AuthenticationFailed(f"Failed to decrypt credentials: {e}")

    def get_auth_record(self, connector_id: str) -> ConnectorAuth | None:
        """Return the raw auth record (for status checks)."""
        return self.db.query(ConnectorAuth).filter(
            ConnectorAuth.connector_id == connector_id,
        ).first()

    def invalidate(self, connector_id: str) -> None:
        """Mark credentials as invalid (e.g. after a failed refresh)."""
        auth = self.db.query(ConnectorAuth).filter(
            ConnectorAuth.connector_id == connector_id
        ).first()
        if auth:
            auth.is_valid = False
            self.db.commit()

    def delete(self, connector_id: str) -> None:
        """Remove all credential records for a connector."""
        self.db.query(ConnectorAuth).filter(
            ConnectorAuth.connector_id == connector_id
        ).delete()
        self.db.commit()
