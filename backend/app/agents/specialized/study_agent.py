"""Study Agent (Step 6) — turns workspace knowledge into a study programme.

REUSES the existing knowledge-asset services (Summaries / Notes / Flashcards) through the framework
generation tools (which enqueue via the injected async runners) and the Knowledge Dashboard (analytics)
— it duplicates NO business logic. On top of asset generation it synthesizes a learning-oriented plan
(study guide narrative, learning path, revision plan, weak-topic focus) through the single answer
pathway.

Deliverables (task.params["deliverables"], any subset):
  notes · study_guide · flashcards · quiz · summary · weak_topics · learning_path · revision_plan · exam_prep
Default: study_guide + flashcards + learning_path.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from app.agents.context import AgentContext
from app.agents.graph import ExecutionGraph, GraphNode
from app.agents.specialized.base import (
    AgentStep, AgentTask, AgentTaskResult, BaseSpecializedAgent, Evidence, PhaseTimings, _estimate_tokens,
)
from app.agents.specialized.outputs import StructuredOutput
from app.agents.specialized.research_agent import _first_line, _short

# deliverable → (kind, tool, tool-args-builder)  — kind ∈ asset | analysis | plan
_ASSET_DELIVERABLES = {
    "notes":       ("note",    "generate_notes",      {"note_type": "study"}),
    "study_guide": ("note",    "generate_notes",      {"note_type": "study"}),
    "revision":    ("note",    "generate_notes",      {"note_type": "revision"}),
    "summary":     ("summary", "generate_summary",    {"summary_type": "standard"}),
    "flashcards":  ("deck",    "generate_flashcards", {"count": 12}),
    "quiz":        ("deck",    "generate_flashcards", {"count": 10}),
}
_PLAN_DELIVERABLES = {"learning_path", "revision_plan", "exam_prep"}
DEFAULT_DELIVERABLES = ["study_guide", "flashcards", "learning_path"]

_STUDY_SYSTEM = (
    "You are LexiMind's Study Agent — an expert tutor. Using ONLY the numbered evidence and the "
    "workspace learning stats provided, produce a practical, encouraging study plan. Include: a short "
    "orientation, an ordered learning path (what to study first and why), a revision schedule, and a "
    "list of weak/at-risk topics to prioritise. Cite grounded claims with [n] markers; do not invent "
    "facts. Keep it actionable."
)


class StudyAgent(BaseSpecializedAgent):
    name = "study_agent"
    task_type = "study"
    search_tools = ["workspace_search"]

    def run(self, task: AgentTask, ctx: AgentContext, *, executor, events) -> AgentTaskResult:
        t0 = time.perf_counter()
        timings = PhaseTimings()
        steps: List[AgentStep] = []
        deliverables = [d for d in (task.params.get("deliverables") or DEFAULT_DELIVERABLES)]
        result = AgentTaskResult(task_id=task.task_id, agent=self.name, task_type=self.task_type,
                                 objective=task.objective, success=False, phase="planning", output=None)

        # 1) PLAN
        p = time.perf_counter()
        assets = [d for d in deliverables if d in _ASSET_DELIVERABLES]
        wants_plan = any(d in _PLAN_DELIVERABLES for d in deliverables) or not assets
        wants_weak = "weak_topics" in deliverables or wants_plan
        timings.planner_ms = (time.perf_counter() - p) * 1000
        result.plan = {"deliverables": deliverables, "assets": assets, "plan": wants_plan}
        steps.append(AgentStep("planning", "Planned study programme", ", ".join(deliverables), timings.planner_ms))
        events.emit("phase", {"phase": "planning", "deliverables": deliverables})

        # 2) GENERATE ASSETS — reuse the existing generation tools/services (async runners injected)
        result.phase = "research"
        p = time.perf_counter()
        created: List[Dict[str, Any]] = []
        if assets:
            graph = self._asset_graph(task, assets)
            gen_results = executor.run_graph(graph, ctx, events)
            for node in graph.nodes:
                r = gen_results.get(node.id)
                if r is not None and r.ok and r.output.get("asset_id"):
                    created.append({"deliverable": node.args.get("_deliverable"),
                                    "asset_type": r.output.get("asset_type"),
                                    "asset_id": r.output.get("asset_id"),
                                    "status": r.output.get("status"), "route": r.output.get("route")})
            result.tool_calls += len(graph.nodes)
        steps.append(AgentStep("research", "Generated study materials",
                               f"{len(created)} asset(s)", (time.perf_counter() - p) * 1000))

        # dashboard weak topics (reuse analytics) + evidence for the plan narrative
        dashboard: Dict[str, Any] = {}
        evidence: List[Evidence] = []
        if wants_weak:
            dashboard = self._query_dashboard(ctx, executor, events)
            result.tool_calls += 1
        if wants_plan:
            evidence = self.gather(ctx, executor, events, query=task.objective or "study overview",
                                   tools=["workspace_search"], top_k=int(task.params.get("top_k", 8)))
            evidence = self.rank(evidence, limit=16)
            result.tool_calls += 1
        result.evidence = evidence
        timings.research_ms = (time.perf_counter() - p) * 1000

        weak_topics = self._weak_topics(dashboard)

        # 3) WRITE the study plan (single answer pathway) — only if a plan was requested
        plan_text = ""
        result.phase = "writing"
        p = time.perf_counter()
        if wants_plan:
            extra = self._stats_section(dashboard, weak_topics)
            instruction = (f"Study objective: {task.objective or 'Master this workspace.'}\n"
                           "Produce the study plan grounded in the evidence and stats.")
            try:
                plan_text, prompt, pkg = self.synthesize(
                    ctx, system=_STUDY_SYSTEM, instruction=instruction, evidence=evidence,
                    extra_sections=extra)
                result.token_usage = _estimate_tokens(prompt) + _estimate_tokens(plan_text)
            except Exception as e:
                result.error = f"synthesis failed: {e}"
        timings.writing_ms = (time.perf_counter() - p) * 1000
        steps.append(AgentStep("writing", "Composed study plan",
                               f"{len(plan_text)} chars" if plan_text else "assets only", timings.writing_ms))

        output = self.build_output(task, plan_text, created, weak_topics, evidence)
        result.success = True
        result.phase = "done" if not result.error else "failed"
        timings.total_ms = (time.perf_counter() - t0) * 1000
        result.output, result.steps, result.timings = output, steps, timings
        result.documents_used = len(task.document_ids) or len({e.document_id for e in evidence if e.document_id})
        result.media_used = self.count_media(ctx, task.document_ids)
        result.workspace_used = not task.document_ids
        result.estimated_cost = round(result.tool_calls * 1.5 + 1.0, 3)
        result.timeline = ctx.events.timeline() if getattr(ctx, "events", None) else []
        # stash created assets for the service/task-log
        result.plan["created_assets"] = created
        return result

    # ------------------------------------------------------------------ graphs / tools
    def _asset_graph(self, task: AgentTask, assets: List[str]) -> ExecutionGraph:
        g = ExecutionGraph()
        doc = task.primary_document
        subject = task.params.get("subject") or task.objective
        for i, d in enumerate(assets):
            _, tool, base_args = _ASSET_DELIVERABLES[d]
            args = dict(base_args)
            args["_deliverable"] = d
            if doc:
                args["document_id"] = doc
            if subject:
                args["subject"] = subject
            # generation tools are not parallel_safe → sequential nodes
            g.add(GraphNode(id=f"gen_{i}", tool=tool, mode="sequential", on_failure="continue", args=args))
        return g

    def _query_dashboard(self, ctx, executor, events) -> Dict[str, Any]:
        g = ExecutionGraph()
        g.add(GraphNode(id="dash", tool="query_dashboard", mode="sequential", on_failure="continue",
                        args={"section": "learning"}))
        res = executor.run_graph(g, ctx, events).get("dash")
        if res is not None and res.ok:
            return res.output.get("data") or {}
        return {}

    @staticmethod
    def _weak_topics(dashboard: Dict[str, Any]) -> List[str]:
        # analytics 'learning' widget shapes vary; probe a few likely keys defensively.
        for key in ("weak_topics", "at_risk", "struggling_topics", "low_mastery"):
            val = dashboard.get(key)
            if isinstance(val, list) and val:
                return [str(v.get("topic") if isinstance(v, dict) else v) for v in val][:10]
        return []

    @staticmethod
    def _stats_section(dashboard: Dict[str, Any], weak_topics: List[str]):
        from app.agents.prompt_package import PromptSection
        lines = []
        if weak_topics:
            lines.append("Weak / at-risk topics: " + ", ".join(weak_topics))
        if dashboard:
            keep = {k: v for k, v in dashboard.items() if isinstance(v, (int, float, str))}
            if keep:
                lines.append("Learning stats: " + ", ".join(f"{k}={v}" for k, v in list(keep.items())[:12]))
        return [PromptSection(title="Workspace learning stats", content="\n".join(lines))] if lines else []

    # ------------------------------------------------------------------ output
    def build_output(self, task, plan_text: str, created: List[Dict[str, Any]], weak_topics: List[str],
                     evidence: List[Evidence]) -> StructuredOutput:
        out = StructuredOutput(title=f"Study: {_short(task.objective or 'Workspace')}",
                               summary=_first_line(plan_text) or "Study programme and generated materials.")
        if plan_text:
            out.heading("Study Plan", 2).markdown(plan_text)
        if created:
            out.heading("Generated Study Materials", 2).table(
                ["Deliverable", "Type", "Status", "Open"],
                [[c["deliverable"], c["asset_type"], c.get("status") or "queued", c.get("route") or ""]
                 for c in created])
            for c in created:
                out.add_reference("asset", document_id=c.get("asset_id"), title=c["deliverable"],
                                  route=c.get("route"))
        if weak_topics:
            out.heading("Priority (Weak) Topics", 2).bullet_list(weak_topics)
        out.add_citations([e.citation or {"index": e.index, "text": e.text[:300]} for e in evidence])
        out.citations_section()
        return out
