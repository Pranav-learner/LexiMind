"""Real-time synchronization infrastructure (long-poll based).

Provides an in-memory per-workspace event queue that clients poll to receive updates.
This is the "poor man's WebSocket" that works reliably in offline-first / embedded
deployments without additional infrastructure (Redis, message brokers, etc.).

Design for future upgrade:
- When WebSocket support is added, the SyncBus remains the backing store.
  Push notifications replace the long-poll loop.
- Event types are already structured for WebSocket frames.

Event types:
- document_update, knowledge_update, graph_update, media_update
- agent_activity, chat_update, comment, presence
- member_joined, member_left, workspace_updated
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


MAX_QUEUE_SIZE = 500      # Max events per workspace in memory.
POLL_TIMEOUT_SECONDS = 30  # Max seconds to block on a long-poll request.


@dataclass
class SyncEvent:
    id: str
    event_type: str
    workspace_id: str
    actor_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    data: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SyncBus:
    """Per-workspace event bus for real-time synchronization.

    Thread-safe. Each workspace has a bounded deque of events. Clients poll with a
    cursor (the last event ID they received) and get all events after that cursor.
    If no new events exist, the poll blocks up to ``POLL_TIMEOUT_SECONDS``.
    """

    def __init__(self, max_queue_size: int = MAX_QUEUE_SIZE):
        self._max_size = max_queue_size
        self._lock = threading.Lock()
        # {workspace_id: deque[SyncEvent]}
        self._queues: dict[str, deque[SyncEvent]] = {}
        # Condition variables for blocking polls.
        self._conditions: dict[str, threading.Condition] = {}

    def publish(
        self,
        workspace_id: str,
        event_type: str,
        *,
        actor_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        data: dict | None = None,
    ) -> SyncEvent:
        """Publish an event to a workspace's event bus."""
        event = SyncEvent(
            id=f"sync_{uuid.uuid4().hex[:16]}",
            event_type=event_type,
            workspace_id=workspace_id,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            data=data,
        )
        with self._lock:
            q = self._queues.setdefault(workspace_id, deque(maxlen=self._max_size))
            q.append(event)
            # Notify any waiting pollers.
            cond = self._conditions.get(workspace_id)
            if cond:
                with cond:
                    cond.notify_all()
        return event

    def poll(
        self,
        workspace_id: str,
        cursor: str | None = None,
        timeout: float = POLL_TIMEOUT_SECONDS,
    ) -> tuple[list[SyncEvent], str]:
        """Poll for new events after the given cursor.

        Returns (events, new_cursor). If no new events are available, blocks up to
        ``timeout`` seconds before returning an empty list.
        """
        events = self._get_events_after(workspace_id, cursor)
        if events:
            return events, events[-1].id

        # No events yet — block and wait.
        with self._lock:
            if workspace_id not in self._conditions:
                self._conditions[workspace_id] = threading.Condition()
            cond = self._conditions[workspace_id]

        with cond:
            cond.wait(timeout=timeout)

        events = self._get_events_after(workspace_id, cursor)
        new_cursor = events[-1].id if events else (cursor or "")
        return events, new_cursor

    def _get_events_after(self, workspace_id: str, cursor: str | None) -> list[SyncEvent]:
        with self._lock:
            q = self._queues.get(workspace_id, deque())
            if not cursor:
                return list(q)
            # Find events after cursor.
            found = False
            result = []
            for event in q:
                if found:
                    result.append(event)
                elif event.id == cursor:
                    found = True
            return result


# Module-level singleton.
sync_bus = SyncBus()
