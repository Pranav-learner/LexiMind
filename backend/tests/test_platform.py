"""Unit and Integration Tests for Phase 9 Module 4 (Platform Engineering)."""
import sys
from unittest.mock import MagicMock

# Stub out heavy packages before loading app.main
sys.modules['sentence_transformers'] = MagicMock()
sys.modules['torch'] = MagicMock()

import pytest
import time
from fastapi.testclient import TestClient

from app.main import app
from app.platform.feature_flags import FeatureFlagManager
from app.platform.profiles import DeploymentProfile, ProfileName
from app.platform.registry import InfrastructureRegistry
from app.platform.resilience import CircuitBreaker, Bulkhead, retry, ResilienceError
from app.platform.worker.execution import AIResourceScheduler

client = TestClient(app)

# =====================================================================
# 1. Feature Flag Tests
# =====================================================================
def test_feature_flag_evaluation():
    manager = FeatureFlagManager()
    
    # default enabled
    assert manager.is_enabled("enable_mcp") is True
    
    # canary percentage rollout
    manager.update_percentage("enable_canary", 100)
    assert manager.is_enabled("enable_canary", user_id="user_1") is True
    
    # disable flag (0%)
    manager.update_percentage("enable_canary", 0)
    assert manager.is_enabled("enable_canary", user_id="user_1") is False

    # user-specific override
    manager.set_override("enable_canary", "user_special", True)
    assert manager.is_enabled("enable_canary", user_id="user_special") is True
    assert manager.is_enabled("enable_canary", user_id="user_other") is False


# =====================================================================
# 2. Registry Provider Decoupling Tests
# =====================================================================
def test_infrastructure_registry_profiles():
    # Dev Profile returns SQLite + LocalStorage
    dev_profile = DeploymentProfile(ProfileName.DEVELOPMENT)
    dev_registry = InfrastructureRegistry(dev_profile)
    assert dev_registry.get_database().__class__.__name__ == "SQLiteProvider"
    assert dev_registry.get_storage().__class__.__name__ == "LocalStorage"

    # Production Profile returns Postgres + S3
    prod_profile = DeploymentProfile(ProfileName.PRODUCTION)
    prod_registry = InfrastructureRegistry(prod_profile)
    assert prod_registry.get_database().__class__.__name__ == "PostgreSQLProvider"
    assert prod_registry.get_storage().__class__.__name__ == "S3Storage"


# =====================================================================
# 3. Resilience Pattern Decorators Tests
# =====================================================================
def test_circuit_breaker_trips():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.2)
    
    call_count = 0
    @breaker
    def failing_fn():
        nonlocal call_count
        call_count += 1
        raise ValueError("Failed downstream")

    # First fail
    with pytest.raises(ValueError):
        failing_fn()
    assert breaker.state == "CLOSED"

    # Second fail should trip
    with pytest.raises(ValueError):
        failing_fn()
    assert breaker.state == "OPEN"

    # Subsequent call immediately rejected
    with pytest.raises(ResilienceError):
        failing_fn()
    
    # Wait recovery timeout
    time.sleep(0.25)
    
    # Half-open tries
    @breaker
    def success_fn():
        return "success"

    assert success_fn() == "success"
    assert breaker.state == "CLOSED"


def test_bulkhead_concurrency_limit():
    bulkhead = Bulkhead(max_concurrent=1)
    
    @bulkhead
    def long_running():
        time.sleep(0.1)
        return "done"

    import threading
    errors = []
    
    def run_worker():
        try:
            long_running()
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=run_worker)
    t2 = threading.Thread(target=run_worker)
    
    t1.start()
    time.sleep(0.02) # Ensure t1 acquires the bulkhead first
    t2.start()
    
    t1.join()
    t2.join()
    
    assert len(errors) == 1
    assert isinstance(errors[0], ResilienceError)


def test_retry_exhaustion_trigger_dlq():
    dlq_calls = []
    def dlq_cb(err, name):
        dlq_calls.append((err, name))

    @retry(max_attempts=2, delay=0.01, backoff=1.0, dlq_callback=dlq_cb)
    def flunk():
        raise RuntimeError("oops")

    with pytest.raises(RuntimeError):
        flunk()

    assert len(dlq_calls) == 1
    assert dlq_calls[0][1] == "flunk"


# =====================================================================
# 4. AI Resource Scheduler Queueing/Promotion Tests
# =====================================================================
def test_resource_scheduler_priorities():
    scheduler = AIResourceScheduler(max_concurrent_gpu_slots=1, max_concurrent_cpu_slots=1)
    
    # Acquire slot 1
    assert scheduler.request_execution_slot("task_1", is_gpu=True, priority=2) is True
    
    # Request slot 2 (should be queued)
    assert scheduler.request_execution_slot("task_2", is_gpu=True, priority=1) is False
    
    # Request slot 3 (higher priority, should be queued first)
    assert scheduler.request_execution_slot("task_3", is_gpu=True, priority=0) is False

    # Release task 1 -> should promote task 3 (priority 0)
    promoted = scheduler.release_execution_slot("task_1")
    assert promoted is not None
    assert promoted["task_id"] == "task_3"

    # Release task 3 -> should promote task 2 (priority 1)
    promoted = scheduler.release_execution_slot("task_3")
    assert promoted is not None
    assert promoted["task_id"] == "task_2"


# =====================================================================
# 5. FastAPI REST Integration Endpoints Tests
# =====================================================================
def test_platform_api_endpoints(auth):
    client, headers, user_id = auth
    # 1. Health Status check (healthy status returned)
    response = client.get("/api/platform/health", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) > 0
    
    # 2. Get Platform metrics
    metrics_resp = client.get("/api/platform/metrics", headers=headers)
    assert metrics_resp.status_code == 200
    data = metrics_resp.json()
    assert "gpu_utilization" in data
    assert "cpu_slots_max" in data

    # 3. Post scale command
    scale_resp = client.post("/api/platform/scale", json={"service_name": "leximind-worker-media", "replicas": 4}, headers=headers)
    assert scale_resp.status_code == 200
    
    # 4. Check feature flags list
    flags_resp = client.get("/api/platform/flags", headers=headers)
    assert flags_resp.status_code == 200
    assert "enable_canary" in flags_resp.json()

    # 5. Trigger backup
    backup_resp = client.post("/api/platform/backup", json={"snapshot_name": "test-snapshot"}, headers=headers)
    assert backup_resp.status_code == 200
    assert backup_resp.json()["success"] is True
    snapshot_id = backup_resp.json()["snapshot_id"]

    # 6. Trigger restore
    restore_resp = client.post("/api/platform/restore", json={"snapshot_id": snapshot_id}, headers=headers)
    assert restore_resp.status_code == 200
    assert restore_resp.json()["success"] is True

    # 7. Get platform ops logs
    logs_resp = client.get("/api/platform/logs", headers=headers)
    assert logs_resp.status_code == 200
    logs_data = logs_resp.json()
    assert len(logs_data) > 0
    # The last log should be the restore success
    assert any(log["event_type"] == "RESTORE_SUCCESS" for log in logs_data)
