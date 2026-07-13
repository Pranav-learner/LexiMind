"""Storage provider interface."""
from abc import abstractmethod
from typing import BinaryIO, List
from app.platform.interfaces.base import BaseProvider

class StorageProvider(BaseProvider):
    """Abstraction interface for object storage (LocalFS, S3, Azure Blob, GCS, etc.)."""

    @abstractmethod
    def read(self, path: str) -> bytes:
        """Read a file's raw byte content."""
        pass

    @abstractmethod
    def write(self, path: str, content: bytes) -> None:
        """Write content bytes to a file path."""
        pass

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete a file from storage."""
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if a file exists in storage."""
        pass

    @abstractmethod
    def list_files(self, prefix: str = "") -> List[str]:
        """List files under a given prefix."""
        pass
