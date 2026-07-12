"""Comparison Agent (Step 5) — compare two or more targets and surface the relationship.

Targets are documents, recordings or topics. For each target the agent gathers scoped evidence
(reusing the retrieval tools), then synthesizes a structured comparison — Similarities, Differences,
Conflicts, Missing Information — grounded in the numbered evidence, plus a side-by-side table.

Supports: document vs document, lecture vs lecture, lecture vs textbook, meeting vs design doc,
research-paper comparison, image/diagram/architecture comparison (the modality follows whatever the
scoped documents contain — retrieval is multimodal).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.agents.context import AgentContext
from app.agents.planner import _MEDIA_CUE
from app.agents.prompt_package import PromptSection
from app.agents.specialized.base import (
    AgentStep, AgentTask, AgentTaskResult, BaseSpecializedAgent, Evidence, PhaseTimings, _estimate_tokens,
)
from app.agents.specialized.outputs import StructuredOutput
from app.agents.specialized.research_agent import _first_line, _short

_COMPARE_SYSTEM = (
    "You are LexiMind's Comparison Agent. Compare the labelled targets using ONLY the numbered evidence "
    "under each target. Produce four clearly headed sections — **Similarities**, **Differences**, "
    "**Conflicts** (claims that contradict each other), and **Missing Information** (what one target "
    "covers that another lacks). Cite every point with [n] markers referencing the evidence, and never "
    "invent facts. Be specific and attribute each point to the target(s) it came from."
)


class ComparisonAgent(BaseSpecializedAgent):
    name = "comparison_agent"
    task_type = "comparison"

    def resolve_targets(self, task: AgentTask, ctx: AgentContext) -> List[Dict[str, Any]]:
        """Build the list of targets from explicit params, scoped documents, or an 'X vs Y' objective."""
        explicit = task.params.get("targets")
        if explicit:
            out = []
            for i, t in enumerate(explicit, start=1):
                if isinstance(t, dict):
                    out.append({"label": t.get("label") or t.get("topic") or t.get("document_id") or f"Target {i}",
                                "document_id": t.get("document_id"), "topic": t.get("topic")})
                else:
                    out.append({"label": str(t), "document_id": None, "topic": str(t)})
            return out
        if len(task.document_ids) >= 2:
            return [{"label": self._doc_label(ctx, d), "document_id": d, "topic": None}
                    for d in task.document_ids]
        # fall back to splitting the objective on comparison connectors
        from app.agents.specialized.research_agent import _SPLIT
        parts = [p.strip(" ?.") for p in _SPLIT.split(task.objective or "") if len(p.strip()) > 2]
        if len(parts) >= 2:
            return [{"label": p, "document_id": None, "topic": p} for p in parts[:4]]
        return []

    def run(self, task: AgentTask, ctx: AgentContext, *, executor, events) -> AgentTaskResult:
        t0 = time.perf_counter()
        timings = PhaseTimings()
        steps: List[AgentStep] = []
        result = AgentTaskResult(task_id=task.task_id, agent=self.name, task_type=self.task_type,
                                 objective=task.objective, success=False, phase="planning", output=None)

        # 1) PLAN — resolve targets
        p = time.perf_counter()
        targets = self.resolve_targets(task, ctx)
        timings.planner_ms = (time.perf_counter() - p) * 1000
        result.plan = {"targets": [t["label"] for t in targets], "objective": task.objective}
        steps.append(AgentStep("planning", "Resolved comparison targets",
                               ", ".join(t["label"] for t in targets) or "none", timings.planner_ms))
        events.emit("phase", {"phase": "planning", "targets": [t["label"] for t in targets]})

        if len(targets) < 2:
            result.error = "A comparison needs at least two targets (documents or topics)."
            result.phase = "failed"
            result.output = StructuredOutput(title="Comparison", summary=result.error)
            timings.total_ms = (time.perf_counter() - t0) * 1000
            result.steps, result.timings = steps, timings
            return result

        # 2) RESEARCH — gather evidence per target (scoped)
        result.phase = "research"
        p = time.perf_counter()
        top_k = int(task.params.get("top_k", 6))
        per_target: List[Dict[str, Any]] = []
        all_evidence: List[Evidence] = []
        saved_doc = ctx.document_id
        for tgt in targets:
            query = tgt.get("topic") or task.objective
            tools = ["workspace_search"]
            ctx.document_id = tgt.get("document_id") or None
            if tgt.get("document_id") and self.count_media(ctx, [tgt["document_id"]]):
                tools.append("temporal_search")
            elif _MEDIA_CUE.search(query or ""):
                tools.append("temporal_search")
            ev = self.gather(ctx, executor, events, query=query, tools=tools, top_k=top_k,
                             start_index=len(all_evidence))
            per_target.append({"target": tgt, "evidence": ev})
            all_evidence.extend(ev)
            result.tool_calls += len(tools)
            if getattr(ctx, "_cancelled", False):
                break
        ctx.document_id = saved_doc
        timings.research_ms = (time.perf_counter() - p) * 1000
        result.evidence = all_evidence
        steps.append(AgentStep("research", "Collected per-target evidence",
                               f"{len(all_evidence)} item(s) across {len(targets)} target(s)", timings.research_ms))

        # 3) WRITE — labelled evidence sections → single answer pathway
        result.phase = "writing"
        p = time.perf_counter()
        sections = self._labelled_sections(per_target)
        instruction = (f"Comparison objective: {task.objective or 'Compare the targets.'}\n"
                       "Compare: " + " vs ".join(t["target"]["label"] for t in per_target))
        try:
            answer, prompt, pkg = self.synthesize(ctx, system=_COMPARE_SYSTEM, instruction=instruction,
                                                  evidence=all_evidence, extra_sections=sections,
                                                  include_evidence_section=False)
        except Exception as e:
            timings.writing_ms = (time.perf_counter() - p) * 1000
            result.error = f"synthesis failed: {e}"; result.phase = "failed"
            result.output = StructuredOutput(title="Comparison")
            timings.total_ms = (time.perf_counter() - t0) * 1000
            result.steps, result.timings = steps, timings
            return result
        timings.writing_ms = (time.perf_counter() - p) * 1000
        result.token_usage = _estimate_tokens(prompt) + _estimate_tokens(answer)
        steps.append(AgentStep("writing", "Synthesized comparison", f"{len(answer)} chars", timings.writing_ms))

        output = self.build_output(task, per_target, answer, all_evidence)
        result.success = True
        result.phase = "done"
        timings.total_ms = (time.perf_counter() - t0) * 1000
        result.output, result.steps, result.timings = output, steps, timings
        result.documents_used = len({e.document_id for e in all_evidence if e.document_id})
        result.media_used = self.count_media(ctx, list({e.document_id for e in all_evidence if e.document_id}))
        result.workspace_used = not task.document_ids
        result.estimated_cost = round(result.tool_calls * 1.0 + 2.0, 3)
        result.timeline = ctx.events.timeline() if getattr(ctx, "events", None) else []
        return result

    # ------------------------------------------------------------------ helpers
    def _labelled_sections(self, per_target: List[Dict[str, Any]]) -> List[PromptSection]:
        secs = []
        for grp in per_target:
            label = grp["target"]["label"]
            body = "\n".join(self._evidence_line(e) for e in grp["evidence"]) or "(no evidence found)"
            secs.append(PromptSection(title=f"Evidence — {label}", content=body))
        return secs

    def build_output(self, task, per_target, body: str, evidence: List[Evidence]) -> StructuredOutput:
        labels = [g["target"]["label"] for g in per_target]
        out = StructuredOutput(title=f"Comparison: {' vs '.join(_short(l, 32) for l in labels)}",
                               summary=_first_line(body) or f"Comparison of {', '.join(labels)}")
        out.heading("Targets", 2).table(
            ["Target", "Evidence items", "Scope"],
            [[g["target"]["label"], len(g["evidence"]),
              g["target"].get("document_id") or "topic"] for g in per_target])
        out.heading("Comparison", 2).markdown(body or "_No comparison was generated._")
        out.add_citations([e.citation or {"index": e.index, "text": e.text[:300]} for e in evidence])
        for e in evidence:
            if e.document_id:
                out.add_reference("timeline" if e.timespan else "document", document_id=e.document_id,
                                  title=e.title, timespan=e.timespan)
        out.citations_section()
        return out

    @staticmethod
    def _doc_label(ctx: AgentContext, document_id: str) -> str:
        try:
            from app.documents.repository import DocumentRepository
            row = DocumentRepository(ctx.db).get(document_id, ctx.owner_id)
            if row is not None:
                return row.display_name or row.filename or document_id
        except Exception:
            pass
        return document_id
