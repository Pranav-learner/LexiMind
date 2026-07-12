"""Unit tests for the Phase-6 Module-2 specialized agents — pure/offline (no HTTP, no LLM, no faiss).

Covers the structured-output formatter, the workflow engine (serialize + topo order + evidence
forwarding), task memory, evidence collection/ranking, and each specialized agent's phase machine
driven by a tiny fake executor + a stub context (fake answer function).
"""

from __future__ import annotations

from app.agents.events import InMemoryEventSink
from app.agents.interfaces import ToolResult
from app.agents.specialized.base import AgentTask, BaseSpecializedAgent, Evidence
from app.agents.specialized.comparison_agent import ComparisonAgent
from app.agents.specialized.outputs import StructuredOutput
from app.agents.specialized.research_agent import ResearchAgent, derive_subquestions
from app.agents.specialized.study_agent import StudyAgent
from app.agents.specialized.task_memory import TaskMemory
from app.agents.specialized.workflows import (
    WorkflowDefinition, WorkflowEngine, WorkflowStep, get_workflow, list_workflows,
)
from app.agents.specialized.writing_agent import DOC_TYPES, WritingAgent


# --------------------------------------------------------------------- stubs
class _Ctx:
    """Minimal AgentContext stand-in (db=None → count_media degrades to 0)."""

    def __init__(self, *, answer="SYNTH ANSWER\n- point one [1]", doc=None):
        self.db = None
        self.owner_id = "o"; self.workspace_id = "ws"; self.document_id = doc
        self.params = {}; self.services = {"answer_fn": lambda p: answer}
        self.memory = TaskMemory(); self.events = InMemoryEventSink(); self._cancelled = False

    def answer_fn(self):
        return self.services["answer_fn"]


class _FakeExec:
    """Returns a deterministic ToolResult per graph node, keyed by tool name."""

    def __init__(self, per_tool=None):
        self.per_tool = per_tool or {}
        self.calls = 0

    def run_graph(self, graph, ctx, events):
        self.calls += 1
        out = {}
        for n in graph.nodes:
            out[n.id] = self.per_tool.get(n.tool, self._default(n.tool))
        return out

    @staticmethod
    def _default(tool):
        return ToolResult(tool=tool, ok=True, context_text=f"{tool} evidence",
                          citations=[{"index": 1, "text": f"evidence from {tool}", "document_id": "doc_x",
                                      "confidence": 0.9, "title": "Doc X"}])


# --------------------------------------------------------------------- structured output
def test_structured_output_markdown_and_dict():
    o = StructuredOutput(title="Report", summary="s")
    o.heading("Overview").markdown("Body text.").bullet_list(["a", "b"])
    o.table(["Name", "Val"], [["x", 1], ["y|z", 2]])
    o.code("print(1)", "python").callout("note")
    o.add_citations([{"index": 1, "text": "ev", "title": "Doc", "page_number": 3}]).citations_section()
    md = o.to_markdown()
    assert "# Report" in md and "## Overview" in md and "- a" in md
    assert "| Name | Val |" in md and "y\\|z" in md          # pipe escaped
    assert "```python" in md and "> note" in md
    assert "**[1]**" in md                                    # citation rendered
    d = o.to_dict()
    assert d["markdown"] == md and d["title"] == "Report" and len(d["citations"]) == 1


def test_output_empty_lists_are_skipped():
    o = StructuredOutput(title="T")
    o.bullet_list([]).markdown("   ")
    assert o.to_markdown().strip() == "# T"


# --------------------------------------------------------------------- workflows
def test_workflow_serialize_roundtrip():
    wf = get_workflow("research_and_write")
    d = wf.to_dict()
    wf2 = WorkflowDefinition.from_dict(d)
    assert wf2.name == "research_and_write" and len(wf2.steps) == 2
    assert wf2.steps[1].forward_evidence is True and wf2.steps[1].depends_on == ["research"]


def test_workflow_topological_order_and_cycle():
    wf = WorkflowDefinition(name="w", description="", steps=[
        WorkflowStep(id="c", task_type="writing", depends_on=["a", "b"]),
        WorkflowStep(id="a", task_type="research"),
        WorkflowStep(id="b", task_type="research"),
    ])
    order = [s.id for s in wf.order()]
    assert order.index("a") < order.index("c") and order.index("b") < order.index("c")
    bad = WorkflowDefinition(name="w", description="", steps=[
        WorkflowStep(id="a", task_type="research", depends_on=["b"]),
        WorkflowStep(id="b", task_type="research", depends_on=["a"])])
    try:
        bad.order(); assert False, "expected cycle error"
    except ValueError:
        pass


def test_workflow_engine_runs_in_order_and_forwards_evidence():
    seen = []

    def run_task(task: AgentTask):
        seen.append((task.task_type, "evidence" in task.params))
        from app.agents.specialized.base import AgentTaskResult
        return AgentTaskResult(task_id=f"t_{task.task_type}", agent=task.task_type, task_type=task.task_type,
                               objective=task.objective, success=True, phase="done",
                               output=StructuredOutput(title=task.task_type, summary="ok"),
                               evidence=[Evidence(index=1, text="e", origin_tool="x")])

    eng = WorkflowEngine(run_task=run_task)
    out = eng.run(get_workflow("research_and_write"), objective="topic", workspace_id="ws", owner_id="o")
    assert [t for t, _ in seen] == ["research", "writing"]
    assert seen[1][1] is True                                  # writing step received forwarded evidence
    assert len(out["steps"]) == 2 and out["final_task_id"] == "t_writing"


def test_builtin_workflows_present():
    names = {w["name"] for w in list_workflows()}
    assert {"research_and_write", "compare_and_summarize", "study_pack"} <= names


# --------------------------------------------------------------------- task memory
def test_task_memory_scopes_and_evidence_cache():
    m = TaskMemory()
    m.cache_evidence("q1", [Evidence(index=1, text="a", origin_tool="t")])
    m.put_result("research", {"n": 1}); m.note("thinking")
    assert len(m.cached_evidence("q1")) == 1 and len(m.all_evidence()) == 1
    assert m.get_result("research") == {"n": 1} and m.notes() == ["thinking"]
    snap = m.snapshot()
    assert "q1" in snap["evidence_keys"] and snap["note_count"] == 1


# --------------------------------------------------------------------- evidence collection
def test_collect_evidence_dedupes_and_ranks():
    class _A(BaseSpecializedAgent):
        def run(self, *a, **k):
            return None
    agent = _A()
    r1 = ToolResult(tool="workspace_search", ok=True, citations=[
        {"text": "low", "document_id": "d1", "confidence": 0.2},
        {"text": "high", "document_id": "d2", "confidence": 0.9}])
    r2 = ToolResult(tool="workspace_search", ok=True, citations=[
        {"text": "high", "document_id": "d2", "confidence": 0.9}])   # duplicate → dropped
    ev = agent.collect_evidence([r1, r2])
    assert len(ev) == 2 and ev[0].text == "high" and ev[0].index == 1     # ranked by score


# --------------------------------------------------------------------- research agent
def test_derive_subquestions():
    assert derive_subquestions("mutexes vs semaphores")[0] == "mutexes vs semaphores"
    assert "mutexes" in derive_subquestions("mutexes vs semaphores")


def test_research_agent_full_run():
    ctx = _Ctx()
    task = AgentTask(task_type="research", objective="explain deadlocks and livelocks",
                     workspace_id="ws", owner_id="o")
    res = ResearchAgent().run(task, ctx, executor=_FakeExec(), events=ctx.events)
    assert res.success and res.phase == "done"
    assert res.evidence and res.output.title.startswith("Research:")
    assert "Report" in res.output.to_markdown() and res.timings.total_ms >= 0
    assert res.tool_calls > 0


def test_research_agent_reports_gaps_when_no_evidence():
    ctx = _Ctx()
    _mt = lambda name: ToolResult(tool=name, ok=True, context_text="", citations=[])
    empty = _FakeExec(per_tool={"workspace_search": _mt("workspace_search"),
                                "graph_search": _mt("graph_search")})   # graph_search is now a research tool too
    task = AgentTask(task_type="research", objective="obscure topic", workspace_id="ws", owner_id="o")
    res = ResearchAgent().run(task, ctx, executor=empty, events=ctx.events)
    assert res.success and res.knowledge_gaps                    # unanswered question flagged


# --------------------------------------------------------------------- writing agent
def test_writing_agent_uses_doc_type_and_provided_evidence():
    ctx = _Ctx()
    ev = [{"index": 1, "text": "fact", "document_id": "d1", "confidence": 0.8}]
    task = AgentTask(task_type="writing", objective="system design", workspace_id="ws", owner_id="o",
                     params={"doc_type": "design_doc", "evidence": ev})
    exec_ = _FakeExec()
    res = WritingAgent().run(task, ctx, executor=exec_, events=ctx.events)
    assert res.success and DOC_TYPES["design_doc"]["label"] in res.output.title
    assert exec_.calls == 0                                      # provided evidence → NO retrieval


# --------------------------------------------------------------------- comparison agent
def test_comparison_agent_requires_two_targets():
    ctx = _Ctx()
    one = AgentTask(task_type="comparison", objective="single thing", workspace_id="ws", owner_id="o")
    res = ComparisonAgent().run(one, ctx, executor=_FakeExec(), events=ctx.events)
    assert res.success is False and "two targets" in (res.error or "")


def test_comparison_agent_topic_targets():
    ctx = _Ctx()
    task = AgentTask(task_type="comparison", objective="compare TCP and UDP", workspace_id="ws",
                     owner_id="o", params={"targets": [{"topic": "TCP"}, {"topic": "UDP"}]})
    res = ComparisonAgent().run(task, ctx, executor=_FakeExec(), events=ctx.events)
    assert res.success and "Comparison" in res.output.title
    assert any(b.type == "table" for b in res.output.blocks)     # side-by-side target table


# --------------------------------------------------------------------- study agent
def test_study_agent_generates_assets_and_plan():
    ctx = _Ctx()
    per_tool = {
        "generate_notes": ToolResult(tool="generate_notes", ok=True,
            output={"asset_type": "note", "asset_id": "n1", "status": "queued", "route": "/r/n1"}),
        "generate_flashcards": ToolResult(tool="generate_flashcards", ok=True,
            output={"asset_type": "deck", "asset_id": "d1", "status": "queued", "route": "/r/d1"}),
        "query_dashboard": ToolResult(tool="query_dashboard", ok=True,
            output={"section": "learning", "data": {"weak_topics": [{"topic": "recursion"}]}}),
    }
    task = AgentTask(task_type="study", objective="prep for the exam", workspace_id="ws", owner_id="o",
                     params={"deliverables": ["study_guide", "flashcards", "learning_path", "weak_topics"]})
    res = StudyAgent().run(task, ctx, executor=_FakeExec(per_tool), events=ctx.events)
    assert res.success
    md = res.output.to_markdown()
    assert "Generated Study Materials" in md and "Study Plan" in md
    assert "recursion" in md                                     # weak topic surfaced from dashboard
    assert len(res.plan["created_assets"]) == 2


def test_study_agent_assets_only_no_plan():
    ctx = _Ctx()
    per_tool = {"generate_flashcards": ToolResult(tool="generate_flashcards", ok=True,
        output={"asset_type": "deck", "asset_id": "d1", "status": "queued", "route": "/r"})}
    task = AgentTask(task_type="study", objective="cards", workspace_id="ws", owner_id="o",
                     params={"deliverables": ["flashcards"]})
    res = StudyAgent().run(task, ctx, executor=_FakeExec(per_tool), events=ctx.events)
    assert res.success and res.plan["created_assets"]
