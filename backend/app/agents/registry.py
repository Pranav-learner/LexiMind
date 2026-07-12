"""Tool Registry + Agent Registry (Steps 4 & 5) — discovery, metadata, versioning, lazy loading.

`ToolRegistry` is a process-wide singleton of tool INSTANCES keyed by name. Tools are registered lazily
on first access (`_ensure_loaded`) so importing `app.agents.registry` pulls in no heavy service until a
tool actually runs. Discovery/validation/permissions all read a tool's `ToolSpec` without executing it.

`AgentRegistry` holds agent DESCRIPTORS (metadata + capabilities + version + health), NOT
implementations. Module 1 ships one usable agent — the `workspace_agent` the runtime drives — plus
declared descriptors for the future agents (Research/Writing/Verification/Meeting/KnowledgeGraph) so
they can be discovered and, later, register their own implementations against the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.agents.errors import ToolNotFound
from app.agents.interfaces import ToolSpec


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, object] = {}
        self._loaded = False

    def register(self, tool) -> None:
        self._tools[tool.spec.name] = tool

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        # Lazy: import + register the built-in tools only when the registry is first used.
        from app.agents.tools.generation_tools import (
            CreateNoteTool, GenerateFlashcardsTool, GenerateNotesTool, GenerateSummaryTool,
        )
        from app.agents.tools.search_tools import (
            QueryDashboardTool, RetrieveTranscriptTool, TemporalSearchTool, UnifiedMediaSearchTool,
            WorkspaceSearchTool,
        )
        for cls in (WorkspaceSearchTool, TemporalSearchTool, UnifiedMediaSearchTool, RetrieveTranscriptTool,
                    QueryDashboardTool, GenerateSummaryTool, GenerateNotesTool, GenerateFlashcardsTool,
                    CreateNoteTool):
            self.register(cls())
        self._loaded = True

    def get(self, name: str):
        self._ensure_loaded()
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFound(name)
        return tool

    def has(self, name: str) -> bool:
        self._ensure_loaded()
        return name in self._tools

    def specs(self) -> List[ToolSpec]:
        self._ensure_loaded()
        return [t.spec for t in self._tools.values()]

    def spec(self, name: str) -> ToolSpec:
        return self.get(name).spec


@dataclass
class AgentDescriptor:
    name: str
    version: str
    description: str
    capabilities: List[str] = field(default_factory=list)
    default_tools: List[str] = field(default_factory=list)
    status: str = "available"                 # available | planned
    implemented: bool = False

    def to_dict(self) -> Dict:
        return {"name": self.name, "version": self.version, "description": self.description,
                "capabilities": self.capabilities, "default_tools": self.default_tools,
                "status": self.status, "implemented": self.implemented, "health": "ok"}


class AgentRegistry:
    def __init__(self):
        self._agents: Dict[str, AgentDescriptor] = {}
        self._seed()

    def _seed(self) -> None:
        # The one agent the runtime drives in Module 1.
        self.register(AgentDescriptor(
            name="workspace_agent", version="1.0",
            description="General workspace agent: plans, selects tools, retrieves, and answers.",
            capabilities=["planning", "tool_use", "retrieval", "generation", "answering"],
            default_tools=["workspace_search", "temporal_search", "unified_media_search",
                           "retrieve_transcript", "query_dashboard", "generate_summary",
                           "generate_notes", "generate_flashcards", "create_note"],
            status="available", implemented=True))
        # Future agents — DESCRIPTORS ONLY (no implementations in Module 1).
        for name, desc, caps in [
            ("research_agent", "Multi-step research over the workspace (Phase 6 Module 2).", ["research", "synthesis"]),
            ("writing_agent", "Long-form drafting from workspace knowledge (Phase 6 Module 2).", ["writing", "editing"]),
            ("verification_agent", "Claim verification + reasoning checks (Phase 6 Module 3).", ["verification", "reasoning"]),
            ("meeting_agent", "Meeting intelligence over recordings (future).", ["meeting", "action_items"]),
            ("knowledge_graph_agent", "Entity/relationship graph construction (future).", ["graph", "entities"]),
        ]:
            self.register(AgentDescriptor(name=name, version="0.1", description=desc, capabilities=caps,
                                          status="planned", implemented=False))

    def register(self, descriptor: AgentDescriptor) -> None:
        self._agents[descriptor.name] = descriptor

    def get(self, name: str) -> Optional[AgentDescriptor]:
        return self._agents.get(name)

    def all(self) -> List[AgentDescriptor]:
        return list(self._agents.values())


# Process-wide singletons (cheap; tools lazy-load on first use).
_TOOL_REGISTRY: Optional[ToolRegistry] = None
_AGENT_REGISTRY: Optional[AgentRegistry] = None


def tool_registry() -> ToolRegistry:
    global _TOOL_REGISTRY
    if _TOOL_REGISTRY is None:
        _TOOL_REGISTRY = ToolRegistry()
    return _TOOL_REGISTRY


def agent_registry() -> AgentRegistry:
    global _AGENT_REGISTRY
    if _AGENT_REGISTRY is None:
        _AGENT_REGISTRY = AgentRegistry()
    return _AGENT_REGISTRY
