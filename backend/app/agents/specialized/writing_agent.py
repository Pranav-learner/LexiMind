"""Writing Agent (Step 4) — turns workspace knowledge into a long-form document.

Supports many document types (technical/research report, study guide, lecture notes, meeting minutes,
design doc, architecture summary, documentation, executive summary, plain Markdown). DOCX/PDF/slide
rendering is a FUTURE renderer over the same `StructuredOutput` — the agent produces the structured
deliverable once.

It REUSES the existing AnswerService (the single inference pathway via `synthesize`) — there is no
second writing pipeline. Evidence is either gathered fresh (reusing retrieval tools) or supplied by a
prior workflow step (`task.params["evidence"]`) so a Research → Write workflow never re-retrieves.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from app.agents.context import AgentContext
from app.agents.planner import _MEDIA_CUE
from app.agents.specialized.base import (
    AgentStep, AgentTask, AgentTaskResult, BaseSpecializedAgent, Evidence, PhaseTimings, _estimate_tokens,
)
from app.agents.specialized.outputs import StructuredOutput
from app.agents.specialized.research_agent import _first_line, _short

# doc_type → (title label, outline sections, style instruction)
DOC_TYPES: Dict[str, Dict[str, Any]] = {
    "technical_report": {"label": "Technical Report",
        "outline": ["Overview", "Background", "Details", "Findings", "Recommendations"],
        "style": "a precise technical report for an engineering audience"},
    "research_report": {"label": "Research Report",
        "outline": ["Executive Summary", "Key Findings", "Discussion", "Conclusion"],
        "style": "a rigorous research report with grounded findings"},
    "study_guide": {"label": "Study Guide",
        "outline": ["Overview", "Key Concepts", "Worked Examples", "Practice Questions", "Summary"],
        "style": "a student-friendly study guide optimized for learning and recall"},
    "lecture_notes": {"label": "Lecture Notes",
        "outline": ["Topics Covered", "Key Points", "Definitions", "Takeaways"],
        "style": "clear, structured lecture notes"},
    "meeting_minutes": {"label": "Meeting Minutes",
        "outline": ["Attendees & Context", "Discussion", "Decisions", "Action Items"],
        "style": "concise meeting minutes with decisions and action items"},
    "design_doc": {"label": "Design Document",
        "outline": ["Problem", "Goals & Non-Goals", "Proposed Design", "Alternatives", "Risks"],
        "style": "a software design document"},
    "architecture_summary": {"label": "Architecture Summary",
        "outline": ["System Overview", "Components", "Data Flow", "Trade-offs"],
        "style": "an architecture summary for technical stakeholders"},
    "documentation": {"label": "Documentation",
        "outline": ["Introduction", "Usage", "Reference", "Examples"],
        "style": "developer documentation"},
    "executive_summary": {"label": "Executive Summary",
        "outline": ["Summary", "Key Points", "Recommendation"],
        "style": "a one-page executive summary for leadership"},
    "markdown": {"label": "Document", "outline": [], "style": "a well-structured Markdown document"},
}
DEFAULT_DOC_TYPE = "research_report"


def _writing_system(doc_type: str) -> str:
    spec = DOC_TYPES.get(doc_type, DOC_TYPES[DEFAULT_DOC_TYPE])
    outline = ", ".join(spec["outline"]) if spec["outline"] else "sensible sections"
    return (
        f"You are LexiMind's Writing Agent. Produce {spec['style']} in Markdown, grounded ONLY in the "
        f"numbered evidence provided. Organize it with these sections where relevant: {outline}. Cite "
        "claims with the bracketed [n] markers, preserve timestamps/speakers when present, use headings, "
        "bullets and tables where they aid clarity, and never invent facts not in the evidence."
    )


class WritingAgent(BaseSpecializedAgent):
    name = "writing_agent"
    task_type = "writing"
    search_tools = ["workspace_search"]

    def run(self, task: AgentTask, ctx: AgentContext, *, executor, events) -> AgentTaskResult:
        t0 = time.perf_counter()
        timings = PhaseTimings()
        steps: List[AgentStep] = []
        doc_type = task.params.get("doc_type") or task.params.get("report_type") or DEFAULT_DOC_TYPE
        spec = DOC_TYPES.get(doc_type, DOC_TYPES[DEFAULT_DOC_TYPE])
        result = AgentTaskResult(task_id=task.task_id, agent=self.name, task_type=self.task_type,
                                 objective=task.objective, success=False, phase="planning", output=None)

        # 1) PLAN
        p = time.perf_counter()
        tools = ["workspace_search"] + (["temporal_search"]
                 if _MEDIA_CUE.search(task.objective or "") or self.count_media(ctx, task.document_ids)
                 else [])
        timings.planner_ms = (time.perf_counter() - p) * 1000
        result.plan = {"doc_type": doc_type, "outline": spec["outline"], "tools": tools}
        steps.append(AgentStep("planning", f"Planned {spec['label']}",
                               ", ".join(spec["outline"]) or "free-form", timings.planner_ms))
        events.emit("phase", {"phase": "planning", "doc_type": doc_type})

        # 2) RESEARCH — reuse supplied evidence if a prior step produced it (no repeated retrieval)
        result.phase = "research"
        p = time.perf_counter()
        evidence = self._provided_evidence(task)
        if evidence is None:
            evidence = self.gather(ctx, executor, events, query=task.objective, tools=tools,
                                   top_k=int(task.params.get("top_k", 8)))
            evidence = self.rank(evidence, limit=int(task.params.get("evidence_limit", 24)))
            result.tool_calls = len(tools)
            reused = False
        else:
            reused = True
        timings.research_ms = (time.perf_counter() - p) * 1000
        result.evidence = evidence
        steps.append(AgentStep("research", "Reused evidence" if reused else "Collected evidence",
                               f"{len(evidence)} item(s)", timings.research_ms))

        if getattr(ctx, "_cancelled", False):
            result.phase = "cancelled"; result.output = StructuredOutput(title=spec["label"])
            timings.total_ms = (time.perf_counter() - t0) * 1000
            result.steps, result.timings = steps, timings
            return result

        # 3) WRITE — single answer pathway
        result.phase = "writing"
        p = time.perf_counter()
        instruction = (f"Write {spec['label'].lower()} titled/for: {task.objective}. "
                       "Ground every claim in the numbered evidence with [n] citations.")
        try:
            answer, prompt, pkg = self.synthesize(ctx, system=_writing_system(doc_type),
                                                  instruction=instruction, evidence=evidence)
        except Exception as e:
            timings.writing_ms = (time.perf_counter() - p) * 1000
            result.error = f"synthesis failed: {e}"; result.phase = "failed"
            result.output = StructuredOutput(title=spec["label"])
            timings.total_ms = (time.perf_counter() - t0) * 1000
            result.steps, result.timings = steps, timings
            return result
        timings.writing_ms = (time.perf_counter() - p) * 1000
        result.token_usage = _estimate_tokens(prompt) + _estimate_tokens(answer)
        steps.append(AgentStep("writing", f"Wrote {spec['label']}", f"{len(answer)} chars", timings.writing_ms))

        output = self.build_output(task, spec, doc_type, answer, evidence)
        result.success = True
        result.phase = "done"
        timings.total_ms = (time.perf_counter() - t0) * 1000
        result.output, result.steps, result.timings = output, steps, timings
        result.documents_used = len({e.document_id for e in evidence if e.document_id})
        result.media_used = self.count_media(ctx, list({e.document_id for e in evidence if e.document_id}))
        result.workspace_used = not task.document_ids
        result.estimated_cost = round(result.tool_calls * 1.0 + 2.5, 3)
        result.timeline = ctx.events.timeline() if getattr(ctx, "events", None) else []
        return result

    def build_output(self, task, spec, doc_type, body: str, evidence: List[Evidence]) -> StructuredOutput:
        out = StructuredOutput(title=f"{spec['label']}: {_short(task.objective)}",
                               summary=_first_line(body) or f"{spec['label']} on {_short(task.objective)}")
        out.markdown(body or "_No content was generated._")
        out.add_citations([e.citation or {"index": e.index, "text": e.text[:300]} for e in evidence])
        for e in evidence:
            if e.document_id:
                out.add_reference("timeline" if e.timespan else "document", document_id=e.document_id,
                                  title=e.title, timespan=e.timespan)
        out.citations_section()
        return out

    @staticmethod
    def _provided_evidence(task: AgentTask):
        """Accept evidence handed down by a prior workflow step (Evidence objects or plain dicts)."""
        prov = task.params.get("evidence")
        if not prov:
            return None
        out: List[Evidence] = []
        for i, e in enumerate(prov, start=1):
            if isinstance(e, Evidence):
                out.append(e)
            elif isinstance(e, dict):
                out.append(Evidence(index=e.get("index", i), text=e.get("text", ""),
                                    origin_tool=e.get("origin_tool", "prior_step"),
                                    source_type=e.get("source_type", "text"),
                                    document_id=e.get("document_id"), title=e.get("title"),
                                    page_number=e.get("page_number"), timespan=e.get("timespan"),
                                    speaker_label=e.get("speaker_label"), score=float(e.get("score", 0.5)),
                                    citation=e.get("citation") or e))
        return out or None
