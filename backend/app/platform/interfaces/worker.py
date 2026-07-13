"""Worker backend interface."""
from abc import abstractmethod
from typing import Dict, Any
from app.platform.interfaces.base import BaseProvider

class WorkerBackend(BaseProvider):
    """Abstraction interface for background worker runner backends."""

    @abstractmethod
    def start_worker(self, pool_name: str) -> None:
        """Start worker thread/process execution loop for a specialized pool."""
        pass

    @abstractmethod
    def stop_worker(self, pool_name: str) -> None:
        """Stop worker execution cleanly (graceful shutdown)."""
        pass

    @abstractmethod
    def get_status(self, pool_name: str) -> Dict[str, Any]:
        """Get specialized worker pool status metrics (active/idle/errors)."""
        pass
