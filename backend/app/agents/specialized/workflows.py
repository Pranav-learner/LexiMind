"""Agent Workflows (Step 7) — reusable, serializable multi-step pipelines over specialized agents.

A workflow chains specialized-agent tasks (research → writing, compare → summarize, a study pack) with
declared dependencies and optional evidence hand-off (so a downstream step reuses an upstream step's
retrieved evidence instead of searching again — Step 14). Definitions are fully `to_dict`/`from_dict`
serializable so they can be persisted, edited, and — in Module 4 — executed collaboratively across
agents. The engine here executes them SEQUENTIALLY in dependency order within one request; the
`run_task` callback (supplied by the task service) is the seam a future distributed executor replaces.

The engine owns no agent/retrieval logic — it only orders steps, threads context, and forwards results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.agents.specialized.base import AgentTask, AgentTaskResult


@dataclass
class WorkflowStep:
    id: str
    task_type: str                       # research | writing | comparison | study
    description: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    forward_evidence: bool = False       # feed the dependency's evidence into this step (no re-retrieval)
    objective: Optional[str] = None       # override the workflow objective for this step

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "task_type": self.task_type, "description": self.description,
                "params": self.params, "depends_on": self.depends_on,
                "forward_evidence": self.forward_evidence, "objective": self.objective}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "WorkflowStep":
        return WorkflowStep(id=d["id"], task_type=d["task_type"], description=d.get("description", ""),
                            params=d.get("params", {}), depends_on=d.get("depends_on", []),
                            forward_evidence=d.get("forward_evidence", False), objective=d.get("objective"))


@dataclass
class WorkflowDefinition:
    name: str
    description: str
    steps: List[WorkflowStep] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "steps": [s.to_dict() for s in self.steps]}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "WorkflowDefinition":
        return WorkflowDefinition(name=d["name"], description=d.get("description", ""),
                                  steps=[WorkflowStep.from_dict(s) for s in d.get("steps", [])])

    def order(self) -> List[WorkflowStep]:
        """Topologically order steps (raises on a cycle/missing dep)."""
        remaining = {s.id: s for s in self.steps}
        done: set = set()
        ordered: List[WorkflowStep] = []
        while remaining:
            ready = [s for s in remaining.values() if all(dep in done for dep in s.depends_on)]
            if not ready:
                raise ValueError("Workflow has a dependency cycle or missing dependency.")
            for s in ready:
                ordered.append(s); done.add(s.id); del remaining[s.id]
        return ordered


class WorkflowEngine:
    def __init__(self, run_task: Callable[[AgentTask], AgentTaskResult]):
        self.run_task = run_task

    def run(self, definition: WorkflowDefinition, *, objective: str, workspace_id: str, owner_id: str,
            document_ids: Optional[List[str]] = None, base_params: Optional[Dict[str, Any]] = None,
            cancel_flag: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
        document_ids = document_ids or []
        base_params = base_params or {}
        results: Dict[str, AgentTaskResult] = {}
        step_out: List[Dict[str, Any]] = []
        for step in definition.order():
            if cancel_flag and cancel_flag():
                step_out.append({"step": step.id, "task_type": step.task_type, "skipped": True,
                                 "reason": "cancelled"})
                continue
            params = {**base_params, **step.params}
            if step.forward_evidence:
                dep_evidence = self._collect_dep_evidence(step, results)
                if dep_evidence:
                    params["evidence"] = dep_evidence
            task = AgentTask(task_type=step.task_type, objective=step.objective or objective,
                             workspace_id=workspace_id, owner_id=owner_id,
                             document_ids=document_ids, params=params)
            res = self.run_task(task)
            results[step.id] = res
            step_out.append({"step": step.id, "task_type": step.task_type, "task_id": res.task_id,
                             "success": res.success, "phase": res.phase,
                             "summary": res.output.summary if res.output else "",
                             "description": step.description})
        final = self._final_result(definition, results)
        return {"workflow": definition.name, "steps": step_out, "results": results,
                "final": final.to_dict() if final else None,
                "final_task_id": final.task_id if final else None}

    @staticmethod
    def _collect_dep_evidence(step: WorkflowStep, results: Dict[str, AgentTaskResult]) -> List[Any]:
        evidence: List[Any] = []
        for dep in step.depends_on:
            r = results.get(dep)
            if r is not None:
                evidence.extend(r.evidence)
        return evidence

    @staticmethod
    def _final_result(definition: WorkflowDefinition, results: Dict[str, AgentTaskResult]):
        # the final step in topological order that produced a result
        for step in reversed(definition.order()):
            if step.id in results:
                return results[step.id]
        return None


# --------------------------------------------------------------------- built-in workflows
def _builtin() -> Dict[str, WorkflowDefinition]:
    return {
        "research_and_write": WorkflowDefinition(
            name="research_and_write",
            description="Research the objective, then write a grounded report reusing the evidence.",
            steps=[
                WorkflowStep(id="research", task_type="research", description="Gather + rank evidence"),
                WorkflowStep(id="write", task_type="writing", description="Write the report",
                             depends_on=["research"], forward_evidence=True,
                             params={"doc_type": "research_report"}),
            ]),
        "compare_and_summarize": WorkflowDefinition(
            name="compare_and_summarize",
            description="Compare the targets, then produce an executive summary of the comparison.",
            steps=[
                WorkflowStep(id="compare", task_type="comparison", description="Compare the targets"),
                WorkflowStep(id="summary", task_type="writing", description="Executive summary",
                             depends_on=["compare"], forward_evidence=True,
                             params={"doc_type": "executive_summary"}),
            ]),
        "study_pack": WorkflowDefinition(
            name="study_pack",
            description="Produce a full study pack: study guide, flashcards and a learning path.",
            steps=[
                WorkflowStep(id="study", task_type="study", description="Generate materials + plan",
                             params={"deliverables": ["study_guide", "flashcards", "learning_path",
                                                      "weak_topics"]}),
            ]),
        "research_write_study": WorkflowDefinition(
            name="research_write_study",
            description="Research a topic, write a report, then build a study pack around it.",
            steps=[
                WorkflowStep(id="research", task_type="research", description="Research the topic"),
                WorkflowStep(id="write", task_type="writing", description="Write the report",
                             depends_on=["research"], forward_evidence=True,
                             params={"doc_type": "research_report"}),
                WorkflowStep(id="study", task_type="study", description="Build the study pack",
                             depends_on=["research"],
                             params={"deliverables": ["study_guide", "flashcards", "learning_path"]}),
            ]),
    }


WORKFLOWS: Dict[str, WorkflowDefinition] = _builtin()


def get_workflow(name: str) -> WorkflowDefinition:
    wf = WORKFLOWS.get(name)
    if wf is None:
        from app.agents.errors import AgentError

        class WorkflowNotFound(AgentError):
            status_code = 404
            code = "workflow_not_found"
        raise WorkflowNotFound(f"Workflow '{name}' is not registered.")
    return wf


def list_workflows() -> List[Dict[str, Any]]:
    return [wf.to_dict() for wf in WORKFLOWS.values()]
