"""Centralized platform-wide event bus for integration and automation events.

Funnels lifecycle events (connector syncs, webhook deliveries, manual triggers)
to registered handlers (such as the automation trigger matching system) and
persists events for auditing.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.integrations.models import IntegrationEvent

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class IntegrationEventBus:
    """Thread-safe event pub-sub engine for LexiMind integrations."""

    def __init__(self):
        self._lock = threading.Lock()
        self._handlers: Dict[str, List[Callable[[IntegrationEvent], None]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[IntegrationEvent], None]) -> None:
        """Subscribe a handler function to an event type (or '*' for all)."""
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: Callable[[IntegrationEvent], None]) -> None:
        with self._lock:
            if event_type in self._handlers:
                try:
                    self._handlers[event_type].remove(handler)
                except ValueError:
                    pass

    def publish(
        self,
        db: Session,
        event_type: str,
        source: str,
        workspace_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> IntegrationEvent:
        """Publish an event, persist to database, and dispatch synchronously to handlers."""
        event = IntegrationEvent(
            id=f"evt_{uuid.uuid4().hex[:16]}",
            workspace_id=workspace_id,
            event_type=event_type,
            source=source,
            actor_id=actor_id,
            payload=payload or {},
            processed=False,
            created_at=_now(),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        # Dispatching handlers
        handlers_to_call = []
        with self._lock:
            # Type-specific handlers
            if event_type in self._handlers:
                handlers_to_call.extend(self._handlers[event_type])
            # Wildcard handlers
            if "*" in self._handlers:
                handlers_to_call.extend(self._handlers["*"])

        for handler in handlers_to_call:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Error executing event handler: {e}")

        # Mark processed if all went well
        event.processed = True
        db.commit()

        # Seamless routing to existing SyncBus for collaborative live notifications
        try:
            if workspace_id:
                from app.collaboration.sync import sync_bus
                sync_bus.publish(
                    workspace_id=workspace_id,
                    event_type="integration_event",
                    actor_id=actor_id,
                    data={"event_id": event.id, "event_type": event_type, "source": source},
                )
        except Exception as e:
            logger.error(f"Failed to publish to SyncBus: {e}")

        return event


# Module-level singleton
_BUS: Optional[IntegrationEventBus] = None


def event_bus() -> IntegrationEventBus:
    global _BUS
    if _BUS is None:
        _BUS = IntegrationEventBus()
    return _BUS
