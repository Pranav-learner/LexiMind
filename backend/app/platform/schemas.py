"""Pydantic schemas for Platform API operations."""
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime

class PlatformProviderStatus(BaseModel):
    name: str
    status: str # healthy | unhealthy | degraded
    details: str

class PlatformMetricsResponse(BaseModel):
    gpu_utilization: float
    cpu_utilization: float
    gpu_slots_active: int
    gpu_slots_max: int
    cpu_slots_active: int
    cpu_slots_max: int
    backlog_waiting_count: int
    active_connections_db: int
    queue_backlog_total: int

class PlatformScaleRequest(BaseModel):
    service_name: str
    replicas: int = Field(..., ge=0, le=20)

class FeatureFlagUpdateRequest(BaseModel):
    flag_name: str
    percentage: int = Field(..., ge=0, le=100)

class FeatureFlagOverrideRequest(BaseModel):
    flag_name: str
    key: str # organization_id, workspace_id, or user_id
    enabled: bool

class BackupRequest(BaseModel):
    snapshot_name: str = Field(default="manual-snapshot")

class BackupResponse(BaseModel):
    success: bool
    snapshot_id: str
    size_bytes: int
    created_at: str

class RestoreRequest(BaseModel):
    snapshot_id: str

class RestoreResponse(BaseModel):
    success: bool
    restored_at: str
    details: str

class CanaryRolloutRequest(BaseModel):
    service_name: str
    weight: int = Field(..., ge=0, le=100) # percentage of traffic routed to canary

class OpsLogResponse(BaseModel):
    id: str
    workspace_id: Optional[str] = None
    operator_id: Optional[str] = None
    event_type: str
    status: str
    service_name: str
    message: str
    metadata_json: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True
