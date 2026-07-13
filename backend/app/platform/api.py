"""FastAPI Platform APIs."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from app.db.base import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.platform.schemas import (
    PlatformProviderStatus, PlatformMetricsResponse, PlatformScaleRequest,
    FeatureFlagUpdateRequest, FeatureFlagOverrideRequest, BackupRequest,
    BackupResponse, RestoreRequest, RestoreResponse, CanaryRolloutRequest,
    OpsLogResponse
)
from app.platform.registry import InfrastructureRegistry
from app.platform.profiles import DeploymentProfile, ProfileName
from app.platform.feature_flags import FeatureFlagManager
from app.platform.worker.execution import AIResourceScheduler
from app.platform.worker.dispatcher import TaskDispatcher
from app.platform.ops_log import log_platform_op, get_platform_ops

router = APIRouter(prefix="/api/platform", tags=["platform"])

# Global singletons
profile = DeploymentProfile(ProfileName.PRODUCTION)
registry = InfrastructureRegistry(profile)
feature_flag_manager = FeatureFlagManager()
resource_scheduler = AIResourceScheduler()
task_dispatcher = TaskDispatcher(registry.get_queue())

@router.get("/health", response_model=List[PlatformProviderStatus])
def get_infra_health(current_user: User = Depends(get_current_user)):
    """Fetch health details of all registered infrastructure providers."""
    # Only superusers/admins can access platform stats
    if not getattr(current_user, "is_superuser", False) and not getattr(current_user, "is_admin", True):
        raise HTTPException(status_code=403, detail="Admin permissions required.")

    status_list = []
    
    # 1. DB
    try:
        db_health = registry.get_database().check_health()
        status_list.append(PlatformProviderStatus(name="Database", **db_health))
    except Exception as e:
        status_list.append(PlatformProviderStatus(name="Database", status="unhealthy", details=str(e)))

    # 2. Queue
    try:
        q_health = registry.get_queue().check_health()
        status_list.append(PlatformProviderStatus(name="Queue", **q_health))
    except Exception as e:
        status_list.append(PlatformProviderStatus(name="Queue", status="unhealthy", details=str(e)))

    # 3. Storage
    try:
        s_health = registry.get_storage().check_health()
        status_list.append(PlatformProviderStatus(name="Object Storage", **s_health))
    except Exception as e:
        status_list.append(PlatformProviderStatus(name="Object Storage", status="unhealthy", details=str(e)))

    # 4. Vector Store
    try:
        v_health = registry.get_vector().check_health()
        status_list.append(PlatformProviderStatus(name="Vector Store", **v_health))
    except Exception as e:
        status_list.append(PlatformProviderStatus(name="Vector Store", status="unhealthy", details=str(e)))

    # 5. AI Providers
    try:
        ai_health = registry.get_ai().check_health()
        status_list.append(PlatformProviderStatus(name="AI Provider Manager", **ai_health))
    except Exception as e:
        status_list.append(PlatformProviderStatus(name="AI Provider Manager", status="unhealthy", details=str(e)))

    # 6. Deployment Orchestrator
    try:
        dep_health = registry.get_deployment().check_health()
        status_list.append(PlatformProviderStatus(name="Deployment Orchestrator", **dep_health))
    except Exception as e:
        status_list.append(PlatformProviderStatus(name="Deployment Orchestrator", status="unhealthy", details=str(e)))

    return status_list


@router.get("/metrics", response_model=PlatformMetricsResponse)
def get_platform_metrics(current_user: User = Depends(get_current_user)):
    """Retrieve runtime resource scheduler utilization and queue counts."""
    if not getattr(current_user, "is_superuser", False) and not getattr(current_user, "is_admin", True):
        raise HTTPException(status_code=403, detail="Admin permissions required.")

    res_metrics = resource_scheduler.get_metrics()
    queue_metrics = task_dispatcher.get_status().get("queue_metrics", {})
    
    return PlatformMetricsResponse(
        gpu_utilization=res_metrics.get("gpu_utilization", 0.0),
        cpu_utilization=res_metrics.get("cpu_utilization", 0.0),
        gpu_slots_active=res_metrics.get("gpu_slots_active", 0),
        gpu_slots_max=res_metrics.get("gpu_slots_max", 4),
        cpu_slots_active=res_metrics.get("cpu_slots_active", 0),
        cpu_slots_max=res_metrics.get("cpu_slots_max", 8),
        backlog_waiting_count=res_metrics.get("backlog_waiting_count", 0),
        active_connections_db=12,  # Simulated pg pool connection count
        queue_backlog_total=queue_metrics.get("backlog_size", 0)
    )


@router.post("/scale", status_code=200)
def post_scale_replicas(
    req: PlatformScaleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Trigger scale up/down command via deployment orchestrator."""
    if not getattr(current_user, "is_superuser", False) and not getattr(current_user, "is_admin", True):
        raise HTTPException(status_code=403, detail="Admin permissions required.")

    dep = registry.get_deployment()
    current = dep.get_replicas(req.service_name)
    dep.set_replicas(req.service_name, req.replicas)
    
    log_platform_op(
        db,
        "SCALING_SERVICE",
        f"Scaled service '{req.service_name}' from {current} to {req.replicas} replicas.",
        service_name=req.service_name,
        operator_id=current_user.id,
        metadata_json={"previous_replicas": current, "requested_replicas": req.replicas}
    )
    return {"message": f"Successfully scaled '{req.service_name}' replicas to {req.replicas}."}


@router.get("/flags")
def get_feature_flags(current_user: User = Depends(get_current_user)):
    """Fetch status and rules for all feature flags."""
    if not getattr(current_user, "is_superuser", False) and not getattr(current_user, "is_admin", True):
        raise HTTPException(status_code=403, detail="Admin permissions required.")
    return feature_flag_manager.get_all_flags()


@router.post("/flags/percentage", status_code=200)
def update_flag_percentage(
    req: FeatureFlagUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Modify the rollout percentage rate for a flag."""
    if not getattr(current_user, "is_superuser", False) and not getattr(current_user, "is_admin", True):
        raise HTTPException(status_code=403, detail="Admin permissions required.")

    feature_flag_manager.update_percentage(req.flag_name, req.percentage)
    log_platform_op(
        db,
        "FEATURE_FLAG_ROLLOUT",
        f"Updated feature flag '{req.flag_name}' rollout rate to {req.percentage}%.",
        operator_id=current_user.id,
        metadata_json={"flag_name": req.flag_name, "percentage": req.percentage}
    )
    return {"message": f"Updated flag '{req.flag_name}' rollout percentage."}


@router.post("/flags/override", status_code=200)
def create_flag_override(
    req: FeatureFlagOverrideRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Register user, workspace, or org overrides for a flag."""
    if not getattr(current_user, "is_superuser", False) and not getattr(current_user, "is_admin", True):
        raise HTTPException(status_code=403, detail="Admin permissions required.")

    feature_flag_manager.set_override(req.flag_name, req.key, req.enabled)
    log_platform_op(
        db,
        "FEATURE_FLAG_OVERRIDE",
        f"Configured feature flag '{req.flag_name}' override for '{req.key}' to {req.enabled}.",
        operator_id=current_user.id,
        metadata_json={"flag_name": req.flag_name, "key": req.key, "enabled": req.enabled}
    )
    return {"message": f"Overrode flag '{req.flag_name}' status."}


@router.post("/backup", response_model=BackupResponse)
def trigger_backup(
    req: BackupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Simulate Point-in-Time database and index backup execution."""
    if not getattr(current_user, "is_superuser", False) and not getattr(current_user, "is_admin", True):
        raise HTTPException(status_code=403, detail="Admin permissions required.")

    import uuid
    snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
    created_at = datetime.now(timezone.utc).isoformat()
    
    log_platform_op(
        db,
        "BACKUP_SUCCESS",
        f"Database and FAISS vector indices successfully backed up. Snapshot id: {snapshot_id}.",
        operator_id=current_user.id,
        metadata_json={"snapshot_name": req.snapshot_name, "snapshot_id": snapshot_id}
    )
    
    return BackupResponse(
        success=True,
        snapshot_id=snapshot_id,
        size_bytes=4828100, # Simulated 4.8MB archive size
        created_at=created_at
    )


@router.post("/restore", response_model=RestoreResponse)
def trigger_restore(
    req: RestoreRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Simulate database restoration and recovery playbook execution."""
    if not getattr(current_user, "is_superuser", False) and not getattr(current_user, "is_admin", True):
        raise HTTPException(status_code=403, detail="Admin permissions required.")

    log_platform_op(
        db,
        "RESTORE_SUCCESS",
        f"Triggered recovery playbook. Snapshot '{req.snapshot_id}' restored successfully.",
        operator_id=current_user.id,
        metadata_json={"snapshot_id": req.snapshot_id}
    )
    
    return RestoreResponse(
        success=True,
        restored_at=datetime.now(timezone.utc).isoformat(),
        details=f"Point-In-Time recovery complete. Restored Postgres & Vector entities from snapshot {req.snapshot_id}."
    )


@router.get("/logs", response_model=List[OpsLogResponse])
def get_ops_logs(
    workspace_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Query recent platform operation activities logs."""
    if not getattr(current_user, "is_superuser", False) and not getattr(current_user, "is_admin", True):
        raise HTTPException(status_code=403, detail="Admin permissions required.")
    return get_platform_ops(db, workspace_id=workspace_id, event_type=event_type, limit=limit)
