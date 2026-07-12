"""Specialized-agent core (Phase 6, Module 2) — the common interface every research/writing/
comparison/study agent implements, plus the shared value objects and reusable orchestration helpers.

This is the seam that turns the Module-1 Agent *framework* (planner / graph / executor / tools /
prompt-package / single answer pathway) into autonomous, multi-step *workers*. A specialized agent
does NOT re-implement retrieval, context engineering, prompt building or inference — it composes the
existing pieces across several phases (plan → research → analysis → write) and shapes a structured,
citation-preserving deliverable.

Design:
- `AgentTask`         — the request a specialized agent runs (objective + scope + params).
- `Evidence`         — one ranked, citation-bearing unit collected during the research phase.
- `PhaseTimings`     — per-phase wall-clock (planner/research/analysis/writing) for the AgentTaskLog.
- `AgentStep`        — a serializable record of one thing the agent did (for the execution timeline).
- `AgentTaskResult`  — the uniform structured result (output + evidence + plan + steps + telemetry).
- `SpecializedAgent` — the Protocol every agent satisfies (`task_type` + `run`).
- `BaseSpecializedAgent` — an ABC giving the reusable helpers: run search tools through the framework
                       executor, collect + rank evidence, and synthesize via the SINGLE answer pathway.

Everything is programmed against the Module-1 interfaces so a future planner/LLM-reasoner, verifier
(Module 3) or multi-agent orchestrator (Module 4) drops in without touching these agents.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from app.agents.context import AgentContext
from app.agents.graph import ExecutionGraph, GraphNode
from app.agents.interfaces import ToolResult
from app.agents.prompt_package import PromptPackage, PromptSection


# --------------------------------------------------------------------- value objects
@dataclass
class AgentTask:
    """A unit of autonomous work handed to a specialized agent."""

    task_type: str                      # research | writing | comparison | study
    objective: str                      # the user's goal / research question / topic
    workspace_id: str
    owner_id: str
    document_ids: List[str] = field(default_factory=list)   # scope (0 = whole workspace)
    conversation_id: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)     # per-task knobs (report_type, format, count…)
    task_id: str = field(default_factory=lambda: f"agt_{uuid.uuid4().hex[:16]}")

    @property
    def primary_document(self) -> Optional[str]:
        return self.document_ids[0] if self.document_ids else None


@dataclass
class Evidence:
    """One ranked, cited piece of evidence the research phase collected (never LLM output)."""

    index: int
    text: str
    origin_tool: str
    source_type: str = "text"           # text | ocr | image | transcript | chapter | topic | dashboard …
    document_id: Optional[str] = None
    title: Optional[str] = None
    page_number: Optional[int] = None
    timespan: Optional[str] = None       # temporal evidence
    speaker_label: Optional[str] = None
    score: float = 0.5
    citation: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"index": self.index, "text": self.text[:600], "origin_tool": self.origin_tool,
                "source_type": self.source_type, "document_id": self.document_id, "title": self.title,
                "page_number": self.page_number, "timespan": self.timespan,
                "speaker_label": self.speaker_label, "score": round(self.score, 4)}


@dataclass
class PhaseTimings:
    planner_ms: float = 0.0
    research_ms: float = 0.0
    analysis_ms: float = 0.0
    writing_ms: float = 0.0
    total_ms: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {k: round(v, 3) for k, v in self.__dict__.items()}


@dataclass
class AgentStep:
    phase: str                           # planning | research | analysis | writing | done
    label: str
    detail: str = ""
    ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {"phase": self.phase, "label": self.label, "detail": self.detail, "ms": round(self.ms, 3)}


@dataclass
class AgentTaskResult:
    task_id: str
    agent: str
    task_type: str
    objective: str
    success: bool
    phase: str
    output: Any                          # StructuredOutput
    error: Optional[str] = None
    plan: Dict[str, Any] = field(default_factory=dict)
    steps: List[AgentStep] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    knowledge_gaps: List[str] = field(default_factory=list)
    timings: PhaseTimings = field(default_factory=PhaseTimings)
    tool_calls: int = 0
    retries: int = 0
    documents_used: int = 0
    media_used: int = 0
    workspace_used: bool = False
    token_usage: int = 0
    estimated_cost: float = 0.0
    timeline: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id, "agent": self.agent, "task_type": self.task_type,
            "objective": self.objective, "success": self.success, "phase": self.phase, "error": self.error,
            "plan": self.plan, "steps": [s.to_dict() for s in self.steps],
            "evidence": [e.to_dict() for e in self.evidence], "knowledge_gaps": self.knowledge_gaps,
            "output": self.output.to_dict() if self.output is not None else None,
            "citations": self.output.citations if self.output is not None else [],
            "timings": self.timings.to_dict(), "tool_calls": self.tool_calls, "retries": self.retries,
            "documents_used": self.documents_used, "media_used": self.media_used,
            "workspace_used": self.workspace_used, "token_usage": self.token_usage,
            "estimated_cost": round(self.estimated_cost, 3), "timeline": self.timeline,
        }


# --------------------------------------------------------------------- protocol
@runtime_checkable
class SpecializedAgent(Protocol):
    name: str
    task_type: str

    def run(self, task: AgentTask, ctx: AgentContext, *, executor, events) -> AgentTaskResult: ...


# --------------------------------------------------------------------- shared base
def _estimate_tokens(text: str) -> int:
    return max(0, len(text or "") // 4)


class BaseSpecializedAgent(ABC):
    """Reusable orchestration for every specialized agent.

    Subclasses implement `run()` but lean on these helpers so retrieval, evidence handling and
    inference are done ONE way across all agents:
      - `search_graph`  builds a parallel ExecutionGraph of existing search tools.
      - `gather`        runs that graph through the Module-1 executor and collects `Evidence`.
      - `synthesize`    builds a PromptPackage and calls the SINGLE answer pathway (`ctx.answer_fn`).
    """

    name: str = "specialized_agent"
    task_type: str = "generic"
    # search tools this agent uses in its research phase (all thin wrappers over existing retrieval)
    search_tools: List[str] = ["workspace_search"]

    # ------------------------------------------------------------------ retrieval
    def search_graph(self, tools: List[str], query: str, top_k: int) -> ExecutionGraph:
        g = ExecutionGraph()
        for i, tool in enumerate(tools):
            g.add(GraphNode(id=f"search_{i}", tool=tool, mode="parallel", on_failure="continue",
                            args={"query": query, "top_k": top_k}))
        return g

    def gather(self, ctx: AgentContext, executor, events, *, query: str, tools: Optional[List[str]] = None,
               top_k: int = 8, start_index: int = 0) -> List[Evidence]:
        """Run search tools through the framework executor and reshape ToolResults into ranked Evidence.

        Reuses the EXISTING retrieval engines (via the tools) — no new retrieval logic. Cancellation and
        permission gating are handled inside the executor.
        """
        graph = self.search_graph(tools or self.search_tools, query, top_k)
        results = executor.run_graph(graph, ctx, events)
        collected: List[ToolResult] = [r for r in results.values() if r is not None and r.ok]
        return self.collect_evidence(collected, start_index=start_index)

    def collect_evidence(self, results: List[ToolResult], *, start_index: int = 0) -> List[Evidence]:
        """Flatten tool citations/context into deduped, ranked Evidence with stable [n] indices."""
        items: List[Evidence] = []
        seen: set = set()
        for res in results:
            for c in (res.citations or []):
                key = (c.get("document_id"), c.get("chunk_id") or c.get("key"),
                       (c.get("text") or "")[:80], c.get("timespan"))
                if key in seen:
                    continue
                seen.add(key)
                items.append(Evidence(
                    index=0, text=(c.get("text") or c.get("content") or "").strip(),
                    origin_tool=res.tool, source_type=c.get("modality") or c.get("source_type") or "text",
                    document_id=c.get("document_id"), title=c.get("title"),
                    page_number=c.get("page_number"), timespan=c.get("timespan"),
                    speaker_label=c.get("speaker_label"),
                    score=float(c.get("confidence") or c.get("score") or 0.5), citation=dict(c)))
            # tools that contribute prose but no structured citations (e.g. unified_media_search)
            if not res.citations and res.context_text:
                for line in [l.strip() for l in res.context_text.splitlines() if l.strip()][:top_k_cap]:
                    key = (res.tool, line[:80])
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(Evidence(index=0, text=line, origin_tool=res.tool, score=0.4))
        items = [e for e in items if e.text]
        items.sort(key=lambda e: e.score, reverse=True)
        for i, e in enumerate(items, start=start_index + 1):
            e.index = i
            e.citation.setdefault("index", i)
        return items

    def rank(self, evidence: List[Evidence], *, limit: int = 24) -> List[Evidence]:
        ranked = sorted(evidence, key=lambda e: e.score, reverse=True)[:limit]
        for i, e in enumerate(ranked, start=1):
            e.index = i
        return ranked

    # ------------------------------------------------------------------ synthesis (single LLM pathway)
    def synthesize(self, ctx: AgentContext, *, system: str, instruction: str, evidence: List[Evidence],
                   extra_sections: Optional[List[PromptSection]] = None,
                   include_evidence_section: bool = True):
        """Assemble a PromptPackage from evidence + instruction and run the SINGLE answer pathway.

        The runtime NEVER calls the LLM directly — it renders the package and hands it to
        `ctx.answer_fn()` (prod = `answer_service.complete`, tests = injected fake). Same pathway as the
        Module-1 runtime and the rest of LexiMind.
        """
        pkg = PromptPackage(query=instruction)
        pkg.system = system
        for sec in (extra_sections or []):
            pkg.sections.append(sec)
        if evidence and include_evidence_section:
            body = "\n".join(self._evidence_line(e) for e in evidence)
            pkg.sections.append(PromptSection(title="Evidence", content=body))
        for e in evidence:
            pkg.citations.append(e.citation or {"index": e.index, "text": e.text[:300]})
        prompt = pkg.render()
        answer = (ctx.answer_fn()(prompt) or "").strip()
        return answer, prompt, pkg

    @staticmethod
    def _evidence_line(e: Evidence) -> str:
        tag = f"[{e.index}]"
        loc = ""
        if e.timespan:
            loc = f" ({e.timespan}{' · ' + e.speaker_label if e.speaker_label else ''})"
        elif e.page_number is not None:
            loc = f" (p{e.page_number})"
        return f"{tag}{loc} {e.text}".strip()

    # ------------------------------------------------------------------ scope helpers
    @staticmethod
    def count_media(ctx: AgentContext, document_ids: List[str]) -> int:
        if not document_ids:
            return 0
        try:
            from app.documents.repository import DocumentRepository
            repo = DocumentRepository(ctx.db)
            return sum(1 for d in document_ids
                       if (row := repo.get(d, ctx.owner_id)) and row.media_type in ("audio", "video"))
        except Exception:
            return 0

    # ------------------------------------------------------------------ contract
    @abstractmethod
    def run(self, task: AgentTask, ctx: AgentContext, *, executor, events) -> AgentTaskResult:
        raise NotImplementedError


# a soft cap for prose-only evidence extraction (kept module-level so it's easy to tune)
top_k_cap = 8
