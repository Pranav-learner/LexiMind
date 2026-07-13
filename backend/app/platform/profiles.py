"""Deployment Profiles for LexiMind."""
from enum import Enum
from typing import Dict, Any, Optional
from app.platform.errors import ConfigurationError

class ProfileName(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"
    ENTERPRISE = "enterprise"
    OFFLINE = "offline"


class DeploymentProfile:
    """Represents configuration, feature sets, and resource limits for a deployment profile."""

    def __init__(self, name: ProfileName, settings_dict: Optional[Dict[str, Any]] = None):
        self.name = ProfileName(name)
        self.settings = settings_dict or {}

    @property
    def offline_mode(self) -> bool:
        if self.name == ProfileName.OFFLINE:
            return True
        return self.settings.get("offline_mode", False)

    @property
    def security_level(self) -> str:
        if self.name in (ProfileName.PRODUCTION, ProfileName.ENTERPRISE):
            return "high"
        return "standard"

    @property
    def default_database_provider(self) -> str:
        if self.name in (ProfileName.DEVELOPMENT, ProfileName.TESTING, ProfileName.OFFLINE):
            return "sqlite"
        return "postgresql"

    @property
    def default_queue_provider(self) -> str:
        if self.name in (ProfileName.DEVELOPMENT, ProfileName.TESTING, ProfileName.OFFLINE):
            return "local"
        return "redis"

    @property
    def default_storage_provider(self) -> str:
        if self.name in (ProfileName.DEVELOPMENT, ProfileName.TESTING, ProfileName.OFFLINE):
            return "local"
        return "s3"

    @property
    def default_vector_store_provider(self) -> str:
        if self.name in (ProfileName.DEVELOPMENT, ProfileName.TESTING, ProfileName.OFFLINE):
            return "faiss"
        return "pgvector"

    @property
    def default_ai_provider(self) -> str:
        if self.name == ProfileName.OFFLINE:
            return "ollama"
        return "openai"

    def get_rate_limit(self, role: str) -> int:
        """Get rate limit (calls per minute) by role in this profile."""
        limits = self.settings.get("rate_limits", {})
        if not limits:
            if self.name in (ProfileName.PRODUCTION, ProfileName.ENTERPRISE):
                return 120 if role == "api" else 10
            return 1000  # High limit for dev/tests
        return limits.get(role, 60)
