"""Queue provider interface."""
from abc import abstractmethod
from typing import Dict, Any, Optional
from app.platform.interfaces.base import BaseProvider

class QueueProvider(BaseProvider):
    """Abstraction interface for task queues (Local, Redis, Kafka, SQS, etc.)."""

    @abstractmethod
    def enqueue(self, queue_name: str, payload: Dict[str, Any], priority: int = 0) -> str:
        """Enqueue a job payload. Returns job ID."""
        pass

    @abstractmethod
    def dequeue(self, queue_name: str) -> Optional[Dict[str, Any]]:
        """Dequeue a job payload. Returns None if queue is empty."""
        pass

    @abstractmethod
    def size(self, queue_name: str) -> int:
        """Get the current size of a queue."""
        pass

    @abstractmethod
    def get_metrics(self) -> Dict[str, Any]:
        """Return metrics such as throughput, backlog size, and utilization."""
        pass
