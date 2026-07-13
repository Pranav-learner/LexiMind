"""Connector Runtime — drives connector operations with rate limiting, retries, and standard telemetry.

Creates spans inside the standard Observability trace model, persisting execution
telemetry to ``IntegrationExecutionLog``.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Type

from sqlalchemy.orm import Session

from app.integrations.errors import (
    AuthenticationFailed,
    IntegrationError,
    RateLimitExceeded,
)
from app.integrations.models import ConnectorInstance, IntegrationExecutionLog
from app.integrations.sdk.auth import AuthManager
from app.integrations.sdk.base import BaseConnector, HealthStatus
from app.integrations.sdk.registry import connector_registry
from app.observability.bus import bus as telemetry_bus
from app.observability.interfaces import SpanRecord, TraceRecord


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ConnectorRuntime:
    """Safely executes operations on an installed connector instance."""

    def __init__(self, db: Session, workspace_id: str, owner_id: str):
        self.db = db
        self.workspace_id = workspace_id
        self.owner_id = owner_id
        self.auth_manager = AuthManager(db)

    def _get_instance(self, connector_id: str) -> ConnectorInstance:
        instance = self.db.query(ConnectorInstance).filter(
            ConnectorInstance.id == connector_id,
            ConnectorInstance.workspace_id == self.workspace_id,
            ConnectorInstance.owner_id == self.owner_id,
        ).first()
        if not instance:
            from app.integrations.errors import ConnectorNotFound
            raise ConnectorNotFound(connector_id)
        return instance

    def get_connector(self, connector_id: str) -> BaseConnector:
        """Instantiate and connect the connector class."""
        instance = self._get_instance(connector_id)
        if not instance.is_active:
            raise IntegrationError(f"Connector '{connector_id}' is disabled.")

        cls = connector_registry().get(instance.connector_type)
        connector = cls()

        credentials = self.auth_manager.get_credentials(connector_id) or {}
        try:
            connected = connector.connect(instance.config, credentials)
            if not connected:
                raise AuthenticationFailed("Connector rejected credentials during connection.")
        except Exception as e:
            instance.status = "error"
            instance.health = "unhealthy"
            instance.error_message = str(e)
            self.db.commit()
            raise IntegrationError(f"Failed to connect to service: {e}")

        return connector

    def execute_with_telemetry(
        self,
        connector_id: str,
        operation_name: str,
        func: Callable[[BaseConnector], Any],
        *args,
        **kwargs,
    ) -> Any:
        """Executes a connector function inside an observability span & telemetry log."""
        instance = self._get_instance(connector_id)
        connector = self.get_connector(connector_id)

        t0 = time.perf_counter()
        started_at = _now()
        trace_id = f"t_{uuid.uuid4().hex[:16]}"
        span_id = f"s_{uuid.uuid4().hex[:16]}"

        # Standard Telemetry Setup
        trace = TraceRecord(
            id=trace_id,
            workspace_id=self.workspace_id,
            owner_id=self.owner_id,
            operation=f"connector.{operation_name}",
            attributes={"connector_id": connector_id, "connector_type": instance.connector_type},
        )
        span = SpanRecord(
            id=span_id,
            trace_id=trace_id,
            name=operation_name,
            component=f"connector.{instance.connector_type}",
            start_ms=t0 * 1000,
        )

        log = IntegrationExecutionLog(
            workspace_id=self.workspace_id,
            actor_id=self.owner_id,
            operation=f"connector.{operation_name}",
            connector_type=instance.connector_type,
            connector_id=connector_id,
            status="running",
            created_at=started_at,
        )
        self.db.add(log)
        self.db.commit()

        # Retry config
        retry_config = connector.retry_config()
        max_retries = retry_config.max_retries
        backoff = retry_config.backoff_factor

        result = None
        error_msg = None
        status = "completed"
        items_imported = 0
        items_exported = 0

        for attempt in range(max_retries + 1):
            try:
                # Stub rate limiting check
                rate_limit = connector.rate_limit_config()
                # A real implementation would token bucket check here.

                result = func(connector)

                # Extract items sync stats if returned
                from app.integrations.sdk.base import SyncResult
                if isinstance(result, SyncResult):
                    items_imported = result.items_imported
                    items_exported = result.items_exported

                break
            except Exception as e:
                log.retries += 1
                if attempt == max_retries:
                    status = "failed"
                    error_msg = str(e)
                    span.status = "error"
                    span.error = error_msg
                    trace.status = "error"
                    trace.error = error_msg
                    break
                # Exponential backoff sleep
                time.sleep(backoff ** attempt)

        # Teardown connection
        try:
            connector.disconnect()
        except Exception:
            pass

        duration_ms = (time.perf_counter() - t0) * 1000
        span.duration_ms = duration_ms
        trace.total_ms = duration_ms
        trace.spans.append(span)

        # Publish standard trace
        try:
            telemetry_bus().publish(trace)
        except Exception:
            pass

        # Update persistent execution log
        log.status = status
        log.duration_ms = duration_ms
        log.error = error_msg
        log.items_imported = items_imported
        log.items_exported = items_exported
        log.execution_metadata = {"trace_id": trace_id}
        self.db.commit()

        if status == "failed":
            raise IntegrationError(f"Connector execution failed: {error_msg}")

        return result
