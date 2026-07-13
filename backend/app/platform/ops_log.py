"""Platform operations logging (telemetry & audit trail)."""
from datetime import datetime, timezone
import uuid
from typing import Dict, Any, Optional, List
from sqlalchemy import String, Text, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, Session
from app.db.base import Base

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

class PlatformOperationsLog(Base):
    __tablename__ = "platform_ops_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # plo_...
    workspace_id: Mapped[Optional[str]] = mapped_column(String(40), index=True, nullable=True)
    operator_id: Mapped[Optional[str]] = mapped_column(String(40), index=True, nullable=True)
    
    event_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False) # e.g. SCALING_UP, BACKUP_SUCCESS, CANARY_PROMOTION, PROVIDER_FAILOVER
    status: Mapped[str] = mapped_column(String(12), index=True, nullable=False, default="success") # success | error | warning
    service_name: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (Index("ix_plat_ops_created", "created_at"),)


def log_platform_op(
    db: Session,
    event_type: str,
    message: str,
    *,
    service_name: str = "leximind-platform",
    status: str = "success",
    workspace_id: Optional[str] = None,
    operator_id: Optional[str] = None,
    metadata_json: Optional[Dict[str, Any]] = None
) -> PlatformOperationsLog:
    """Create and persist a platform operation log in the database."""
    log_id = f"plo_{uuid.uuid4().hex[:12]}"
    log_entry = PlatformOperationsLog(
        id=log_id,
        workspace_id=workspace_id,
        operator_id=operator_id,
        event_type=event_type,
        status=status,
        service_name=service_name,
        message=message,
        metadata_json=metadata_json or {}
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    return log_entry


def get_platform_ops(
    db: Session,
    *,
    workspace_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50
) -> List[PlatformOperationsLog]:
    """Retrieve platform logs filtered by parameters."""
    query = db.query(PlatformOperationsLog)
    if workspace_id:
        query = query.filter(PlatformOperationsLog.workspace_id == workspace_id)
    if event_type:
        query = query.filter(PlatformOperationsLog.event_type == event_type)
    return query.order_by(PlatformOperationsLog.created_at.desc()).limit(limit).all()
