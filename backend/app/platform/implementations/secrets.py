"""Secret provider implementation."""
import os
from typing import Dict, Any, Optional
from app.platform.interfaces.secrets import SecretProvider

class EnvSecretProvider(SecretProvider):
    """Fallback secrets provider extracting variables from environment environment."""

    def __init__(self):
        self._vault = {}

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        # Return local environment override, falling back to local memory vault
        val = os.getenv(key)
        if val is not None:
            return val
        return self._vault.get(key, default)

    def set_secret(self, key: str, value: str) -> None:
        self._vault[key] = value

    def check_health(self) -> Dict[str, Any]:
        return {"status": "healthy", "details": "Environment Secrets Provider online."}
