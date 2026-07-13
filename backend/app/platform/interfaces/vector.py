"""Vector store provider interface."""
from abc import abstractmethod
from typing import Dict, Any, List
from app.platform.interfaces.base import BaseProvider

class VectorStoreProvider(BaseProvider):
    """Abstraction interface for vector databases (FAISS, PgVector, Qdrant, etc.)."""

    @abstractmethod
    def add(self, embedding: List[float], metadata: Dict[str, Any]) -> None:
        """Add a vector embedding and associated metadata to the store."""
        pass

    @abstractmethod
    def search(self, embedding: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for top_k nearest vectors and return their metadata & scores."""
        pass

    @abstractmethod
    def size(self) -> int:
        """Return total number of vectors in the store."""
        pass

    @abstractmethod
    def remove_where(self, key: str, value: Any) -> int:
        """Remove all vectors matching key = value metadata fields. Returns count."""
        pass

    @abstractmethod
    def save(self) -> None:
        """Commit or persist index changes (if local/cache-based)."""
        pass
