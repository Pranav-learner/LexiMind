"""Workflow Registry (Step 8) — declarative, reusable multi-agent templates.

Templates are named `TaskGraph`s a UI can pick (and, later, compose visually). They are serializable, so
a custom graph submitted over the API is just an unnamed template. New agents/templates register here
with no scheduler change.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.orchestration.errors import WorkflowNotFound
from app.orchestration.interfaces import TaskGraph, TaskNode


def _tpl(nodes: List[TaskNode]) -> TaskGraph:
    return TaskGraph(nodes=nodes)


TEMPLATES: Dict[str, Dict[str, Any]] = {
    "research_report": {
        "description": "Research a topic, then write a verified report.",
        "graph": _tpl([
            TaskNode(id="research", agent="research", priority=1),
            TaskNode(id="writing", agent="writing", depends_on=["research"], priority=2,
                     forward_evidence=True, params={"doc_type": "research_report"}),
            TaskNode(id="verification", agent="verification", depends_on=["writing"], priority=8,
                     optional=True, params={"mode": "fast"}),
        ]),
    },
    "compare_and_report": {
        "description": "Research, compare sources, write a report, and verify it.",
        "graph": _tpl([
            TaskNode(id="research", agent="research", priority=1),
            TaskNode(id="comparison", agent="comparison", depends_on=["research"], priority=2,
                     forward_evidence=True),
            TaskNode(id="writing", agent="writing", depends_on=["comparison"], priority=3,
                     forward_evidence=True, params={"doc_type": "research_report"}),
            TaskNode(id="verification", agent="verification", depends_on=["writing"], priority=8,
                     optional=True, params={"mode": "fast"}),
        ]),
    },
    "study_pipeline": {
        "description": "Research a topic then build a study guide + flashcards in parallel, and verify.",
        "graph": _tpl([
            TaskNode(id="research", agent="research", priority=1),
            TaskNode(id="writing", agent="writing", depends_on=["research"], priority=2,
                     forward_evidence=True, params={"doc_type": "study_guide"}),
            TaskNode(id="study", agent="study", depends_on=["research"], priority=2, optional=True,
                     params={"deliverables": ["study_guide", "flashcards", "learning_path"]}),
            TaskNode(id="verification", agent="verification", depends_on=["writing", "study"],
                     priority=8, optional=True, params={"mode": "fast"}),
        ]),
    },
    "full_research_suite": {
        "description": "Research → compare → report + study pack (parallel) → verify. The full team.",
        "graph": _tpl([
            TaskNode(id="research", agent="research", priority=1),
            TaskNode(id="comparison", agent="comparison", depends_on=["research"], priority=2,
                     forward_evidence=True, optional=True),
            TaskNode(id="writing", agent="writing", depends_on=["research", "comparison"], priority=3,
                     forward_evidence=True, params={"doc_type": "research_report"}),
            TaskNode(id="study", agent="study", depends_on=["research"], priority=3, optional=True,
                     params={"deliverables": ["study_guide", "flashcards"]}),
            TaskNode(id="verification", agent="verification", depends_on=["writing", "study"],
                     priority=8, optional=True, params={"mode": "fast"}),
        ]),
    },
}


def get_template(name: str) -> TaskGraph:
    tpl = TEMPLATES.get(name)
    if tpl is None:
        raise WorkflowNotFound(name)
    # deep-copy via (de)serialization so a run never mutates the shared template
    return TaskGraph.from_dict(tpl["graph"].to_dict())


def list_templates() -> List[Dict[str, Any]]:
    return [{"name": name, "description": t["description"], "graph": t["graph"].to_dict()}
            for name, t in TEMPLATES.items()]
