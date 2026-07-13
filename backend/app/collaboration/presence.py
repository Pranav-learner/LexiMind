"""In-memory workspace presence store.

Tracks which users are online in each workspace, what they're currently looking at,
and their status (online/away/busy). Uses heartbeat-based TTL — a user is considered
offline if their last heartbeat is older than ``PRESENCE_TTL_SECONDS``.

Design for future upgrade:
- Currently poll-based (clients call GET /presence periodically).
- Presence data shape is WebSocket/SSE-compatible — when real-time transport is added,
  this module becomes the backing store and events are pushed instead of polled.
- CRDT/OT compatibility: presence entries include artifact-level granularity so future
  collaborative editing can track cursors.

**Not persisted to SQLite** — presence is ephemeral. A server restart resets all presence
(which is correct — no user is online after a restart).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from dataclasses import dataclass, field


PRESENCE_TTL_SECONDS = 60  # Consider a user offline after this many seconds without heartbeat.


@dataclass
class _PresenceEntry:
    user_id: str
    display_name: str | None = None
    status: str = "online"  # online | away | busy
    active_document_id: str | None = None
    active_artifact_type: str | None = None
    active_artifact_id: str | None = None
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PresenceStore:
    """Thread-safe in-memory presence store, keyed by workspace_id.

    Usage::

        store = PresenceStore()
        store.heartbeat("ws_123", "user_abc", display_name="Alice", status="online")
        online = store.get_online("ws_123")
    """

    def __init__(self, ttl_seconds: int = PRESENCE_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        # {workspace_id: {user_id: _PresenceEntry}}
        self._data: dict[str, dict[str, _PresenceEntry]] = {}

    def heartbeat(
        self,
        workspace_id: str,
        user_id: str,
        *,
        display_name: str | None = None,
        status: str = "online",
        active_document_id: str | None = None,
        active_artifact_type: str | None = None,
        active_artifact_id: str | None = None,
    ) -> None:
        with self._lock:
            ws = self._data.setdefault(workspace_id, {})
            ws[user_id] = _PresenceEntry(
                user_id=user_id,
                display_name=display_name,
                status=status,
                active_document_id=active_document_id,
                active_artifact_type=active_artifact_type,
                active_artifact_id=active_artifact_id,
                last_seen=datetime.now(timezone.utc),
            )

    def disconnect(self, workspace_id: str, user_id: str) -> None:
        with self._lock:
            ws = self._data.get(workspace_id)
            if ws:
                ws.pop(user_id, None)

    def get_online(self, workspace_id: str) -> list[dict]:
        """Return all currently online users in a workspace (TTL-filtered)."""
        now = datetime.now(timezone.utc)
        result = []
        with self._lock:
            ws = self._data.get(workspace_id, {})
            expired = []
            for uid, entry in ws.items():
                age = (now - entry.last_seen).total_seconds()
                if age <= self._ttl:
                    result.append({
                        "user_id": entry.user_id,
                        "display_name": entry.display_name,
                        "status": entry.status,
                        "active_document_id": entry.active_document_id,
                        "active_artifact_type": entry.active_artifact_type,
                        "active_artifact_id": entry.active_artifact_id,
                        "last_seen": entry.last_seen.isoformat(),
                    })
                else:
                    expired.append(uid)
            # Clean up expired entries.
            for uid in expired:
                del ws[uid]
        return result

    def count_online(self, workspace_id: str) -> int:
        return len(self.get_online(workspace_id))


# Module-level singleton (shared across the process).
presence_store = PresenceStore()
