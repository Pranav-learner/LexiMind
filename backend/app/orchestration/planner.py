"""Task Planner (Step 3) — decompose a user objective into a multi-agent task graph.

Heuristic + LLM-free (Step 15: no unnecessary inference): it reads the objective's intent cues and
composes a dependency graph of specialized-agent tasks. Example:

    "Compare these three papers and generate a study guide"
        research  →  comparison  →  writing(study_guide)  →  study(flashcards)  →  verification

Each downstream node depends on research (and reuses its evidence — `forward_evidence`), so retrieval
runs once. The graph is a serializable `TaskGraph`; a future LLM/interactive planner replaces this
behind the `TaskPlanner` protocol. A named template (from the registry) bypasses decomposition.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.orchestration.interfaces import OrchestrationPlan, TaskGraph, TaskNode

_COMPARE = re.compile(r"\b(compare|comparison|versus|vs\.?|differ|difference|contrast|against)\b", re.I)
_WRITE = re.compile(r"\b(write|report|document|draft|summary|summarise|summarize|memo|brief|guide|"
                    r"notes|documentation|minutes)\b", re.I)
_STUDY = re.compile(r"\b(study|flash ?cards?|quiz|revision|revise|exam|learn|practice|memorise|memorize)\b", re.I)
_RESEARCH = re.compile(r"\b(research|investigate|analy[sz]e|explain|explore|find out|survey|review|"
                       r"understand|summar)\b", re.I)
_VERIFY = re.compile(r"\b(verify|verified|fact.?check|validate|accurate|accuracy|trustworthy)\b", re.I)

_DOC_TYPE = [
    (re.compile(r"\bstudy guide\b", re.I), "study_guide"),
    (re.compile(r"\b(exec(utive)? summary)\b", re.I), "executive_summary"),
    (re.compile(r"\b(technical report)\b", re.I), "technical_report"),
    (re.compile(r"\b(design doc(ument)?)\b", re.I), "design_doc"),
    (re.compile(r"\b(lecture notes)\b", re.I), "lecture_notes"),
    (re.compile(r"\b(meeting minutes|minutes)\b", re.I), "meeting_minutes"),
]


def _doc_type(objective: str) -> str:
    for rx, dt in _DOC_TYPE:
        if rx.search(objective):
            return dt
    return "research_report"


class TaskPlanner:
    name = "heuristic-v1"

    def decompose(self, objective: str, *, document_ids: List[str], params: Dict[str, Any]) -> OrchestrationPlan:
        obj = objective or ""
        wants_compare = bool(_COMPARE.search(obj)) or len(document_ids) >= 2
        wants_write = bool(_WRITE.search(obj))
        wants_study = bool(_STUDY.search(obj))
        wants_verify = params.get("verify_workflow", True) and (bool(_VERIFY.search(obj)) or wants_write or wants_compare)

        graph = TaskGraph()
        leaves: List[str] = []

        # 1) research is the evidence base for the whole team (always first)
        graph.add(TaskNode(id="research", agent="research", priority=1,
                           params={"top_k": params.get("top_k", 8)}))
        upstream = "research"

        # 2) comparison (depends on research; reuses its evidence)
        if wants_compare:
            graph.add(TaskNode(id="comparison", agent="comparison", depends_on=["research"], priority=2,
                               forward_evidence=True))
            upstream = "comparison"
            leaves.append("comparison")

        # 3) writing (depends on the strongest upstream analysis; reuses evidence)
        if wants_write or not (wants_study or wants_compare):
            graph.add(TaskNode(id="writing", agent="writing", depends_on=list({"research", upstream}),
                               priority=3, forward_evidence=True,
                               params={"doc_type": _doc_type(obj)}))
            leaves.append("writing")

        # 4) study pack (depends on research; runs in PARALLEL with writing)
        if wants_study:
            graph.add(TaskNode(id="study", agent="study", depends_on=["research"], priority=3,
                               optional=True,
                               params={"deliverables": params.get("deliverables",
                                       ["study_guide", "flashcards", "learning_path"])}))
            leaves.append("study")

        if not leaves:
            leaves = ["research"]

        # 5) verification node — checks the assembled leaves (optional, never aborts the workflow)
        if wants_verify:
            graph.add(TaskNode(id="verification", agent="verification", depends_on=leaves, priority=8,
                               optional=True, forward_evidence=True,
                               params={"mode": params.get("verify_mode", "fast")}))

        rationale = ("Decomposed into: " + " → ".join(n.id for n in graph.nodes)
                     + f" ({graph.max_width()}-wide, depth {graph.depth()}).")
        return OrchestrationPlan(objective=obj, graph=graph, planner=self.name, workflow="custom",
                                 rationale=rationale)
