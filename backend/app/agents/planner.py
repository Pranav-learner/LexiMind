"""Agent Planner (Step 7) — a lightweight, replaceable planning strategy.

Interpret intent → decide whether tools are needed → emit an ordered `ExecutionGraph` + a cost
estimate. Deliberately heuristic (no LLM call in planning — Step 14: avoid unnecessary inference) and
deliberately small, because a future module replaces it with LLM reasoning behind the SAME `Planner`
protocol. It REUSES the existing intent analyzers (temporal + multimodal) rather than re-deriving
intent, so planning stays consistent with retrieval.

Strategy:
- Generation intent ("summarize", "flashcards", "study notes") → a single generation tool node.
- Otherwise a retrieval-and-answer plan: a parallel layer of the relevant search tools (workspace
  always; temporal added when the query has temporal/media cues or a recording is in scope), which the
  runtime synthesizes into one grounded answer.
- Trivial small-talk → no tools (the runtime answers directly), so we never pay for retrieval/LLM tools
  we don't need.
"""

from __future__ import annotations

import re
from typing import List

from app.agents.graph import ExecutionGraph, ExecutionPlan, GraphNode
from app.agents.registry import tool_registry

_GEN_SUMMARY = re.compile(r"\b(summar(y|ise|ize)|tl;?dr|overview of|recap)\b", re.I)
_GEN_FLASH = re.compile(r"\b(flash ?cards?|quiz me|test me|revision cards?)\b", re.I)
_GEN_NOTES = re.compile(r"\b(study notes|make notes|take notes|write notes|revision notes)\b", re.I)
_GREETING = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|yo|good (morning|evening|afternoon))\b", re.I)
_MEDIA_CUE = re.compile(r"\b(lecture|meeting|podcast|recording|video|audio|transcript|speaker|said|"
                        r"timestamp|chapter|at \d{1,2}:\d{2}|minute|scene|discussion)\b", re.I)


class HeuristicPlanner:
    name = "heuristic-v1"

    def plan(self, ctx) -> ExecutionPlan:
        q = ctx.query or ""
        reg = tool_registry()
        graph = ExecutionGraph()
        intents: List[str] = []
        rationale = ""

        # 1) generation intents → single generation node (no retrieval needed)
        if _GEN_FLASH.search(q):
            graph.add(GraphNode(id="gen", tool="generate_flashcards", mode="sequential", on_failure="abort"))
            intents = ["generate_flashcards"]; rationale = "User asked to create flashcards."
        elif _GEN_NOTES.search(q):
            graph.add(GraphNode(id="gen", tool="generate_notes", mode="sequential", on_failure="abort"))
            intents = ["generate_notes"]; rationale = "User asked to create study notes."
        elif _GEN_SUMMARY.search(q):
            graph.add(GraphNode(id="gen", tool="generate_summary", mode="sequential", on_failure="abort"))
            intents = ["generate_summary"]; rationale = "User asked for a summary."
        # 2) trivial small-talk → no tools
        elif _GREETING.search(q) and len(q.split()) <= 4:
            return ExecutionPlan(query=q, requires_tools=False, graph=graph, planner=self.name,
                                 rationale="Small talk — answer directly, no tools.", estimated_cost=1.0,
                                 intents=["direct_answer"])
        # 3) default: retrieve-and-answer (parallel search layer)
        else:
            wants_media = bool(_MEDIA_CUE.search(q)) or self._is_media_scope(ctx)
            graph.add(GraphNode(id="search_ws", tool="workspace_search", mode="parallel", on_failure="continue"))
            intents.append("workspace_search")
            if wants_media:
                graph.add(GraphNode(id="search_time", tool="temporal_search", mode="parallel", on_failure="continue"))
                intents.append("temporal_search")
            rationale = ("Retrieve across the workspace" + (" and recordings" if wants_media else "")
                         + ", then answer with citations.")

        cost = sum(reg.spec(n.tool).cost_weight for n in graph.nodes) + 1.0  # +1 for the single LLM call
        return ExecutionPlan(query=q, requires_tools=bool(graph.nodes), graph=graph, planner=self.name,
                             rationale=rationale, estimated_cost=cost, intents=intents)

    @staticmethod
    def _is_media_scope(ctx) -> bool:
        if not ctx.document_id:
            return False
        try:
            from app.documents.repository import DocumentRepository
            doc = DocumentRepository(ctx.db).get(ctx.document_id, ctx.owner_id)
            return bool(doc and doc.media_type in ("audio", "video"))
        except Exception:
            return False
