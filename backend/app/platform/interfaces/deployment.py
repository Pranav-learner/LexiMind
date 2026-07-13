"""Deployment provider interface."""
from abc import abstractmethod
from typing import Dict, Any, List
from app.platform.interfaces.base import BaseProvider

class DeploymentProvider(BaseProvider):
    """Abstraction interface for container deployments (Docker Compose, Kubernetes, Nomad, etc.)."""

    @abstractmethod
    def get_replicas(self, service_name: str) -> int:
        """Get current replica count for a service."""
        pass

    @abstractmethod
    def set_replicas(self, service_name: str, count: int) -> None:
        """Set replica count for a service (scale up/down)."""
        pass

    @abstractmethod
    def restart_service(self, service_name: str) -> None:
        """Trigger rolling restart of a service."""
        pass

    @abstractmethod
    def get_service_logs(self, service_name: str, lines: int = 100) -> List[str]:
        """Fetch logs from service containers/pods."""
        pass
