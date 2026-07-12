"""Agent execution context + state — the request-scoped carrier every layer reads.

`AgentContext` is created once per run by the runtime and threaded through the planner, permission
policy, tools, and prompt builder. It carries scope (workspace/owner/conversation/document/media),
the DB session, injected external dependencies (`services` — the single answer function + the existing
async runners, so tools never import FastAPI/runners), the memory manager, and an event sink.

`AgentState` is the mutable per-run status object (phase + timings) the runtime advances and the
observability layer snapshots. Neither holds business logic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class AgentContext:
    db: Session
    owner_id: str
    workspace_id: str
    query: str
    execution_id: str = field(default_factory=lambda: f"agx_{uuid.uuid4().hex[:16]}")
    agent: str = "workspace_agent"
    conversation_id: Optional[str] = None
    document_id: Optional[str] = None            # scope to one document/recording
    params: Dict[str, Any] = field(default_factory=dict)
    granted_permissions: List[str] = field(default_factory=list)
    allowed_tools: Optional[List[str]] = None     # None = any registered tool
    # Injected external dependencies (never import runners/answer_service inside tools):
    #   services["answer_fn"], services["summary_runner"], services["notes_runner"], services["flashcard_runner"]
    services: Dict[str, Any] = field(default_factory=dict)
    memory: Any = None                            # MemoryManager (set by runtime)
    events: Any = None                            # EventSink (set by runtime)
    started_at: datetime = field(default_factory=_now)

    def answer_fn(self):
        fn = self.services.get("answer_fn")
        if fn is not None:
            return fn
        from app.services import answer_service
        return answer_service.complete


@dataclass
class AgentState:
    phase: str = "created"          # created|planning|permission|executing|synthesizing|done|failed|cancelled
    planner_ms: float = 0.0
    selection_ms: float = 0.0
    tools_ms: float = 0.0
    llm_ms: float = 0.0
    total_ms: float = 0.0
    retry_count: int = 0
    tool_count: int = 0
    error: Optional[str] = None
    cancelled: bool = False
