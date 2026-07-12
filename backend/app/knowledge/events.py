"""Graph Event Publisher (Step 2) — the observability/streaming seam for graph mutations.

Emits structured events (entity_created / entity_merged / relationship_created / validated) as the
builder mutates the graph. `InMemoryGraphEvents` buffers them for the construction telemetry; a future
websocket/queue publisher implements the same `emit` for live graph updates or downstream consumers
(search index sync, Module-2 retrieval cache invalidation) with no builder change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class GraphEvent:
    seq: int
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)


class InMemoryGraphEvents:
    def __init__(self):
        self._events: List[GraphEvent] = []
        self._seq = 0

    def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        self._seq += 1
        self._events.append(GraphEvent(seq=self._seq, type=event_type, payload=payload))

    def summary(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for e in self._events:
            out[e.type] = out.get(e.type, 0) + 1
        return out


class NullGraphEvents:
    def emit(self, event_type: str, payload: Dict[str, Any]) -> None:  # pragma: no cover
        return None

    def summary(self) -> Dict[str, int]:  # pragma: no cover
        return {}
