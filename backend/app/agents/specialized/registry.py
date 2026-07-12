"""Specialized-agent registry — resolve a task_type to its agent implementation.

Kept tiny + lazy so importing this module pulls in no heavy service. Mirrors the Module-1
`AgentRegistry` (which holds descriptors); this holds the concrete implementations the task service
dispatches to. Registering a new specialized agent is a one-line addition here — the service/API and
the Module-4 orchestrator discover it through `available()`.
"""

from __future__ import annotations

from typing import Dict, List

from app.agents.specialized.base import SpecializedAgent
from app.agents.specialized.comparison_agent import ComparisonAgent
from app.agents.specialized.research_agent import ResearchAgent
from app.agents.specialized.study_agent import StudyAgent
from app.agents.specialized.writing_agent import WritingAgent

_AGENTS: Dict[str, type] = {
    "research": ResearchAgent,
    "writing": WritingAgent,
    "comparison": ComparisonAgent,
    "study": StudyAgent,
}


def get_agent(task_type: str) -> SpecializedAgent:
    cls = _AGENTS.get(task_type)
    if cls is None:
        from app.agents.errors import AgentNotFound
        raise AgentNotFound(task_type)
    return cls()


def available() -> List[str]:
    return list(_AGENTS.keys())


def has(task_type: str) -> bool:
    return task_type in _AGENTS
