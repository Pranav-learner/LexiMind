"""Database provider interface."""
from abc import abstractmethod
from typing import Iterator
from sqlalchemy.orm import Session
from app.platform.interfaces.base import BaseProvider

class DatabaseProvider(BaseProvider):
    """Abstraction interface for database engines (SQLite, PostgreSQL, etc.)."""

    @abstractmethod
    def get_db_session(self) -> Iterator[Session]:
        """Yield a database session and clean it up afterwards."""
        pass

    @abstractmethod
    def init_database(self) -> None:
        """Initialize database schema tables."""
        pass
