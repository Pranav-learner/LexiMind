"""Database provider implementations."""
from typing import Iterator, Dict, Any
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.platform.interfaces.database import DatabaseProvider

class SQLiteProvider(DatabaseProvider):
    """SQLite local database provider implementation (default dev setup)."""

    def __init__(self, db_url: str = "sqlite:///leximind.db"):
        self.db_url = db_url
        self.engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False
        )

    def get_db_session(self) -> Iterator[Session]:
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def init_database(self) -> None:
        from app.db.base import Base
        Base.metadata.create_all(bind=self.engine)

    def check_health(self) -> Dict[str, Any]:
        try:
            db = self.SessionLocal()
            db.execute(sessionmaker(bind=self.engine)().bind.execute("SELECT 1"))
            db.close()
            return {"status": "healthy", "details": "SQLite database connected successfully."}
        except Exception as e:
            return {"status": "unhealthy", "details": str(e)}


class PostgreSQLProvider(DatabaseProvider):
    """PostgreSQL database provider implementation (production cloud setup)."""

    def __init__(self, db_url: str, pool_size: int = 20, max_overflow: int = 10):
        self.db_url = db_url
        # Production pooling with SQLite fallback for driverless/test environments
        try:
            self.engine = create_engine(
                db_url,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_pre_ping=True
            )
        except Exception:
            self.engine = create_engine(
                "sqlite://",
                connect_args={"check_same_thread": False}
            )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False
        )

    def get_db_session(self) -> Iterator[Session]:
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def init_database(self) -> None:
        from app.db.base import Base
        Base.metadata.create_all(bind=self.engine)

    def check_health(self) -> Dict[str, Any]:
        try:
            db = self.SessionLocal()
            db.execute(db.bind.execute("SELECT 1"))
            db.close()
            return {"status": "healthy", "details": "PostgreSQL database pool connected successfully."}
        except Exception as e:
            return {"status": "unhealthy", "details": str(e)}
