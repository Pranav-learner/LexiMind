"""Research Agent (Step 3) — the primary autonomous worker.

Interpret objective → plan → search the workspace/documents/recordings (reusing Phase-1/4/5 retrieval
through the framework tools) → collect + rank evidence → identify knowledge gaps → synthesize a
grounded research report through the SINGLE answer pathway. Supports workspace-wide, document-specific,
topic, cross-document, cross-modal and timeline-aware research (the scope + tool selection adapt).

It creates NO retrieval or prompt pipeline of its own: `gather()`/`synthesize()` (in BaseSpecializedAgent)
run the existing tools + `answer_service.complete`.
"""

from __future__ import annotations

import re
import time
from typing import List, Optional

from app.agents.context import AgentContext
from app.agents.planner import _MEDIA_CUE
from app.agents.specialized.base import (
    AgentStep, AgentTask, AgentTaskResult, BaseSpecializedAgent, Evidence, PhaseTimings, _estimate_tokens,
)
from app.agents.specialized.outputs import StructuredOutput

_SPLIT = re.compile(r"\s+(?:and|vs\.?|versus|compared to|,|;)\s+", re.I)

_RESEARCH_SYSTEM = (
    "You are LexiMind's Research Agent — a rigorous analyst. Write a structured research report that "
    "answers the objective using ONLY the numbered evidence provided. Cite every claim with the "
    "bracketed [n] markers, preserve timestamps/speakers when the evidence carries them, and never "
    "invent facts. Organize the report as: a short Executive Summary, then Key Findings (grounded "
    "bullets), then a brief Analysis. If the evidence is insufficient for part of the objective, say so "
    "explicitly rather than speculating."
)


def derive_subquestions(objective: str, *, limit: int = 4) -> List[str]:
    """Lightweight objective decomposition (no LLM) — split conjunctions/comparisons into aspects.

    Deliberately heuristic and small; a future LLM planner replaces this behind the same call site.
    """
    obj = (objective or "").strip()
    if not obj:
        return []
    parts = [p.strip(" ?.") for p in _SPLIT.split(obj) if len(p.strip()) > 3]
    subs = [obj] + [p for p in parts if p.lower() != obj.lower()]
    # dedup preserving order
    seen, out = set(), []
    for s in subs:
        k = s.lower()
        if k not in seen:
            seen.add(k); out.append(s)
    return out[:limit]


class ResearchAgent(BaseSpecializedAgent):
    name = "research_agent"
    task_type = "research"
    search_tools = ["workspace_search"]

    def select_tools(self, task: AgentTask, ctx: AgentContext) -> List[str]:
        """Reuse the existing intent cue + document scope to decide whether recordings are in play.

        Phase-7 M2: `graph_search` (Semantic Memory) is always included as a retrieval provider — it is a
        cheap no-op when the workspace has no knowledge graph yet, and adds graph knowledge when it does.
        """
        tools = ["workspace_search", "graph_search", "graph_reason"]
        media = bool(_MEDIA_CUE.search(task.objective or "")) or self.count_media(ctx, task.document_ids) > 0
        if media:
            tools.append("temporal_search")
        return tools

    def run(self, task: AgentTask, ctx: AgentContext, *, executor, events) -> AgentTaskResult:
        t0 = time.perf_counter()
        timings = PhaseTimings()
        steps: List[AgentStep] = []
        result = AgentTaskResult(task_id=task.task_id, agent=self.name, task_type=self.task_type,
                                 objective=task.objective, success=False, phase="planning", output=None)

        # 1) PLAN --------------------------------------------------------------
        p = time.perf_counter()
        tools = self.select_tools(task, ctx)
        subqs = derive_subquestions(task.objective)
        top_k = int(task.params.get("top_k", 8))
        timings.planner_ms = (time.perf_counter() - p) * 1000
        steps.append(AgentStep("planning", "Planned research",
                               f"{len(subqs)} question(s), tools: {', '.join(tools)}", timings.planner_ms))
        events.emit("phase", {"phase": "planning", "subquestions": subqs, "tools": tools})
        result.plan = {"objective": task.objective, "subquestions": subqs, "tools": tools,
                       "scope": "document" if task.document_ids else "workspace"}

        if getattr(ctx, "_cancelled", False):
            return self._cancel(result, steps, timings, t0)

        # 2) RESEARCH ----------------------------------------------------------
        result.phase = "research"
        p = time.perf_counter()
        evidence: List[Evidence] = []
        per_sub: dict = {}
        for q in subqs:
            found = self.gather(ctx, executor, events, query=q, tools=tools, top_k=top_k,
                                start_index=len(evidence))
            per_sub[q] = len(found)
            evidence.extend(found)
            ctx.memory.cache_evidence(q, found) if hasattr(ctx.memory, "cache_evidence") else None
            if getattr(ctx, "_cancelled", False):
                return self._cancel(result, steps, timings, t0)
        evidence = self.rank(evidence, limit=int(task.params.get("evidence_limit", 24)))
        timings.research_ms = (time.perf_counter() - p) * 1000
        result.evidence = evidence
        result.tool_calls = len(subqs) * len(tools)
        steps.append(AgentStep("research", "Collected evidence",
                               f"{len(evidence)} ranked item(s) across {len(subqs)} question(s)",
                               timings.research_ms))
        events.emit("phase", {"phase": "research", "evidence": len(evidence)})

        # 3) ANALYSIS (gap identification, no LLM) -----------------------------
        result.phase = "analysis"
        p = time.perf_counter()
        gaps = [q for q, n in per_sub.items() if n == 0]
        result.knowledge_gaps = gaps
        timings.analysis_ms = (time.perf_counter() - p) * 1000
        steps.append(AgentStep("analysis", "Identified knowledge gaps",
                               f"{len(gaps)} unanswered question(s)", timings.analysis_ms))

        # 4) WRITE (single answer pathway) -------------------------------------
        result.phase = "writing"
        p = time.perf_counter()
        instruction = self._instruction(task, subqs, gaps)
        try:
            answer, prompt, pkg = self.synthesize(ctx, system=_RESEARCH_SYSTEM, instruction=instruction,
                                                  evidence=evidence)
        except Exception as e:
            timings.writing_ms = (time.perf_counter() - p) * 1000
            result.error = f"synthesis failed: {e}"
            result.phase = "failed"
            return self._finalize(result, steps, timings, t0, task, ctx, output=self._empty_output(task))
        timings.writing_ms = (time.perf_counter() - p) * 1000
        result.token_usage = _estimate_tokens(prompt) + _estimate_tokens(answer)
        steps.append(AgentStep("writing", "Synthesized research report",
                               f"{len(answer)} chars", timings.writing_ms))

        output = self.build_output(task, answer, evidence, subqs, gaps)
        result.success = True
        result.phase = "done"
        return self._finalize(result, steps, timings, t0, task, ctx, output=output)

    # ------------------------------------------------------------------ report assembly
    def build_output(self, task: AgentTask, report: str, evidence: List[Evidence], subqs: List[str],
                     gaps: List[str]) -> StructuredOutput:
        out = StructuredOutput(title=f"Research: {_short(task.objective)}",
                               summary=_first_line(report) or f"Research report on {_short(task.objective)}")
        out.heading("Objective", 2).markdown(task.objective)
        if subqs and len(subqs) > 1:
            out.heading("Research Plan", 2).bullet_list(subqs)
        out.heading("Report", 2).markdown(report or "_No report was generated._")
        if evidence:
            out.heading("Evidence", 2).bullet_list([self._evidence_line(e) for e in evidence[:16]])
        if gaps:
            out.heading("Knowledge Gaps", 2).bullet_list(gaps)
            out.callout("These aspects of the objective were not covered by the available evidence.")
        out.add_citations([e.citation or {"index": e.index, "text": e.text[:300]} for e in evidence])
        for e in evidence:
            if e.document_id:
                out.add_reference("timeline" if e.timespan else "document", document_id=e.document_id,
                                  title=e.title, timespan=e.timespan)
        out.citations_section()
        return out

    @staticmethod
    def _instruction(task: AgentTask, subqs: List[str], gaps: List[str]) -> str:
        lines = [f"Research objective: {task.objective}"]
        if len(subqs) > 1:
            lines.append("Cover these aspects: " + "; ".join(subqs))
        lines.append("Write the report grounded strictly in the numbered evidence, citing [n] markers.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ finalization helpers
    def _finalize(self, result: AgentTaskResult, steps, timings, t0, task, ctx, *, output) -> AgentTaskResult:
        timings.total_ms = (time.perf_counter() - t0) * 1000
        result.output = output
        result.steps = steps
        result.timings = timings
        result.documents_used = len({e.document_id for e in result.evidence if e.document_id})
        result.media_used = self.count_media(ctx, list({e.document_id for e in result.evidence if e.document_id}))
        result.workspace_used = not task.document_ids
        result.estimated_cost = round(result.tool_calls * 1.0 + 2.0, 3)
        result.timeline = ctx.events.timeline() if getattr(ctx, "events", None) else []
        return result

    def _cancel(self, result, steps, timings, t0) -> AgentTaskResult:
        result.phase = "cancelled"
        result.output = self._empty_output_for(result.objective)
        timings.total_ms = (time.perf_counter() - t0) * 1000
        result.steps = steps
        result.timings = timings
        return result

    def _empty_output(self, task: AgentTask) -> StructuredOutput:
        return self._empty_output_for(task.objective)

    @staticmethod
    def _empty_output_for(objective: str) -> StructuredOutput:
        return StructuredOutput(title=f"Research: {_short(objective)}", summary="No report produced.")


def _short(s: str, n: int = 80) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _first_line(s: str) -> str:
    for line in (s or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:200]
    return ""
