"""Secrets provider interface."""
from abc import abstractmethod
from typing import Optional
from app.platform.interfaces.base import BaseProvider

class SecretProvider(BaseProvider):
    """Abstraction interface for reading/writing configuration credentials and secrets."""

    @abstractmethod
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Fetch secret value by key name."""
        pass

    @abstractmethod
    def set_secret(self, key: str, value: str) -> None:
        """Store/update secret key-value pair."""
        pass
