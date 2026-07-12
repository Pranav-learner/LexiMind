"""Event bus (Step 2 / Step 11) — the observability + future-streaming seam.

The runtime emits lifecycle events (`plan`, `tool_start`, `tool_end`, `synthesize`, `done`, `error`).
`InMemoryEventSink` just buffers them (used to build the execution timeline in the debug panel). A
future SSE/websocket sink implements the same `emit` — so live agent streaming needs no runtime change.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AgentEvent:
    seq: int
    event: str
    at_ms: float
    payload: Dict[str, Any]


class InMemoryEventSink:
    def __init__(self):
        self._events: List[AgentEvent] = []
        self._t0 = time.perf_counter()
        self._seq = 0

    def emit(self, event: str, payload: Dict[str, Any]) -> None:
        self._seq += 1
        self._events.append(AgentEvent(seq=self._seq, event=event,
                                       at_ms=round((time.perf_counter() - self._t0) * 1000, 3),
                                       payload=payload))

    def timeline(self) -> List[Dict[str, Any]]:
        return [{"seq": e.seq, "event": e.event, "at_ms": e.at_ms, **e.payload} for e in self._events]


class NullEventSink:
    def emit(self, event: str, payload: Dict[str, Any]) -> None:  # pragma: no cover - trivial
        return None

    def timeline(self) -> List[Dict[str, Any]]:  # pragma: no cover - trivial
        return []
