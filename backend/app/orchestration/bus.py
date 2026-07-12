"""Agent Communication Bus (Step 5) — structured inter-agent messaging + the execution timeline.

Agents never talk in free-form prose or chain-of-thought — they exchange STRUCTURED ARTIFACTS: task
requests, intermediate results (ids + summaries + counts), status updates, errors, and shared
references. `CommunicationBus` buffers these in order; the buffer IS the orchestration timeline the
dashboard renders and the OrchestrationExecutionLog persists. A future websocket/SSE sink implements
the same `publish` for live streaming — no scheduler change.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from app.orchestration.interfaces import AgentMessage


class CommunicationBus:
    def __init__(self):
        self._messages: List[AgentMessage] = []
        self._t0 = time.perf_counter()
        self._seq = 0

    def publish(self, sender: str, recipient: str, mtype: str, payload: Dict[str, Any]) -> AgentMessage:
        self._seq += 1
        msg = AgentMessage(seq=self._seq, at_ms=(time.perf_counter() - self._t0) * 1000,
                           sender=sender, recipient=recipient, type=mtype, payload=payload)
        self._messages.append(msg)
        return msg

    # convenience emitters (kept structured — artifacts only)
    def task_request(self, node_id: str, agent: str, objective: str) -> None:
        self.publish("orchestrator", node_id, "task_request",
                     {"agent": agent, "objective": objective[:200]})

    def status(self, node_id: str, status: str, detail: str = "") -> None:
        self.publish(node_id, "orchestrator", "status", {"status": status, "detail": detail[:200]})

    def result(self, node_id: str, agent: str, *, task_id: str, summary: str, evidence: int,
               confidence: Any = None) -> None:
        self.publish(node_id, "all", "result", {"agent": agent, "task_id": task_id,
                     "summary": summary[:200], "evidence": evidence, "confidence": confidence})

    def error(self, node_id: str, message: str, *, recovered: bool = False) -> None:
        self.publish(node_id, "orchestrator", "error", {"message": message[:300], "recovered": recovered})

    def shared_ref(self, node_id: str, ref_type: str, ref: Dict[str, Any]) -> None:
        self.publish(node_id, "all", "shared_ref", {"ref_type": ref_type, **ref})

    def timeline(self) -> List[Dict[str, Any]]:
        return [m.to_dict() for m in self._messages]
